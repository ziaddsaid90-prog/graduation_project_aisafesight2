from __future__ import annotations

import asyncio
import io
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import (Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile,
                     WebSocket, WebSocketDisconnect)
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from ultralytics import YOLO

from api.auth import ROLE_PERMISSIONS, Auth, user_payload
from api.reports import Reports
from api.translator import Translator

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("SAFESIGHT_DB", ROOT / "api" / "safesight.db"))
SEED_FILE = ROOT / "api" / "seed_users.json"
if not SEED_FILE.exists():
    SEED_FILE = ROOT / "api" / "seed_users.example.json"
CAMERAS = int(os.environ.get("SAFESIGHT_CAMERAS", 1))
FRONTEND_URL = os.environ.get("SAFESIGHT_FRONTEND_URL", "http://127.0.0.1:5500/Frontend")
BI_REPORT = Path(os.environ.get("SAFESIGHT_BI_REPORT", ROOT / "powerbi" / "AI_SafeSight_CHV.pdf"))

SEVERITY = {"no_helmet": "high", "chain_open": "high", "no_vest": "medium"}
PPE_PAIRS = [("helmet", "no_helmet"), ("vest", "no_vest")]
CONF_THRESHOLD = float(os.environ.get("SAFESIGHT_CONF", 0.4))
TRACK_GAP = int(os.environ.get("SAFESIGHT_TRACK_GAP", 10))  # seconds before a lost violation counts as new
TRACK_IOU = 0.3


def find_weights() -> Path:
    if os.environ.get("SAFESIGHT_WEIGHTS"):
        return Path(os.environ["SAFESIGHT_WEIGHTS"])
    trained = sorted((ROOT / "runs").glob("**/weights/best.pt"), key=lambda p: p.stat().st_mtime)
    if trained:
        return trained[-1]
    return ROOT / "yolo11s.pt"


