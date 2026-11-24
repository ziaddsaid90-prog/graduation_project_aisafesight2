# AI SafeSight API

FastAPI server that runs the YOLO model for the Frontend and stores violations in SQLite (`api/safesight.db`, created automatically, not committed).

## Run
From the repo root, using the same `.venv` as training (see `src/training/README.md`):
```bash
.venv\Scripts\activate
pip install -r api/requirements.txt
uvicorn api.main:app --reload
```
Then open `Frontend/index.html` with Live Server. Manual testing: http://127.0.0.1:8000/docs

To see live violations without a camera, run `python tools/fake_pipeline.py` while the API is up: it pretends to be the live pipeline.

## Which model it uses
1. `SAFESIGHT_WEIGHTS` environment variable, if set
2. otherwise the newest `runs/**/weights/best.pt` (after training)
3. otherwise the stock `yolo11s.pt` - it only knows COCO classes (person, car...), so it never reports PPE violations; the dashboard shows a notice while this is the case

## Accounts and permissions
The account list is `api/seed_users.json` if it exists, otherwise `api/seed_users.example.json` (test accounts). Every time the API starts it syncs the database with that file: new accounts are added, changed names/roles/passwords are applied, and accounts removed from the file are deleted. So to add, remove or change an account, edit the file and restart the API. Passwords are stored only as bcrypt hashes in `api/safesight.db`.

The API follows `docs/api_contracts.md` (the contract between the live pipeline, this backend and the dashboard). All REST paths start with `/api`; the WebSocket is `/ws/alerts`.

Every endpoint except `/api/health`, `/api/translate`, `/api/auth/*` and `/api/ingest/*` needs `Authorization: Bearer <token>` from `/api/auth/login`. Sessions expire after 30 minutes without requests. What each role may do is `ROLE_PERMISSIONS` in `api/auth.py` (keep `Frontend/auth.js` in sync for mock mode).

Forgot password: there is no email server yet, so `/api/auth/forgot-password` prints the reset link in the server console. Set `SAFESIGHT_FRONTEND_URL` if the Frontend is not served at `http://127.0.0.1:5500/Frontend`.

## How violations arrive
1. **Live pipeline** (Model Team, separate program): watches the camera, tracks people with ByteTrack, decides `no_helmet` / `no_vest` / `no_helmet_no_vest` per person, and sends `POST /api/ingest/events` when a violation starts and again when it ends. Every few seconds it also sends the people it sees to `POST /api/ingest/tracks` (needed for compliance %).
2. **Manual check** (`POST /api/detect`): a user uploads one image, the server runs its own model on it, and every violation becomes an event + alert the same way.

Times are ISO-8601 UTC (`2026-11-23T10:15:02Z`). Days (`daily_stats.date`, "today") are the server's local date.

### Pipeline -> backend
Ingest endpoints are for programs, not users. With `SAFESIGHT_INGEST_KEY` set they need the header `X-API-Key: <that key>`; without it they accept requests only from this computer (127.0.0.1).

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/api/ingest/events` | `{event_id, camera_id, track_id, violation, state: "start"\|"end", ts, confidence, bbox: [x1,y1,x2,y2], snapshot_jpeg_base64}` (only `camera_id`, `violation`, `ts` are required for a start; `event_id` for an end) | `201 {event_id, alert_id}`. Sending the same start twice returns the same ids |
| POST | `/api/ingest/tracks` *(addition to the contract)* | `{camera_id, ts, track_ids: [17, 18, ...]}` = the people visible now | `{ok, new_tracks}`. New ids count in `persons_seen`; also marks the camera online |

`camera_id` is a text id like `cam1` (`1` is turned into `cam1`). An unknown camera is added automatically.

### Backend -> dashboard (WebSocket `/ws/alerts`)
1. Connect to `ws://127.0.0.1:8000/ws/alerts`
2. Send `{"token": "<token from /api/auth/login>"}` first (browsers cannot set headers on a WebSocket, and a token in the URL would end up in logs)
3. The server answers `{"type": "ready"}`, then sends:
   - `{"type": "violation", alert_id, event_id, camera_id, track_id, violation, severity, ts, bbox, snapshot_url}`
   - `{"type": "event_end", event_id, ts}`
   - `{"type": "stats", camera_id, ts}` when new people were seen (refresh the counters)
   - `{"type": "ack", alert_id}` when someone acknowledged an alert *(addition)*

Close code 4401 = not signed in / expired (the dashboard logs out), 4403 = the role has no `view_alerts`. The dashboard reconnects by itself and still refreshes every 30 s as a fallback.

