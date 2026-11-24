# API Contracts: Live Pipeline ↔ Backend ↔ Dashboard

Owner: Dashboard Team (owns the contract) + Model Team. Decision D-012.
**Status: implemented by the Dashboard Team in `api/` (FastAPI). The Model Team builds the live pipeline against it.**
Additions to the first draft are marked *(added)*.

## Flow

```
Camera → Live pipeline (Model Team) ──POST /api/ingest/events──▶ Backend (Dashboard Team)
                                    ──POST /api/ingest/tracks──▶   │ stores in DB
                                                                   └──WebSocket /ws/alerts──▶ Dashboard
```

## Shared rules

- Time: ISO-8601 in UTC, e.g. `2026-11-23T10:15:02Z`. (A time with an offset such as `+02:00` is accepted and converted.)
- Boxes: pixel coordinates `[x1, y1, x2, y2]` on the original frame.
- Class and status names: exactly as in `docs/class_mapping.md` (`no_helmet`, `no_vest`, `no_helmet_no_vest`).
- IDs: `event_id` and `alert_id` are UUID strings. Camera ids are text, e.g. `cam1`.
- Days in `daily_stats` are the site's local date.

## Database tables

### `cameras`
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | e.g. `cam1` |
| name | TEXT | |
| location | TEXT | |
| stream_url | TEXT | USB index or RTSP URL |
| active | BOOLEAN | |
| last_seen | TIMESTAMP | *(added)* last time the pipeline sent anything for this camera |

### `tracks` (one tracked person)
| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| camera_id | TEXT FK → cameras | |
| track_id | INTEGER | ByteTrack ID, unique per camera session. NULL for people in a manually checked image |
| first_seen | TIMESTAMP | |
| last_seen | TIMESTAMP | |

### `events` (one violation)
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | `event_id` |
| camera_id | TEXT FK → cameras | |
| track_id | INTEGER | |
| violation | TEXT | `no_helmet` / `no_vest` / `no_helmet_no_vest` |
| start_ts | TIMESTAMP | |
| end_ts | TIMESTAMP NULL | NULL while ongoing |
| confidence | REAL | |
| bbox | TEXT (JSON) | person box at alert time |
| snapshot_path | TEXT | saved frame |

### `alerts`
| Column | Type | Notes |
|---|---|---|
| id | TEXT PK | `alert_id` |
| event_id | TEXT FK → events | |
| sent_ts | TIMESTAMP | |
| acknowledged | BOOLEAN | |
| ack_ts | TIMESTAMP NULL | |
| ack_by | TEXT | *(added)* email of the user who acknowledged |

### `daily_stats`
| Column | Type | Notes |
|---|---|---|
| date | DATE | |
| camera_id | TEXT | |
| persons_seen | INTEGER | distinct tracks first seen that day |
| helmet_compliance | REAL | 0–1 = 1 − people with `no_helmet`/`no_helmet_no_vest` ÷ persons_seen |
| vest_compliance | REAL | 0–1 = 1 − people with `no_vest`/`no_helmet_no_vest` ÷ persons_seen |
| safety_index | REAL | 0.75 × helmet + 0.25 × vest |
| violations | INTEGER | events that started that day |
| helmet_violations, vest_violations | INTEGER | *(added)* the counts behind the rates, so several cameras/days can be combined |

## Pipeline → Backend

Authentication *(added)*: if the backend has `SAFESIGHT_INGEST_KEY` set, send it as the header `X-API-Key`. Without it the backend accepts ingest only from the same computer.

### `POST /api/ingest/events`
Sent by the live pipeline when a violation starts, and again when it ends.
```json
{
  "event_id": "8f1c…",
  "camera_id": "cam1",
  "track_id": 17,
  "violation": "no_helmet",
  "state": "start",
  "ts": "2026-11-23T10:15:02Z",
  "confidence": 0.87,
  "bbox": [412, 120, 530, 460],
  "snapshot_jpeg_base64": "…"
}
```
`state` is `start` or `end`. Response: `201 {"event_id": "…", "alert_id": "…"}`.
- For `end`, only `event_id`, `camera_id`, `violation`, `state` and `ts` matter.
- If `event_id` is left out on a start, the backend makes one and returns it.
- Re-sending the same start (same `event_id`) returns the same ids; no duplicate alert.

### `POST /api/ingest/tracks` *(added)*
Compliance needs to know how many people were seen, not only the ones in violation. Every few seconds the pipeline sends the ByteTrack ids it currently sees:
```json
{ "camera_id": "cam1", "ts": "2026-11-23T10:15:00Z", "track_ids": [15, 16, 17] }
```
Response: `{"ok": true, "new_tracks": 1}`. New ids count in `persons_seen`; the call also marks the camera online.

## Backend → Dashboard (WebSocket `/ws/alerts`)

The first message from the dashboard must be `{"token": "<login token>"}`; the backend answers `{"type": "ready"}`.

```json
{
  "type": "violation",
  "alert_id": "c2d9…",
  "event_id": "8f1c…",
  "camera_id": "cam1",
  "track_id": 17,
  "violation": "no_helmet",
  "severity": "high",
  "ts": "2026-11-23T10:15:02Z",
  "bbox": [412, 120, 530, 460],
  "snapshot_url": "/api/snapshots/events/8f1c….jpg"
}
```
Other message types: `{"type": "event_end", "event_id": "…", "ts": "…"}`, `{"type": "stats", "camera_id": "…", "ts": "…"}` (counters changed, refresh) and *(added)* `{"type": "ack", "alert_id": "…"}`.

## REST endpoints (Dashboard → Backend)

All need `Authorization: Bearer <login token>`.

| Method | Path | Returns |
|---|---|---|
| GET | `/api/events?from=&to=&camera=&violation=` | list of events |
| GET | `/api/alerts?acknowledged=` | list of alerts (with their event's camera, violation, times and `snapshot_url`) |
| POST | `/api/alerts/{alert_id}/ack` | acknowledged alert |
| GET | `/api/statistics?from=&to=&camera=` | compliance (0–1), Safety Index, counts per violation, `active_alerts` |
| GET | `/api/cameras` | list of cameras (with `online` and `last_snapshot_url`) |
| GET | `/api/snapshots/{file}` | snapshot image |
| GET | `/api/analytics?days=7` | *(added)* the chart series the dashboard needs in one call |

`from`/`to` are dates (`2026-11-23`, default today) or ISO times.
