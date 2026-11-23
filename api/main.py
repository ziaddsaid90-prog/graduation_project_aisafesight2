from __future__ import annotations

import io
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from ultralytics import YOLO

from api.auth import Auth, user_payload
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
        """)


init_db()
auth = Auth(db, SEED_FILE)
reports = Reports(db, Path(os.environ.get("SAFESIGHT_SNAPSHOTS", ROOT / "api" / "snapshots")))
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

    with db() as conn:
        conn.executemany(
            "INSERT INTO detections (created_at, camera, label, confidence, severity) VALUES (?, ?, ?, ?, ?)",
            [(now, camera, d["label"], d["confidence"], d["severity"]) for d in detections],
        )

    incident_id = reports.record_incident(image, detections, camera, WEIGHTS.name, when)

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
        rows = conn.execute(
            "SELECT created_at, camera, label, severity FROM detections "
            "WHERE severity IS NOT NULL ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [{"time": r["created_at"][11:16], "date": r["created_at"][:10], "camera": r["camera"],
             "violation": r["label"], "level": r["severity"]} for r in rows]


@app.get("/stats")
def stats(user=Depends(auth.require("view_stats"))):
    today = datetime.now().date().isoformat()
    with db() as conn:
        violations = conn.execute(
            "SELECT COUNT(*) FROM detections WHERE severity IS NOT NULL AND created_at >= ?", (today,)
        ).fetchone()[0]
        counts = dict(conn.execute(
            "SELECT label, COUNT(*) FROM detections WHERE created_at >= ? GROUP BY label", (today,)
        ).fetchall())

    worn = sum(counts.get(ok, 0) for ok, _ in PPE_PAIRS)
    missing = sum(counts.get(bad, 0) for _, bad in PPE_PAIRS)
    compliance = round(100 * worn / (worn + missing)) if worn + missing else 100
    return {"cameras": CAMERAS, "violationsToday": violations, "compliance": compliance}


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
            "SELECT substr(created_at, 1, 10) AS d, label, COUNT(*) FROM detections "
            "WHERE created_at >= ? GROUP BY d, label", (start,)).fetchall()
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