### REST (dashboard -> backend)
| Method | Path | Permission | Returns |
|---|---|---|---|
| GET | `/api/events?from=&to=&camera=&violation=&limit=200` | `view_stats` | events, newest first. `from`/`to` are dates (`2026-11-24`, default today) or ISO times |
| GET | `/api/alerts?acknowledged=&camera=&limit=50` | `view_alerts` | `[{alert_id, event_id, camera_id, track_id, violation, severity, ts, end_ts, sent_ts, confidence, bbox, acknowledged, ack_ts, snapshot_url}]` |
| POST | `/api/alerts/{alert_id}/ack` | `view_alerts` | the acknowledged alert (stores who and when) |
| GET | `/api/statistics?from=&to=&camera=` | `view_stats` | `{persons_seen, helmet_compliance, vest_compliance, safety_index (0-1), violations, by_violation, active_alerts, alerts_sent}` |
| GET | `/api/cameras` | `view_stats` | `[{id, name, location, stream_url, active, last_seen, online, last_snapshot_url}]`; `online` = sent something in the last 10 minutes |
| GET | `/api/snapshots/{file}` | `view_alerts` | a snapshot image (the `snapshot_url` of an alert/event) |
| GET | `/api/analytics?days=7` *(addition)* | `view_stats` | chart series: `violationsByHour` (today), `days` + `violationsByDay` + `complianceByDay` (safety index %), `violationsByType` |
| POST | `/api/detect` (form: `file`, optional `camera`, default `cam1`) | `check_image` | `{width, height, detections: [{label, confidence, box, severity}], incident_id}` |
| GET | `/api/incidents?limit=50` | `view_reports` | violation reports `[{id, date, time, camera, severity, violations, types}]` |
| GET | `/api/incidents/<id>/report.pdf?lang=ar\|en` | `view_reports` | the report as a PDF |
| GET | `/api/users` | `view_users` | `[{name, email, role}]` |
| POST | `/api/auth/login` (JSON `email`, `password`) | - | `{token, user: {name, email, role, permissions}}`, 401 if wrong |
| POST | `/api/auth/logout`, `/api/auth/forgot-password`, `/api/auth/reset-password`; GET `/api/auth/me` | - | as before |
| GET | `/api/health` | - | loaded weights and class names |

Severity: `no_helmet` and `no_helmet_no_vest` high, `no_vest` medium (`chain_open` high is still accepted for the old demo model).

## Database tables (as in the contract)
| Table | What it holds |
|---|---|
| `cameras` | `id` (`cam1`...), `name`, `location`, `stream_url`, `active`, plus `last_seen`. `cam1`..`cam<SAFESIGHT_CAMERAS>` are created at start-up |
| `tracks` | one tracked person: `camera_id`, `track_id` (ByteTrack id; empty for people in a manually checked image), `first_seen`, `last_seen` |
| `events` | one violation: `id` (UUID), `camera_id`, `track_id`, `violation`, `start_ts`, `end_ts` (empty while ongoing), `confidence`, `bbox` (JSON), `snapshot_path` |
| `alerts` | one per event: `id` (UUID), `event_id`, `sent_ts`, `acknowledged`, `ack_ts`, plus `ack_by` |
| `daily_stats` | per local day and camera: `persons_seen`, `helmet_compliance`, `vest_compliance`, `safety_index` = 0.75 x helmet + 0.25 x vest, `violations`, plus the counts behind the rates. Recomputed from `tracks` and `events` on every ingest |
| `detections` | raw log of every box `/api/detect` found |

Compliance: helmet = 1 - (people with `no_helmet`/`no_helmet_no_vest`) / `persons_seen`, vest the same with `no_vest`/`no_helmet_no_vest`. A person counts once per day however many events they have.

The first version of these tables (integer camera ids, alerts without events) is converted automatically the first time this version starts.

## Incident reports (PDF)
Every violation from `/api/detect`, and every live event that comes with a snapshot, stores an incident and a snapshot with the boxes drawn (`api/snapshots/<id>.jpg`, not committed). The PDF is built when someone opens it, in the language they ask for: the sentences are fixed templates per language in `api/reports.py` (`TEXT`), only numbers, dates, camera and violation types change. Only `project_manager` and `hse` have `view_reports`.

Arabic needs a font with Arabic letters; by default `C:\Windows\Fontsrial.ttf` / `arialbd.ttf`. On another machine set `SAFESIGHT_FONT_DIR`, `SAFESIGHT_FONT` and `SAFESIGHT_FONT_BOLD`.

## Translation (Arabic <-> English)
The site texts are written in English only (`Frontend/i18n.js`). Arabic comes from local MarianMT models (`Helsinki-NLP/opus-mt-en-ar` and `opus-mt-ar-en`) through `POST /api/translate` (`{texts, source, target}`, no login needed, en<->ar only). The models download once into the Hugging Face cache (~600 MB) and then run offline, on the GPU if there is one.

- Every translation is stored in the `translations` table, so a text is translated only once; the browser also keeps them in localStorage.
- Wrong translations are corrected in `api/translation_fixes.json` (exact English text -> correct Arabic). A fix always wins over the model; restart the API after editing. If a correction does not show in the browser, clear the site's localStorage (key `i18n_cache_ar_v3`).
- If the API is down, texts without a stored translation show in English.
- Set `SAFESIGHT_TRANSLATE=0` to skip loading the models at start-up (they then load on the first request).
