from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi import (APIRouter, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, Response,
                     UploadFile, WebSocket, WebSocketDisconnect)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field

from api import live
from api.auth import ROLE_PERMISSIONS, Auth, user_payload
from api.reports import Reports
from api.translator import Translator

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("SAFESIGHT_DB", ROOT / "api" / "safesight.db"))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
SEED_FILE = ROOT / "api" / "seed_users.json"
if os.environ.get("SAFESIGHT_SEED_USERS"):
    SEED_FILE = DB_PATH.parent / "seed_users.json"
    SEED_FILE.write_text(os.environ["SAFESIGHT_SEED_USERS"], encoding="utf-8")
elif not SEED_FILE.exists():
    SEED_FILE = ROOT / "api" / "seed_users.example.json"
SERVE_FRONTEND = os.environ.get("SAFESIGHT_SERVE_FRONTEND", "0") == "1"
CAMERAS = int(os.environ.get("SAFESIGHT_CAMERAS", 1))
FRONTEND_URL = os.environ.get("SAFESIGHT_FRONTEND_URL", "http://127.0.0.1:5500/Frontend")
BI_REPORT = Path(os.environ.get("SAFESIGHT_BI_REPORT", ROOT / "powerbi" / "AI_SafeSight_CHV.pdf"))
INGEST_KEY = os.environ.get("SAFESIGHT_INGEST_KEY", "")
CONF_THRESHOLD = float(os.environ.get("SAFESIGHT_CONF", 0.4))
CAMERA_ONLINE_MINUTES = 10
PERSON_LABELS = {"person"}
HEAD_LABELS = {"helmet", "no_helmet", "blue_helmet", "red_helmet", "white_helmet", "yellow_helmet"}


def find_weights() -> Path:
    if os.environ.get("SAFESIGHT_WEIGHTS"):
        return Path(os.environ["SAFESIGHT_WEIGHTS"])
    trained = sorted((ROOT / "runs").glob("**/weights/best.pt"), key=lambda p: p.stat().st_mtime)
    if trained:
        return trained[-1]
    return ROOT / "yolo11s.pt"


WEIGHTS = model = None
IS_PPE_MODEL = False
if os.environ.get("SAFESIGHT_DETECT", "1") != "0":
    from ultralytics import YOLO
    WEIGHTS = find_weights()
    model = YOLO(str(WEIGHTS))
    IS_PPE_MODEL = any(name in live.SEVERITY for name in model.names.values())
if model is not None and not IS_PPE_MODEL:
    print(f"WARNING: {WEIGHTS.name} has no violation classes. /api/detect works but will not report violations; "
          "live violations come from the pipeline through /api/ingest/events.")


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


SNAPSHOT_DIR = Path(os.environ.get("SAFESIGHT_SNAPSHOTS", ROOT / "api" / "snapshots"))


