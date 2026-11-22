"""
AI SafeSight API - bridges the Frontend and the YOLO model.

    POST /auth/login             email + password -> token + user (with permissions)
    POST /auth/logout            ends the session
    GET  /auth/me                who is signed in
    POST /auth/forgot-password   prints a reset link in the server console (no email server yet)
    POST /auth/reset-password    token + new password
    POST /detect   [check_image] upload an image -> YOLO -> violations saved -> detections returned
    GET  /alerts   [view_alerts] latest violations (for the alerts table)
    GET  /stats    [view_stats]  numbers for the dashboard cards
    GET  /users    [view_users]  list of accounts
    GET  /incidents                      [view_reports] one row per image that had violations
    GET  /incidents/<id>/report.pdf?lang=ar|en  [view_reports] the incident report as PDF
    GET  /bi-report                      [view_reports] the Power BI report exported as PDF
    GET  /health                 which model is loaded (no login needed)

[permission] = the role must have it, see ROLE_PERMISSIONS in api/auth.py.

Run (from the repo root, with .venv active):
    uvicorn api.main:app --reload
Docs / manual testing: http://127.0.0.1:8000/docs
"""
from __future__ import annotations

import io
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from ultralytics import YOLO

from api.auth import Auth, user_payload
from api.reports import Reports

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(os.environ.get("SAFESIGHT_DB", ROOT / "api" / "safesight.db"))
# Accounts created on the very first start. seed_users.json (not committed) wins over the example.
SEED_FILE = ROOT / "api" / "seed_users.json"
if not SEED_FILE.exists():
    SEED_FILE = ROOT / "api" / "seed_users.example.json"
# Cameras installed on site (the dashboard card). Only one for now.
CAMERAS = int(os.environ.get("SAFESIGHT_CAMERAS", 1))
# Where the Frontend is served, used to build the password-reset link
FRONTEND_URL = os.environ.get("SAFESIGHT_FRONTEND_URL", "http://127.0.0.1:5500/Frontend")
# Power BI report exported as PDF (File > Export > Export to PDF), shown in the dashboard
BI_REPORT = Path(os.environ.get("SAFESIGHT_BI_REPORT", ROOT / "powerbi" / "AI_SafeSight_CHV.pdf"))

# Class names come from prepared/titan_v1/data.yaml. Only these count as violations.
SEVERITY = {"no_helmet": "high", "chain_open": "high", "no_vest": "medium"}
# Pairs used for the compliance rate: (wearing it, not wearing it)
PPE_PAIRS = [("helmet", "no_helmet"), ("vest", "no_vest")]
CONF_THRESHOLD = float(os.environ.get("SAFESIGHT_CONF", 0.4))


def find_weights() -> Path:
    """SAFESIGHT_WEIGHTS env var > newest trained best.pt > stock yolo11s.pt."""
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
                created_at TEXT    NOT NULL,   -- local time, ISO format
                camera     INTEGER NOT NULL,
                label      TEXT    NOT NULL,
                confidence REAL    NOT NULL,
                severity   TEXT                -- NULL when it is not a violation
            );
            CREATE INDEX IF NOT EXISTS idx_detections_created ON detections(created_at);
        """)


init_db()
auth = Auth(db, SEED_FILE)
reports = Reports(db, Path(os.environ.get("SAFESIGHT_SNAPSHOTS", ROOT / "api" / "snapshots")))

app = FastAPI(title="AI SafeSight API")
# The Frontend runs on Live Server (another port), so the browser needs CORS to call us.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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
        # No email server yet: the link is printed here so the admin can send it by hand
        print(f"[password reset] {body.email}: {FRONTEND_URL}/reset-password.html?token={token}")
    return {"ok": True}  # same answer whether the email exists or not


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
            "box": [round(v) for v in box.xyxy[0].tolist()],  # x1, y1, x2, y2 in image pixels
            "severity": SEVERITY.get(label),
        })

    with db() as conn:
        conn.executemany(
            "INSERT INTO detections (created_at, camera, label, confidence, severity) VALUES (?, ?, ?, ?, ?)",
            [(now, camera, d["label"], d["confidence"], d["severity"]) for d in detections],
        )

    # Any violation -> an incident with a snapshot; its PDF report is built on request (/incidents/<id>/report.pdf)
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
