from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Callable

from fastapi import WebSocket

SEVERITY = {"no_helmet": "high", "no_helmet_no_vest": "high", "no_vest": "medium", "chain_open": "high"}
CONTRACT_VIOLATIONS = ("no_helmet", "no_vest", "no_helmet_no_vest")
HELMET_MISSING = ("no_helmet", "no_helmet_no_vest")
VEST_MISSING = ("no_vest", "no_helmet_no_vest")
HELMET_WEIGHT, VEST_WEIGHT = 0.75, 0.25

SCHEMA = """
CREATE TABLE IF NOT EXISTS cameras (
    id         TEXT    PRIMARY KEY,
    name       TEXT    NOT NULL,
    location   TEXT,
    stream_url TEXT,
    active     INTEGER NOT NULL DEFAULT 1,
    last_seen  TEXT
);
CREATE TABLE IF NOT EXISTS tracks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    camera_id  TEXT    NOT NULL REFERENCES cameras(id),
    track_id   INTEGER,
    first_seen TEXT    NOT NULL,
    last_seen  TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_unique ON tracks(camera_id, track_id) WHERE track_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_tracks_first ON tracks(first_seen);
CREATE TABLE IF NOT EXISTS events (
    id            TEXT    PRIMARY KEY,
    camera_id     TEXT    NOT NULL REFERENCES cameras(id),
    track_id      INTEGER,
    violation     TEXT    NOT NULL,
    start_ts      TEXT    NOT NULL,
    end_ts        TEXT,
    confidence    REAL,
    bbox          TEXT,
    snapshot_path TEXT,
    incident_id   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_ts);
CREATE TABLE IF NOT EXISTS alerts (
    id           TEXT    PRIMARY KEY,
    event_id     TEXT    NOT NULL REFERENCES events(id),
    sent_ts      TEXT    NOT NULL,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    ack_ts       TEXT,
    ack_by       TEXT
);
CREATE INDEX IF NOT EXISTS idx_alerts_sent ON alerts(sent_ts);
CREATE TABLE IF NOT EXISTS daily_stats (
    date              TEXT    NOT NULL,
    camera_id         TEXT    NOT NULL,
    persons_seen      INTEGER NOT NULL DEFAULT 0,
    helmet_compliance REAL,
    vest_compliance   REAL,
    safety_index      REAL,
    violations        INTEGER NOT NULL DEFAULT 0,
    helmet_violations INTEGER NOT NULL DEFAULT 0,
    vest_violations   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, camera_id)
);
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_utc(ts: str) -> str:
    dt = datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def local_date(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date().isoformat()


def local_day_bounds(day: str) -> tuple[str, str]:
    start = datetime.combine(date.fromisoformat(day), datetime.min.time()).astimezone()
    end = datetime.combine(date.fromisoformat(day) + timedelta(days=1), datetime.min.time()).astimezone()
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return start.astimezone(timezone.utc).strftime(fmt), end.astimezone(timezone.utc).strftime(fmt)


def camera_id(value) -> str:
    text = str(value).strip()
    return f"cam{text}" if text.isdigit() else text


def default_camera_name(cam: str) -> str:
    m = re.fullmatch(r"cam(\d+)", cam)
    return f"Camera {m.group(1)}" if m else cam


def ensure_camera(conn: sqlite3.Connection, cam: str, seen: str | None = None) -> None:
    conn.execute("INSERT OR IGNORE INTO cameras (id, name) VALUES (?, ?)", (cam, default_camera_name(cam)))
    if seen:
        conn.execute("UPDATE cameras SET last_seen = ? WHERE id = ? AND (last_seen IS NULL OR last_seen < ?)",
                     (seen, cam, seen))


def touch_track(conn: sqlite3.Connection, cam: str, track_id: int | None, ts: str) -> None:
    if track_id is None:
        conn.execute("INSERT INTO tracks (camera_id, track_id, first_seen, last_seen) VALUES (?, NULL, ?, ?)",
                     (cam, ts, ts))
        return
    conn.execute(
        "INSERT INTO tracks (camera_id, track_id, first_seen, last_seen) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (camera_id, track_id) WHERE track_id IS NOT NULL DO UPDATE SET "
        "last_seen = MAX(last_seen, excluded.last_seen), first_seen = MIN(first_seen, excluded.first_seen)",
        (cam, track_id, ts, ts))


def refresh_daily(conn: sqlite3.Connection, day: str, cam: str) -> None:
    start, end = local_day_bounds(day)
    persons = conn.execute("SELECT COUNT(*) FROM tracks WHERE camera_id = ? AND first_seen >= ? AND first_seen < ?",
                           (cam, start, end)).fetchone()[0]

    def violators(kinds: tuple[str, ...]) -> int:
        marks = ",".join("?" * len(kinds))
        return conn.execute(
            f"SELECT COUNT(DISTINCT track_id) + SUM(track_id IS NULL) FROM events "
            f"WHERE camera_id = ? AND start_ts >= ? AND start_ts < ? AND violation IN ({marks})",
            (cam, start, end, *kinds)).fetchone()[0] or 0

    helmet_v, vest_v = violators(HELMET_MISSING), violators(VEST_MISSING)
    violations = conn.execute("SELECT COUNT(*) FROM events WHERE camera_id = ? AND start_ts >= ? AND start_ts < ?",
                              (cam, start, end)).fetchone()[0]
    persons = max(persons, helmet_v, vest_v)
    if persons:
        helmet, vest = 1 - helmet_v / persons, 1 - vest_v / persons
        index = HELMET_WEIGHT * helmet + VEST_WEIGHT * vest
    else:
        helmet = vest = index = None
    conn.execute(
        "INSERT OR REPLACE INTO daily_stats (date, camera_id, persons_seen, helmet_compliance, vest_compliance, "
        "safety_index, violations, helmet_violations, vest_violations) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (day, cam, persons, helmet, vest, index, violations, helmet_v, vest_v))


def combine(rows) -> dict:
    persons = sum(r["persons_seen"] for r in rows)
    helmet_v = sum(r["helmet_violations"] for r in rows)
    vest_v = sum(r["vest_violations"] for r in rows)
    out = {"persons_seen": persons, "violations": sum(r["violations"] for r in rows),
           "helmet_compliance": None, "vest_compliance": None, "safety_index": None}
    if persons:
        out["helmet_compliance"] = round(1 - helmet_v / persons, 4)
        out["vest_compliance"] = round(1 - vest_v / persons, 4)
        out["safety_index"] = round(HELMET_WEIGHT * out["helmet_compliance"] + VEST_WEIGHT * out["vest_compliance"], 4)
    return out


def new_id() -> str:
    return str(uuid.uuid4())


def create_event(conn: sqlite3.Connection, *, cam: str, track_id: int | None, violation: str, ts: str,
                 confidence: float | None, bbox: list | None, snapshot_path: str | None,
                 incident_id: int | None = None, event_id: str | None = None) -> tuple[str, str]:
    event_id = event_id or new_id()
    alert_id = new_id()
    conn.execute(
        "INSERT INTO events (id, camera_id, track_id, violation, start_ts, confidence, bbox, snapshot_path, incident_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (event_id, cam, track_id, violation, ts, confidence, json.dumps(bbox) if bbox else None, snapshot_path, incident_id))
    conn.execute("INSERT INTO alerts (id, event_id, sent_ts) VALUES (?, ?, ?)", (alert_id, event_id, utc_now()))
    return event_id, alert_id


ALERT_SELECT = """
SELECT a.id AS alert_id, a.sent_ts, a.acknowledged, a.ack_ts, a.ack_by,
       e.id AS event_id, e.camera_id, e.track_id, e.violation, e.start_ts, e.end_ts, e.confidence, e.bbox,
       e.snapshot_path