WEIGHTS = find_weights()
model = YOLO(str(WEIGHTS))
IS_PPE_MODEL = any(name in SEVERITY for name in model.names.values())
if not IS_PPE_MODEL:
    print(f"WARNING: {WEIGHTS.name} has no PPE classes (it is the stock COCO model). "
          "Detection works but will never report violations until a trained best.pt exists.")


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS detections (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT    NOT NULL,
                camera     INTEGER NOT NULL,
                label      TEXT    NOT NULL,
                confidence REAL    NOT NULL,
                severity   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_detections_created ON detections(created_at);

            CREATE TABLE IF NOT EXISTS cameras (
                id         INTEGER PRIMARY KEY,
                name       TEXT    NOT NULL,
                location   TEXT,
                active     INTEGER NOT NULL DEFAULT 1,
                created_at TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tracks (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                camera     INTEGER NOT NULL REFERENCES cameras(id),
                label      TEXT    NOT NULL,
                first_seen TEXT    NOT NULL,
                last_seen  TEXT    NOT NULL,
                hits       INTEGER NOT NULL DEFAULT 1,
                x1 REAL, y1 REAL, x2 REAL, y2 REAL
            );
            CREATE INDEX IF NOT EXISTS idx_tracks_open ON tracks(camera, label, last_seen);

            CREATE TABLE IF NOT EXISTS alerts (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at   TEXT    NOT NULL,
                camera       INTEGER NOT NULL REFERENCES cameras(id),
                track_id     INTEGER REFERENCES tracks(id),
                label        TEXT    NOT NULL,
                severity     TEXT    NOT NULL,
                confidence   REAL
            );

            CREATE TABLE IF NOT EXISTS daily_stats (
                day    TEXT    NOT NULL,
                camera INTEGER NOT NULL,
                label  TEXT    NOT NULL,
                count  INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (day, camera, label)
            );
        """)
        if "track_id" not in [r["name"] for r in conn.execute("PRAGMA table_info(detections)")]:
            conn.execute("ALTER TABLE detections ADD COLUMN track_id INTEGER REFERENCES tracks(id)")
        if "incident_id" not in [r["name"] for r in conn.execute("PRAGMA table_info(alerts)")]:
            conn.execute("ALTER TABLE alerts ADD COLUMN incident_id INTEGER")

        stamp = datetime.now().isoformat(timespec="seconds")
        conn.executemany("INSERT OR IGNORE INTO cameras (id, name, created_at) VALUES (?, ?, ?)",
                         [(i, f"Camera {i}", stamp) for i in range(1, CAMERAS + 1)])
        # Fill the new tables once from detections stored before they existed
        conn.execute("INSERT OR IGNORE INTO cameras (id, name, created_at) "
                     "SELECT DISTINCT camera, 'Camera ' || camera, ? FROM detections", (stamp,))
        if conn.execute("SELECT COUNT(*) FROM daily_stats").fetchone()[0] == 0:
            conn.execute("INSERT INTO daily_stats (day, camera, label, count) "
                         "SELECT substr(created_at, 1, 10), camera, label, COUNT(*) FROM detections GROUP BY 1, 2, 3")
        if conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0] == 0:
            conn.execute("INSERT INTO alerts (created_at, camera, label, severity, confidence) "
                         "SELECT created_at, camera, label, severity, confidence FROM detections "
                         "WHERE severity IS NOT NULL ORDER BY id")


def link_old_alerts() -> None:
    """Alerts stored before incident_id existed get the incident (snapshot) saved in the same /detect call."""
    with db() as conn:
        conn.execute("UPDATE alerts SET incident_id = (SELECT id FROM incidents i WHERE i.created_at = alerts.created_at "
                     "AND i.camera = alerts.camera ORDER BY id LIMIT 1) WHERE incident_id IS NULL")


def iou(a: list[float], b: list[float]) -> float:
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = w * h
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def assign_tracks(conn: sqlite3.Connection, camera: int, now: datetime, detections: list[dict]) -> list[int]:
    """Give every violation a track. A violation that matches a track seen on the same camera in the
    last TRACK_GAP seconds (same label, boxes overlap) continues it; otherwise it starts a new track.
    Returns the ids of the new tracks - only those raise an alert, so one worker without a helmet
    standing in front of the camera is one alert, not one per frame."""
    stamp = now.isoformat(timespec="seconds")
    since = (now - timedelta(seconds=TRACK_GAP)).isoformat(timespec="seconds")
    used: set[int] = set()
    new_tracks = []
    for d in detections:
        if not d["severity"]:
            continue
        open_tracks = conn.execute(
            "SELECT id, x1, y1, x2, y2 FROM tracks WHERE camera = ? AND label = ? AND last_seen >= ?",
            (camera, d["label"], since)).fetchall()
        best, best_iou = None, TRACK_IOU
        for t in open_tracks:
            overlap = iou(d["box"], [t["x1"], t["y1"], t["x2"], t["y2"]])
            if t["id"] not in used and overlap >= best_iou:
                best, best_iou = t["id"], overlap
        if best is None:
            best = conn.execute(
                "INSERT INTO tracks (camera, label, first_seen, last_seen, x1, y1, x2, y2) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (camera, d["label"], stamp, stamp, *d["box"])).lastrowid
            new_tracks.append(best)
        else:
            conn.execute("UPDATE tracks SET last_seen = ?, hits = hits + 1, x1 = ?, y1 = ?, x2 = ?, y2 = ? WHERE id = ?",
                         (stamp, *d["box"], best))
        used.add(best)
        d["track_id"] = best
    return new_tracks


def alert_payload(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "time": row["created_at"][11:16], "date": row["created_at"][:10],
            "camera": row["camera"], "violation": row["label"], "level": row["severity"],
            "hasFrame": row["incident_id"] is not None}


class AlertHub:
    """Dashboards connected to /ws/alert; /detect pushes new alerts to all of them."""

    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def broadcast(self, message: dict) -> None:
        for ws in list(self.clients):
            try:
                await ws.send_json(message)
            except Exception:
                self.clients.discard(ws)


hub = AlertHub()


init_db()
auth = Auth(db, SEED_FILE)
reports = Reports(db, Path(os.environ.get("SAFESIGHT_SNAPSHOTS", ROOT / "api" / "snapshots")))
link_old_alerts()
translator = Translator(db, ROOT / "api" / "translation_fixes.json")
if os.environ.get("SAFESIGHT_TRANSLATE", "1") != "0":
    translator.preload()

app = FastAPI(title="AI SafeSight API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class TranslateBody(BaseModel):
    texts: list[str]
    target: str = "ar"
    source: str = "en"


@app.post("/translate")
def translate(body: TranslateBody):
    from api.translator import MAX_CHARS, MAX_TEXTS
    if len(body.texts) > MAX_TEXTS or any(len(t) > MAX_CHARS for t in body.texts):
        raise HTTPException(status_code=413, detail=f"At most {MAX_TEXTS} texts of {MAX_CHARS} characters")
    try:
        return {"translations": translator.translate(body.texts, body.source, body.target)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


class LoginBody(BaseModel):
    email: str
    password: str


class ForgotBody(BaseModel):
    email: str


class ResetBody(BaseModel):
    token: str
    password: str = Field(min_length=8)


@app.post("/auth/login")
def login(body: LoginBody):
    return auth.login(body.email, body.password)


@app.post("/auth/logout")
def logout(authorization: str = Header(default="")):
    token = authorization.partition(" ")[2]
    if token:
        auth.logout(token)
    return {"ok": True}


@app.get("/auth/me")
def me(user=Depends(auth.current_user())):
    return user_payload(user)


@app.post("/auth/forgot-password")
def forgot_password(body: ForgotBody):
    token = auth.create_reset_token(body.email)
    if token:
        print(f"[password reset] {body.email}: {FRONTEND_URL}/reset-password.html?token={token}")
    return {"ok": True}


@app.post("/auth/reset-password")
def reset_password(body: ResetBody):
    auth.reset_password(body.token, body.password)
    return {"ok": True}


@app.get("/users")
def users(user=Depends(auth.require("view_users"))):
    return auth.list_users()


@app.get("/health")
def health():
    return {"status": "ok", "weights": WEIGHTS.name, "ppe_model": IS_PPE_MODEL,
            "classes": list(model.names.values())}


@app.post("/detect")
async def detect(file: UploadFile = File(...), camera: int = Form(1), user=Depends(auth.require("check_image"))):
    try:
        image = Image.open(io.BytesIO(await file.read())).convert("RGB")
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="The file is not a valid image")

    result = model(image, conf=CONF_THRESHOLD, verbose=False)[0]
    when = datetime.now()
    now = when.isoformat(timespec="seconds")

    detections = []
    for box in result.boxes:
        label = model.names[int(box.cls)]
        detections.append({
            "label": label,
            "confidence": round(float(box.conf), 2),
            "box": [round(v) for v in box.xyxy[0].tolist()],
            "severity": SEVERITY.get(label),
        })

    incident_id = reports.record_incident(image, detections, camera, WEIGHTS.name, when)

    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO cameras (id, name, created_at) VALUES (?, ?, ?)",
                     (camera, f"Camera {camera}", now))
        new_tracks = set(assign_tracks(conn, camera, when, detections))
        conn.executemany(
            "INSERT INTO detections (created_at, camera, label, confidence, severity, track_id) VALUES (?, ?, ?, ?, ?, ?)",
            [(now, camera, d["label"], d["confidence"], d["severity"], d.get("track_id")) for d in detections],
        )
        conn.executemany(
            "INSERT INTO daily_stats (day, camera, label, count) VALUES (?, ?, ?, 1) "
            "ON CONFLICT (day, camera, label) DO UPDATE SET count = count + 1",
            [(now[:10], camera, d["label"]) for d in detections],
        )
        alert_ids = [conn.execute(
            "INSERT INTO alerts (created_at, camera, track_id, label, severity, confidence, incident_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now, camera, d["track_id"], d["label"], d["severity"], d["confidence"], incident_id)).lastrowid
            for d in detections if d.get("track_id") in new_tracks]
        new_alerts = [alert_payload(r) for r in conn.execute(
            f"SELECT * FROM alerts WHERE id IN ({','.join('?' * len(alert_ids))}) ORDER BY id DESC", alert_ids)]

    if detections:
        await hub.broadcast({"type": "detections", "camera": camera, "alerts": new_alerts})

    return {"width": image.width, "height": image.height, "detections": detections, "incident_id": incident_id}


@app.get("/incidents")
def incidents(limit: int = 50, user=Depends(auth.require("view_reports"))):
    return reports.list_incidents(limit)


@app.get("/incidents/{incident_id}/report.pdf")
def incident_report(incident_id: int, lang: str = "ar", user=Depends(auth.require("view_reports"))):
    pdf = reports.build_pdf(incident_id, lang)
    if pdf is None:
        raise HTTPException(status_code=404, detail="No such incident")
    filename = f"safesight-incident-{incident_id}-{lang}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


@app.get("/bi-report")
def bi_report(user=Depends(auth.require("view_reports"))):
    if not BI_REPORT.exists():
        raise HTTPException(status_code=404, detail=f"Export the Power BI report to {BI_REPORT.name} first")
    return Response(BI_REPORT.read_bytes(), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{BI_REPORT.name}"'})


@app.get("/alerts")
def alerts(limit: int = 20, user=Depends(auth.require("view_alerts"))):
    with db() as conn:
        rows = conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [alert_payload(r) for r in rows]


@app.get("/alerts/{alert_id}/frame.jpg")
def alert_frame(alert_id: int, user=Depends(auth.require("view_alerts"))):
    """The camera frame of the alert with the boxes drawn (the incident snapshot saved by /detect)."""
    with db() as conn:
        row = conn.execute("SELECT i.snapshot FROM alerts a JOIN incidents i ON i.id = a.incident_id "
                           "WHERE a.id = ?", (alert_id,)).fetchone()
    path = reports.snapshot_dir / row["snapshot"] if row else None
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="No frame for this alert")
    return Response(path.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@app.websocket("/ws/alert")
async def ws_alert(ws: WebSocket):
    """Live alerts. The browser cannot send an Authorization header on a WebSocket, so the first
    message must be {"token": "..."}; the token is not put in the URL so it never lands in logs.
    Close codes: 4401 not signed in / session expired, 4403 role has no view_alerts."""
    await ws.accept()
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=10)
        user = auth.user_for_token(str(first.get("token", "")))
    except (asyncio.TimeoutError, HTTPException, ValueError, AttributeError, WebSocketDisconnect):
        await ws.close(code=4401)
        return
    if "view_alerts" not in ROLE_PERMISSIONS.get(user["role"], []):
        await ws.close(code=4403)
        return
    await ws.send_json({"type": "ready"})
    hub.clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)


@app.get("/stats")
def stats(user=Depends(auth.require("view_stats"))):
    today = datetime.now().date().isoformat()
    with db() as conn:
        cameras = conn.execute("SELECT COUNT(*) FROM cameras WHERE active = 1").fetchone()[0]
        counts = dict(conn.execute(
            "SELECT label, SUM(count) FROM daily_stats WHERE day = ? GROUP BY label", (today,)
        ).fetchall())

    violations = sum(n for label, n in counts.items() if label in SEVERITY)
    worn = sum(counts.get(ok, 0) for ok, _ in PPE_PAIRS)
    missing = sum(counts.get(bad, 0) for _, bad in PPE_PAIRS)
    compliance = round(100 * worn / (worn + missing)) if worn + missing else 100
    return {"cameras": cameras, "violationsToday": violations, "compliance": compliance}


@app.get("/analytics")
def analytics(days: int = 7, user=Depends(auth.require("view_stats"))):
    days = max(1, min(days, 90))
    now = datetime.now()
    today = now.date()
    start = (today - timedelta(days=days - 1)).isoformat()
    with db() as conn:
        hourly = dict(conn.execute(
            "SELECT CAST(substr(created_at, 12, 2) AS INTEGER), COUNT(*) FROM detections "
            "WHERE severity IS NOT NULL AND created_at >= ? GROUP BY 1", (today.isoformat(),)).fetchall())
        daily_rows = conn.execute(
            "SELECT day, label, SUM(count) FROM daily_stats WHERE day >= ? GROUP BY day, label", (start,)).fetchall()
        by_type = dict(conn.execute(
            "SELECT label, COUNT(*) FROM detections WHERE severity IS NOT NULL AND created_at >= ? GROUP BY label",
            (start,)).fetchall())

    per_day: dict[str, dict[str, int]] = {}
    for d, label, n in daily_rows:
        per_day.setdefault(d, {})[label] = n
    day_list = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    violations_by_day, compliance_by_day = [], []
    for d in day_list:
        counts = per_day.get(d, {})
        violations_by_day.append(sum(n for label, n in counts.items() if label in SEVERITY))
        worn = sum(counts.get(ok, 0) for ok, _ in PPE_PAIRS)
        missing = sum(counts.get(bad, 0) for _, bad in PPE_PAIRS)
        compliance_by_day.append(round(100 * worn / (worn + missing), 1) if worn + missing else None)

    return {
        "hours": list(range(24)),
        "violationsByHour": [hourly.get(h, 0) for h in range(24)],
        "days": day_list,
        "violationsByDay": violations_by_day,
        "complianceByDay": compliance_by_day,
        "violationsByType": {label: by_type.get(label, 0) for label in SEVERITY},
    }