def init_db() -> Reports:
    with db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS detections (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT    NOT NULL,
                camera     TEXT    NOT NULL,
                label      TEXT    NOT NULL,
                confidence REAL    NOT NULL,
                severity   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_detections_created ON detections(created_at);
        """)
    created = Reports(db, SNAPSHOT_DIR)
    with db() as conn:
        live.init_live(conn, CAMERAS)
    return created


reports = init_db()
(SNAPSHOT_DIR / "events").mkdir(parents=True, exist_ok=True)
auth = Auth(db, SEED_FILE)
USE_TRANSLATION_MODEL = os.environ.get("SAFESIGHT_TRANSLATE", "1") != "0"
translator = Translator(db, ROOT / "api" / "translation_fixes.json", use_model=USE_TRANSLATION_MODEL)
if USE_TRANSLATION_MODEL:
    translator.preload()
hub = live.AlertHub()

app = FastAPI(title="AI SafeSight API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
api = APIRouter(prefix="/api")


class TranslateBody(BaseModel):
    texts: list[str]
    target: str = "ar"
    source: str = "en"


@api.post("/translate")
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


@api.post("/auth/login")
def login(body: LoginBody):
    return auth.login(body.email, body.password)


@api.post("/auth/logout")
def logout(authorization: str = Header(default="")):
    token = authorization.partition(" ")[2]
    if token:
        auth.logout(token)
    return {"ok": True}


@api.get("/auth/me")
def me(user=Depends(auth.current_user())):
    return user_payload(user)


@api.post("/auth/forgot-password")
def forgot_password(body: ForgotBody):
    token = auth.create_reset_token(body.email)
    if token:
        print(f"[password reset] {body.email}: {FRONTEND_URL}/reset-password.html?token={token}")
    return {"ok": True}


@api.post("/auth/reset-password")
def reset_password(body: ResetBody):
    auth.reset_password(body.token, body.password)
    return {"ok": True}


@api.get("/users")
def users(user=Depends(auth.require("view_users"))):
    return auth.list_users()


@api.get("/health")
def health():
    return {"status": "ok", "weights": WEIGHTS.name if WEIGHTS else None, "ppe_model": IS_PPE_MODEL,
            "classes": list(model.names.values()) if model else []}


def require_ingest(request: Request, x_api_key: str = Header(default="")) -> None:
    if INGEST_KEY:
        if x_api_key != INGEST_KEY:
            raise HTTPException(status_code=401, detail="Wrong or missing X-API-Key")
    elif request.client is None or request.client.host not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(status_code=403, detail="Set SAFESIGHT_INGEST_KEY to accept events from other computers")


class IngestEvent(BaseModel):
    event_id: str | None = None
    camera_id: str
    track_id: int | None = None
    violation: str
    state: Literal["start", "end"] = "start"
    ts: str
    confidence: float | None = None
    bbox: list[float] | None = Field(default=None, min_length=4, max_length=4)
    snapshot_jpeg_base64: str | None = None


def decode_snapshot(data: str) -> Image.Image:
    if "," in data[:100] and data.startswith("data:"):
        data = data.split(",", 1)[1]
    try:
        return Image.open(io.BytesIO(base64.b64decode(data, validate=False))).convert("RGB")
    except (binascii.Error, UnidentifiedImageError, ValueError):
        raise HTTPException(status_code=400, detail="snapshot_jpeg_base64 is not a valid image")


@api.post("/ingest/events", status_code=201, dependencies=[Depends(require_ingest)])
async def ingest_event(body: IngestEvent):
    try:
        ts = live.to_utc(body.ts)
    except ValueError:
        raise HTTPException(status_code=400, detail="ts must be ISO-8601, e.g. 2026-11-23T10:15:02Z")
    cam = live.camera_id(body.camera_id)

    if body.state == "end":
        if not body.event_id:
            raise HTTPException(status_code=400, detail="event_id is required when state is end")
        with db() as conn:
            row = conn.execute("SELECT e.id, e.start_ts, a.id AS alert_id FROM events e JOIN alerts a ON a.event_id = e.id "
                               "WHERE e.id = ?", (body.event_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=404, detail="No event with this event_id")
            conn.execute("UPDATE events SET end_ts = ? WHERE id = ?", (max(ts, row["start_ts"]), row["id"]))
            live.ensure_camera(conn, cam, ts)
        await hub.broadcast({"type": "event_end", "event_id": row["id"], "ts": ts})
        return {"event_id": row["id"], "alert_id": row["alert_id"]}

    if body.violation not in live.SEVERITY:
        raise HTTPException(status_code=400, detail=f"violation must be one of {', '.join(live.CONTRACT_VIOLATIONS)}")
    event_id = body.event_id or live.new_id()
    with db() as conn:
        existing = conn.execute("SELECT a.id FROM alerts a WHERE a.event_id = ?", (event_id,)).fetchone()
    if existing:
        return {"event_id": event_id, "alert_id": existing["id"]}

    snapshot_path = incident_id = None
    if body.snapshot_jpeg_base64:
        image = decode_snapshot(body.snapshot_jpeg_base64)
        snapshot_path = f"events/{event_id}.jpg"
        image.save(SNAPSHOT_DIR / snapshot_path, quality=88)
        det = {"label": body.violation, "confidence": body.confidence or 0.0,
               "box": body.bbox or [0, 0, 0, 0], "severity": live.SEVERITY[body.violation]}
        local_when = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().replace(tzinfo=None)
        incident_id = reports.record_incident(image, [det], cam, "live pipeline", local_when)

    with db() as conn:
        live.ensure_camera(conn, cam, ts)
        live.touch_track(conn, cam, body.track_id, ts)
        _, alert_id = live.create_event(conn, cam=cam, track_id=body.track_id, violation=body.violation, ts=ts,
                                        confidence=body.confidence, bbox=body.bbox, snapshot_path=snapshot_path,
                                        incident_id=incident_id, event_id=event_id)
        live.refresh_daily(conn, live.local_date(ts), cam)
        row = conn.execute(live.ALERT_SELECT + " WHERE a.id = ?", (alert_id,)).fetchone()
    await hub.broadcast(live.ws_violation(row))
    return {"event_id": event_id, "alert_id": alert_id}


class IngestTracks(BaseModel):
    camera_id: str
    ts: str
    track_ids: list[int] = Field(default_factory=list)


@api.post("/ingest/tracks", dependencies=[Depends(require_ingest)])
async def ingest_tracks(body: IngestTracks):
    try:
        ts = live.to_utc(body.ts)
    except ValueError:
        raise HTTPException(status_code=400, detail="ts must be ISO-8601")
    cam = live.camera_id(body.camera_id)
    with db() as conn:
        live.ensure_camera(conn, cam, ts)
        before = conn.execute("SELECT COUNT(*) FROM tracks WHERE camera_id = ?", (cam,)).fetchone()[0]
        for tid in body.track_ids:
            live.touch_track(conn, cam, tid, ts)
        new = conn.execute("SELECT COUNT(*) FROM tracks WHERE camera_id = ?", (cam,)).fetchone()[0] - before
        if new:
            live.refresh_daily(conn, live.local_date(ts), cam)
    if new:
        await hub.broadcast({"type": "stats", "camera_id": cam, "ts": ts})
    return {"ok": True, "new_tracks": new}


@api.post("/detect")
async def detect(file: UploadFile = File(...), camera: str = Form("cam1"), user=Depends(auth.require("check_image"))):
    if model is None:
        raise HTTPException(status_code=503, detail="Image check is turned off on this server")
    try:
        image = Image.open(io.BytesIO(await file.read())).convert("RGB")
    except UnidentifiedImageError:
        raise HTTPException(status_code=400, detail="The file is not a valid image")

    result = model(image, conf=CONF_THRESHOLD, verbose=False)[0]
    when = datetime.now()
    ts = live.to_utc(when.isoformat(timespec="seconds"))
    cam = live.camera_id(camera)

    detections = []
    for box in result.boxes:
        label = model.names[int(box.cls)]
        detections.append({
            "label": label,
            "confidence": round(float(box.conf), 2),
            "box": [round(v) for v in box.xyxy[0].tolist()],
            "severity": live.SEVERITY.get(label),
        })
    violations = [d for d in detections if d["severity"]]
    persons = sum(d["label"] in PERSON_LABELS for d in detections) or sum(d["label"] in HEAD_LABELS for d in detections)

    incident_id = reports.record_incident(image, detections, cam, WEIGHTS.name, when)
    snapshot = None
    if incident_id is not None:
        with db() as conn:
            snapshot = conn.execute("SELECT snapshot FROM incidents WHERE id = ?", (incident_id,)).fetchone()[0]

    with db() as conn:
        live.ensure_camera(conn, cam, ts)
        conn.executemany(
            "INSERT INTO detections (created_at, camera, label, confidence, severity) VALUES (?, ?, ?, ?, ?)",
            [(when.isoformat(timespec="seconds"), cam, d["label"], d["confidence"], d["severity"]) for d in detections])
        for _ in range(max(persons, len(violations))):
            live.touch_track(conn, cam, None, ts)
        alert_ids = []
        for d in violations:
            event_id, alert_id = live.create_event(conn, cam=cam, track_id=None, violation=d["label"], ts=ts,
                                                   confidence=d["confidence"], bbox=d["box"], snapshot_path=snapshot,
                                                   incident_id=incident_id)
            conn.execute("UPDATE events SET end_ts = start_ts WHERE id = ?", (event_id,))
            alert_ids.append(alert_id)
        if detections:
            live.refresh_daily(conn, live.local_date(ts), cam)
        rows = [conn.execute(live.ALERT_SELECT + " WHERE a.id = ?", (a,)).fetchone() for a in alert_ids]

    for row in rows:
        await hub.broadcast(live.ws_violation(row))
    if detections and not rows:
        await hub.broadcast({"type": "stats", "camera_id": cam, "ts": ts})
    return {"width": image.width, "height": image.height, "detections": detections, "incident_id": incident_id}


def time_range(from_: str | None, to: str | None) -> tuple[str, str, str, str]:
    today = datetime.now().date().isoformat()
    try:
        from_day = (from_ or today)[:10]
        to_day = (to or from_ or today)[:10]
        start = live.to_utc(from_) if from_ and len(from_) > 10 else live.local_day_bounds(from_day)[0]
        end = live.to_utc(to) if to and len(to) > 10 else live.local_day_bounds(to_day)[1]
    except ValueError:
        raise HTTPException(status_code=400, detail="from/to must be YYYY-MM-DD or ISO-8601 times")
    return from_day, to_day, start, end


@api.get("/events")
def events(from_: str | None = Query(None, alias="from"), to: str | None = None, camera: str | None = None,
           violation: str | None = None, limit: int = 200, user=Depends(auth.require("view_stats"))):
    _, _, start, end = time_range(from_, to)
    sql = "SELECT * FROM events WHERE start_ts >= ? AND start_ts < ?"
    args: list = [start, end]
    if camera:
        sql += " AND camera_id = ?"
        args.append(live.camera_id(camera))
    if violation:
        sql += " AND violation = ?"
        args.append(violation)
    sql += " ORDER BY start_ts DESC LIMIT ?"
    args.append(max(1, min(limit, 1000)))
    with db() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [{"event_id": r["id"], "camera_id": r["camera_id"], "track_id": r["track_id"], "violation": r["violation"],
             "severity": live.SEVERITY.get(r["violation"], "medium"), "start_ts": r["start_ts"], "end_ts": r["end_ts"],
             "confidence": r["confidence"], "bbox": json.loads(r["bbox"]) if r["bbox"] else None,
             "snapshot_url": f"/api/snapshots/{r['snapshot_path']}" if r["snapshot_path"] else None} for r in rows]


@api.get("/alerts")
def alerts(acknowledged: bool | None = None, camera: str | None = None, limit: int = 50,
           user=Depends(auth.require("view_alerts"))):
    sql, args = live.ALERT_SELECT + " WHERE 1 = 1", []
    if acknowledged is not None:
        sql += " AND a.acknowledged = ?"
        args.append(int(acknowledged))
    if camera:
        sql += " AND e.camera_id = ?"
        args.append(live.camera_id(camera))
    sql += " ORDER BY e.start_ts DESC LIMIT ?"
    args.append(max(1, min(limit, 500)))
    with db() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [live.alert_payload(r) for r in rows]


@api.post("/alerts/{alert_id}/ack")
async def ack_alert(alert_id: str, user=Depends(auth.require("view_alerts"))):
    with db() as conn:
        found = conn.execute("SELECT acknowledged FROM alerts WHERE id = ?", (alert_id,)).fetchone()
        if found is None:
            raise HTTPException(status_code=404, detail="No such alert")
        if not found["acknowledged"]:
            conn.execute("UPDATE alerts SET acknowledged = 1, ack_ts = ?, ack_by = ? WHERE id = ?",
                         (live.utc_now(), user["email"], alert_id))
        row = conn.execute(live.ALERT_SELECT + " WHERE a.id = ?", (alert_id,)).fetchone()
    await hub.broadcast({"type": "ack", "alert_id": alert_id})
    return live.alert_payload(row)


@api.get("/statistics")
def statistics(from_: str | None = Query(None, alias="from"), to: str | None = None, camera: str | None = None,
               user=Depends(auth.require("view_stats"))):
    from_day, to_day, start, end = time_range(from_, to)
    cam_sql, cam_args = ("", []) if not camera else (" AND camera_id = ?", [live.camera_id(camera)])
    with db() as conn:
        rows = conn.execute(f"SELECT * FROM daily_stats WHERE date >= ? AND date <= ?{cam_sql}",
                            (from_day, to_day, *cam_args)).fetchall()
        by_violation = dict(conn.execute(
            f"SELECT violation, COUNT(*) FROM events WHERE start_ts >= ? AND start_ts < ?{cam_sql} GROUP BY violation",
            (start, end, *cam_args)).fetchall())
        active = conn.execute(
            f"SELECT COUNT(*) FROM alerts a JOIN events e ON e.id = a.event_id WHERE a.acknowledged = 0"
            f"{cam_sql.replace('camera_id', 'e.camera_id')}", cam_args).fetchone()[0]
        alerts_sent = conn.execute(
            f"SELECT COUNT(*) FROM alerts a JOIN events e ON e.id = a.event_id WHERE a.sent_ts >= ? AND a.sent_ts < ?"
            f"{cam_sql.replace('camera_id', 'e.camera_id')}", (start, end, *cam_args)).fetchone()[0]
    out = {"from": from_day, "to": to_day, "camera": live.camera_id(camera) if camera else None}
    out.update(live.combine(rows))
    out["violations"] = sum(by_violation.values())
    out["by_violation"] = {k: by_violation.get(k, 0) for k in live.CONTRACT_VIOLATIONS}
    out["by_violation"].update({k: n for k, n in by_violation.items() if k not in live.CONTRACT_VIOLATIONS})
    out["active_alerts"] = active
    out["alerts_sent"] = alerts_sent
    return out


@api.get("/cameras")
def cameras(user=Depends(auth.require("view_stats"))):
    online_since = live.to_utc((datetime.now() - timedelta(minutes=CAMERA_ONLINE_MINUTES)).isoformat(timespec="seconds"))
    with db() as conn:
        rows = conn.execute("""
            SELECT c.*, (SELECT snapshot_path FROM events e WHERE e.camera_id = c.id AND e.snapshot_path IS NOT NULL
                         ORDER BY start_ts DESC LIMIT 1) AS last_snapshot
            FROM cameras c ORDER BY length(c.id), c.id""").fetchall()
    return [{"id": r["id"], "name": r["name"], "location": r["location"], "stream_url": r["stream_url"],
             "active": bool(r["active"]), "last_seen": r["last_seen"],
             "online": bool(r["active"] and r["last_seen"] and r["last_seen"] >= online_since),
             "last_snapshot_url": f"/api/snapshots/{r['last_snapshot']}" if r["last_snapshot"] else None} for r in rows]


@api.get("/snapshots/{file:path}")
def snapshot(file: str, user=Depends(auth.require("view_alerts"))):
    path = (SNAPSHOT_DIR / file).resolve()
    if SNAPSHOT_DIR.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="No such snapshot")
    return Response(path.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@api.get("/analytics")
def analytics(days: int = 7, user=Depends(auth.require("view_stats"))):
    days = max(1, min(days, 90))
    today = datetime.now().date()
    day_list = [(today - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]
    range_start = live.local_day_bounds(day_list[0])[0]
    today_start, today_end = live.local_day_bounds(today.isoformat())
    with db() as conn:
        hourly = dict(conn.execute(
            "SELECT CAST(strftime('%H', start_ts, 'localtime') AS INTEGER), COUNT(*) FROM events "
            "WHERE start_ts >= ? AND start_ts < ? GROUP BY 1", (today_start, today_end)).fetchall())
        rows = conn.execute("SELECT * FROM daily_stats WHERE date >= ?", (day_list[0],)).fetchall()
        by_type = dict(conn.execute("SELECT violation, COUNT(*) FROM events WHERE start_ts >= ? GROUP BY violation",
                                    (range_start,)).fetchall())
    per_day: dict[str, list] = {}
    for r in rows:
        per_day.setdefault(r["date"], []).append(r)
    totals = [live.combine(per_day.get(d, [])) for d in day_list]
    types = {k: by_type.get(k, 0) for k in live.CONTRACT_VIOLATIONS}
    types.update({k: n for k, n in by_type.items() if k not in live.CONTRACT_VIOLATIONS})
    return {
        "hours": list(range(24)),
        "violationsByHour": [hourly.get(h, 0) for h in range(24)],
        "days": day_list,
        "violationsByDay": [t["violations"] for t in totals],
        "complianceByDay": [round(100 * t["safety_index"], 1) if t["safety_index"] is not None else None for t in totals],
        "violationsByType": types,
    }


@api.get("/incidents")
def incidents(limit: int = 50, user=Depends(auth.require("view_reports"))):
    return reports.list_incidents(limit)


@api.get("/incidents/{incident_id}/report.pdf")
def incident_report(incident_id: int, lang: str = "ar", user=Depends(auth.require("view_reports"))):
    pdf = reports.build_pdf(incident_id, lang)
    if pdf is None:
        raise HTTPException(status_code=404, detail="No such incident")
    filename = f"safesight-incident-{incident_id}-{lang}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{filename}"'})


@api.get("/bi-report")
def bi_report(user=Depends(auth.require("view_reports"))):
    if not BI_REPORT.exists():
        raise HTTPException(status_code=404, detail=f"Export the Power BI report to {BI_REPORT.name} first")
    return Response(BI_REPORT.read_bytes(), media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{BI_REPORT.name}"'})


app.include_router(api)


@app.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket):
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


if SERVE_FRONTEND:
    app.mount("/", StaticFiles(directory=ROOT / "Frontend", html=True), name="frontend")
