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

## Which model it uses
1. `SAFESIGHT_WEIGHTS` environment variable, if set
2. otherwise the newest `runs/**/weights/best.pt` (after training)
3. otherwise the stock `yolo11s.pt` - it only knows COCO classes (person, car...), so it never reports PPE violations; the dashboard shows a notice while this is the case

## Accounts and permissions
The account list is `api/seed_users.json` if it exists, otherwise `api/seed_users.example.json` (test accounts). Every time the API starts it syncs the database with that file: new accounts are added, changed names/roles/passwords are applied, and accounts removed from the file are deleted. So to add, remove or change an account, edit the file and restart the API. Passwords are stored only as bcrypt hashes in `api/safesight.db`.

Every endpoint except `/health` and `/auth/*` needs `Authorization: Bearer <token>` from `/auth/login`. Sessions expire after 30 minutes without requests. What each role may do is `ROLE_PERMISSIONS` in `api/auth.py` (keep `Frontend/auth.js` in sync for mock mode).

Forgot password: there is no email server yet, so `/auth/forgot-password` prints the reset link in the server console. Set `SAFESIGHT_FRONTEND_URL` if the Frontend is not served at `http://127.0.0.1:5500/Frontend`.

## Endpoints
| Method | Path | Permission | Returns |
|---|---|---|---|
| POST | `/auth/login` (JSON `email`, `password`) | - | `{token, user: {name, email, role, permissions}}`, 401 if wrong |
| POST | `/auth/logout` | - | ends the session |
| GET | `/auth/me` | signed in | the current user |
| POST | `/auth/forgot-password` (JSON `email`) | - | always `{ok: true}` |
| POST | `/auth/reset-password` (JSON `token`, `password` >= 8 chars) | - | `{ok: true}`, 400 if the link is invalid/expired |
| POST | `/detect` (form: `file`, optional `camera`) | `check_image` | `{width, height, detections: [{label, confidence, box: [x1,y1,x2,y2], severity}]}` |
| GET | `/alerts?limit=20` | `view_alerts` | latest violations `[{time, date, camera, violation, level}]` |
| GET | `/stats` | `view_stats` | `{cameras, violationsToday, compliance}` |
| GET | `/users` | `view_users` | `[{name, email, role}]` |
| GET | `/incidents?limit=50` | `view_reports` | one row per checked image that had violations `[{id, date, time, camera, severity, violations, types}]` |
| GET | `/incidents/<id>/report.pdf?lang=ar\|en` | `view_reports` | the incident report as a PDF, in that language |
| GET | `/health` | - | loaded weights and class names |

Violations and severity: `no_helmet` high, `chain_open` high, `no_vest` medium. Compliance = helmet+vest seen / (helmet+vest+no_helmet+no_vest) today. `SAFESIGHT_CAMERAS` (default 1) is the number shown on the cameras card.

## Incident reports (PDF)
Every `/detect` call that finds a violation stores an incident and a snapshot with the boxes drawn (`api/snapshots/<id>.jpg`, not committed). The PDF is built when someone opens it, in the language they ask for: the sentences are fixed templates per language in `api/reports.py` (`TEXT`), only numbers, dates, camera and violation types change. Only `project_manager` and `hse` have `view_reports`.

Arabic needs a font with Arabic letters; by default `C:\Windows\Fontsrial.ttf` / `arialbd.ttf`. On another machine set `SAFESIGHT_FONT_DIR`, `SAFESIGHT_FONT` and `SAFESIGHT_FONT_BOLD`.

## Translation (Arabic <-> English)
The site texts are written in English only (`Frontend/i18n.js`). Arabic comes from local MarianMT models (`Helsinki-NLP/opus-mt-en-ar` and `opus-mt-ar-en`) through `POST /translate` (`{texts, source, target}`, no login needed, en<->ar only). The models download once into the Hugging Face cache (~600 MB) and then run offline, on the GPU if there is one.

- Every translation is stored in the `translations` table, so a text is translated only once; the browser also keeps them in localStorage.
- Wrong translations are corrected in `api/translation_fixes.json` (exact English text -> correct Arabic). A fix always wins over the model; restart the API after editing. If a correction does not show in the browser, clear the site's localStorage (key `i18n_cache_ar_v1`).
- If the API is down, texts without a stored translation show in English.
- Set `SAFESIGHT_TRANSLATE=0` to skip loading the models at start-up (they then load on the first request).