FROM alerts a JOIN events e ON e.id = a.event_id
"""


def alert_payload(row: sqlite3.Row) -> dict:
    return {
        "alert_id": row["alert_id"], "event_id": row["event_id"], "camera_id": row["camera_id"],
        "track_id": row["track_id"], "violation": row["violation"], "severity": SEVERITY.get(row["violation"], "medium"),
        "ts": row["start_ts"], "end_ts": row["end_ts"], "sent_ts": row["sent_ts"],
        "confidence": row["confidence"], "bbox": json.loads(row["bbox"]) if row["bbox"] else None,
        "acknowledged": bool(row["acknowledged"]), "ack_ts": row["ack_ts"],
        "snapshot_url": f"/api/snapshots/{row['snapshot_path']}" if row["snapshot_path"] else None,
    }


def ws_violation(row: sqlite3.Row) -> dict:
    p = alert_payload(row)
    return {"type": "violation", "alert_id": p["alert_id"], "event_id": p["event_id"], "camera_id": p["camera_id"],
            "track_id": p["track_id"], "violation": p["violation"], "severity": p["severity"], "ts": p["ts"],
            "bbox": p["bbox"], "snapshot_url": p["snapshot_url"]}


def init_live(conn: sqlite3.Connection, cameras: int) -> None:
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    drop_detections_track_column(conn)
    migrate_v1(conn)
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for i in range(1, cameras + 1):
        ensure_camera(conn, f"cam{i}")


def drop_detections_track_column(conn: sqlite3.Connection) -> None:
    cols = [r[1] for r in conn.execute("PRAGMA table_info(detections)")]
    if "track_id" not in cols:
        return
    conn.executescript("""
        CREATE TABLE detections_new (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT    NOT NULL,
            camera     TEXT    NOT NULL,
            label      TEXT    NOT NULL,
            confidence REAL    NOT NULL,
            severity   TEXT
        );
        INSERT INTO detections_new (id, created_at, camera, label, confidence, severity)
            SELECT id, created_at, camera, label, confidence, severity FROM detections;
        DROP TABLE detections;
        ALTER TABLE detections_new RENAME TO detections;
        CREATE INDEX IF NOT EXISTS idx_detections_created ON detections(created_at);
    """)


def migrate_v1(conn: sqlite3.Connection) -> None:
    cols = {r[1]: r[2] for r in conn.execute("PRAGMA table_info(cameras)")}
    if not cols or cols.get("id", "").upper() != "INTEGER":
        return
    print("Migrating cameras/tracks/alerts/daily_stats to the API-contract tables...")
    for t in ("cameras", "tracks", "alerts", "daily_stats"):
        conn.execute(f"ALTER TABLE {t} RENAME TO {t}_v1")
    conn.execute("DROP INDEX IF EXISTS idx_tracks_open")
    conn.executescript(SCHEMA)
    for r in conn.execute("SELECT id, name, location, active FROM cameras_v1").fetchall():
        cam = f"cam{r[0]}"
        conn.execute("INSERT OR IGNORE INTO cameras (id, name, location, active) VALUES (?, ?, ?, ?)",
                     (cam, default_camera_name(cam), r[2], r[3]))
    alert_cols = {r[1] for r in conn.execute("PRAGMA table_info(alerts_v1)")}
    has_incident = "incident_id" in alert_cols
    rows = conn.execute(f"SELECT created_at, camera, label, confidence{', incident_id' if has_incident else ''} "
                        "FROM alerts_v1 ORDER BY id").fetchall()
    for r in rows:
        cam = f"cam{r[1]}"
        ensure_camera(conn, cam)
        ts = to_utc(r[0])
        incident = r[4] if has_incident else None
        snap = None
        if incident is not None:
            s = conn.execute("SELECT snapshot FROM incidents WHERE id = ?", (incident,)).fetchone()
            snap = s[0] if s else None
        event_id, _ = create_event(conn, cam=cam, track_id=None, violation=r[2], ts=ts, confidence=r[3], bbox=None,
                                   snapshot_path=snap, incident_id=incident)
        conn.execute("UPDATE events SET end_ts = start_ts WHERE id = ?", (event_id,))
        conn.execute("UPDATE alerts SET sent_ts = ? WHERE event_id = ?", (ts, event_id))
    old = {}
    for d, cam, label, n in conn.execute("SELECT day, camera, label, count FROM daily_stats_v1").fetchall():
        old.setdefault((d, f"cam{cam}"), {})[label] = n
    for (d, cam), c in old.items():
        ensure_camera(conn, cam)
        helmet_v, vest_v = c.get("no_helmet", 0), c.get("no_vest", 0)
        persons = max(c.get("helmet", 0) + helmet_v, c.get("vest", 0) + vest_v)
        violations = sum(n for k, n in c.items() if k in SEVERITY)
        if persons:
            hc, vc = 1 - helmet_v / persons, 1 - vest_v / persons
            idx = HELMET_WEIGHT * hc + VEST_WEIGHT * vc
        else:
            hc = vc = idx = None
        conn.execute(
            "INSERT OR REPLACE INTO daily_stats (date, camera_id, persons_seen, helmet_compliance, vest_compliance, "
            "safety_index, violations, helmet_violations, vest_violations) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (d, cam, persons, hc, vc, idx, violations, helmet_v, vest_v))
    for t in ("alerts_v1", "tracks_v1", "daily_stats_v1", "cameras_v1"):
        conn.execute(f"DROP TABLE {t}")
    print(f"Migrated {len(rows)} alerts.")


class AlertHub:

    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def broadcast(self, message: dict) -> None:
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:
                self.clients.discard(ws)


Connect = Callable[[], sqlite3.Connection]
