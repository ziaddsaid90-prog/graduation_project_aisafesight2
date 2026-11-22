"""
Incident reports: one incident per checked image that contains at least one violation.

- record_incident()  is called by /detect right after the model runs. It stores the incident and
  a snapshot of the image with the boxes drawn on it (api/snapshots/<id>.jpg).
- build_pdf()  makes the PDF on request, in Arabic or English, from the templates below.
  Nothing is machine-translated: sentences are fixed templates per language, and only the
  values (numbers, dates, violation types, camera) change.
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable

from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  TEXT    NOT NULL,
    camera      INTEGER NOT NULL,
    severity    TEXT    NOT NULL,          -- highest severity in the image
    violations  INTEGER NOT NULL,
    persons     INTEGER NOT NULL,
    weights     TEXT    NOT NULL,          -- model file that produced it
    snapshot    TEXT    NOT NULL           -- file name inside api/snapshots/
);
CREATE TABLE IF NOT EXISTS incident_items (
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    label       TEXT    NOT NULL,
    severity    TEXT    NOT NULL,
    confidence  REAL    NOT NULL
);
"""

SEVERITY_RANK = {"high": 1, "medium": 2}

# ---------- texts (one template per language) ----------
TEXT = {
    "ar": {
        "title": "تقرير مخالفة سلامة",
        "report_no": "رقم التقرير",
        "date": "التاريخ",
        "time": "الوقت",
        "camera": "الكاميرا",
        "severity": "الخطورة",
        "summary": "تم رصد {count} مخالفة في الكاميرا {camera} يوم {date} الساعة {time}.",
        "persons": "عدد الأشخاص في الصورة: {persons}",
        "details": "تفاصيل المخالفات",
        "col_type": "نوع المخالفة",
        "col_count": "العدد",
        "col_severity": "الخطورة",
        "col_conf": "أعلى ثقة",
        "snapshot": "صورة من الكاميرا وقت المخالفة",
        "actions": "الإجراءات المطلوبة",
        "footer": "تم إنشاء هذا التقرير تلقائيًا بواسطة نظام AI SafeSight. النموذج المستخدم: {weights}",
        "high": "عالية", "medium": "متوسطة",
        "no_helmet": "عدم ارتداء الخوذة", "no_vest": "عدم ارتداء السترة العاكسة",
        "chain_open": "سلسلة الأمان مفتوحة",
        "action_no_helmet": "إيقاف العامل عن العمل فورًا حتى يرتدي خوذة الأمان.",
        "action_no_vest": "توجيه العامل لارتداء السترة العاكسة قبل الاستمرار في العمل.",
        "action_chain_open": "إغلاق سلسلة الأمان فورًا ومنع الدخول للمنطقة حتى تأمينها.",
        "days": ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"],
        "months": ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس",
                   "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"],
        "am": "ص", "pm": "م",
    },
    "en": {
        "title": "Safety Violation Report",
        "report_no": "Report No.",
        "date": "Date",
        "time": "Time",
        "camera": "Camera",
        "severity": "Severity",
        "summary": "{count} violation(s) were detected on camera {camera} on {date} at {time}.",
        "persons": "People in the image: {persons}",
        "details": "Violation details",
        "col_type": "Violation",
        "col_count": "Count",
        "col_severity": "Severity",
        "col_conf": "Top confidence",
        "snapshot": "Camera snapshot at the time of the violation",
        "actions": "Required actions",
        "footer": "This report was generated automatically by AI SafeSight. Model: {weights}",
        "high": "High", "medium": "Medium",
        "no_helmet": "No safety helmet", "no_vest": "No high-visibility vest",
        "chain_open": "Safety chain left open",
        "action_no_helmet": "Stop the worker immediately until a safety helmet is worn.",
        "action_no_vest": "Have the worker put on a high-visibility vest before continuing.",
        "action_chain_open": "Close the safety chain now and keep the area closed until it is secured.",
        "days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "months": ["January", "February", "March", "April", "May", "June", "July", "August",
                   "September", "October", "November", "December"],
        "am": "AM", "pm": "PM",
    },
}

NAVY, ORANGE, RED, AMBER, MUTED, BORDER = (15, 23, 42), (245, 158, 11), (220, 38, 38), (217, 119, 6), (100, 116, 139), (226, 232, 240)
BOX_COLORS = {"violation": (220, 38, 38), "ok": (22, 163, 74), "other": (245, 158, 11)}
OK_CLASSES = {"helmet", "vest", "chain_closed"}

FONT_DIR = Path(os.environ.get("SAFESIGHT_FONT_DIR", r"C:\Windows\Fonts"))
FONT_REGULAR = os.environ.get("SAFESIGHT_FONT", "arial.ttf")       # must contain Arabic letters
FONT_BOLD = os.environ.get("SAFESIGHT_FONT_BOLD", "arialbd.ttf")


def format_date(dt: datetime, lang: str) -> str:
    t = TEXT[lang]
    day, month = t["days"][dt.weekday()], t["months"][dt.month - 1]
    return f"{day} {dt.day} {month} {dt.year}" if lang == "ar" else f"{day}, {month} {dt.day}, {dt.year}"


def format_time(dt: datetime, lang: str) -> str:
    t = TEXT[lang]
    hour = dt.hour % 12 or 12
    return f"{hour}:{dt.minute:02d} {t['am'] if dt.hour < 12 else t['pm']}"


class Reports:
    def __init__(self, connect: Callable[[], sqlite3.Connection], snapshot_dir: Path, ok_classes=OK_CLASSES):
        self.connect = connect
        self.snapshot_dir = snapshot_dir
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        self.ok_classes = ok_classes
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    # ---------- saving ----------
    def record_incident(self, image: Image.Image, detections: list[dict], camera: int,
                        weights: str, when: datetime) -> int | None:
        """Store an incident if the image has violations. Returns its id, or None."""
        violations = [d for d in detections if d.get("severity")]
        if not violations:
            return None
        severity = min((d["severity"] for d in violations), key=lambda s: SEVERITY_RANK.get(s, 9))
        persons = sum(1 for d in detections if d["label"] == "person")

        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO incidents (created_at, camera, severity, violations, persons, weights, snapshot) "
                "VALUES (?, ?, ?, ?, ?, ?, '')",
                (when.isoformat(timespec="seconds"), camera, severity, len(violations), persons, weights),
            )
            incident_id = cur.lastrowid
            snapshot = f"{incident_id}.jpg"
            conn.execute("UPDATE incidents SET snapshot = ? WHERE id = ?", (snapshot, incident_id))
            conn.executemany(
                "INSERT INTO incident_items (incident_id, label, severity, confidence) VALUES (?, ?, ?, ?)",
                [(incident_id, d["label"], d["severity"], d["confidence"]) for d in violations],
            )
        self._save_snapshot(image, detections, self.snapshot_dir / snapshot)
        return incident_id

    def _save_snapshot(self, image: Image.Image, detections: list[dict], path: Path) -> None:
        img = image.convert("RGB").copy()
        img.thumbnail((1280, 1280))
        scale = img.width / image.width
        draw = ImageDraw.Draw(img)
        width = max(2, img.width // 300)
        try:
            font = ImageFont.truetype(str(FONT_DIR / FONT_BOLD), max(14, img.width // 50))
        except OSError:
            font = ImageFont.load_default()
        for d in detections:
            x1, y1, x2, y2 = [v * scale for v in d["box"]]
            kind = "violation" if d.get("severity") else "ok" if d["label"] in self.ok_classes else "other"
            color = BOX_COLORS[kind]
            draw.rectangle([x1, y1, x2, y2], outline=color, width=width)
            label = f"{d['label']} {round(d['confidence'] * 100)}%"
            tw, th = draw.textbbox((0, 0), label, font=font)[2:]
            ty = y1 - th - 6 if y1 - th - 6 >= 0 else y1
            draw.rectangle([x1, ty, x1 + tw + 8, ty + th + 6], fill=color)
            draw.text((x1 + 4, ty + 2), label, fill="white", font=font)
        img.save(path, quality=88)

    # ---------- reading ----------
    def list_incidents(self, limit: int = 50) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM incidents ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            items = conn.execute(
                "SELECT incident_id, label, COUNT(*) AS n FROM incident_items "
                "WHERE incident_id IN (SELECT id FROM incidents ORDER BY id DESC LIMIT ?) "
                "GROUP BY incident_id, label", (limit,)
            ).fetchall()
        by_incident: dict[int, dict] = {}
        for it in items:
            by_incident.setdefault(it["incident_id"], {})[it["label"]] = it["n"]
        return [{"id": r["id"], "date": r["created_at"][:10], "time": r["created_at"][11:16],
                 "camera": r["camera"], "severity": r["severity"], "violations": r["violations"],
                 "types": by_incident.get(r["id"], {})} for r in rows]

    def _load(self, incident_id: int):
        with self.connect() as conn:
            inc = conn.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,)).fetchone()
            items = conn.execute(
                "SELECT label, severity, COUNT(*) AS n, MAX(confidence) AS conf FROM incident_items "
                "WHERE incident_id = ? GROUP BY label, severity", (incident_id,)
            ).fetchall()
        return inc, items

    # ---------- PDF ----------
    def build_pdf(self, incident_id: int, lang: str) -> bytes | None:
        inc, items = self._load(incident_id)
        if inc is None:
            return None
        lang = lang if lang in TEXT else "ar"
        t = TEXT[lang]
        rtl = lang == "ar"
        align = "R" if rtl else "L"
        when = datetime.fromisoformat(inc["created_at"])
        items = sorted(items, key=lambda r: SEVERITY_RANK.get(r["severity"], 9))

        pdf = FPDF(format="A4")
        pdf.set_margins(15, 15, 15)
        pdf.set_auto_page_break(True, margin=18)
        pdf.add_font("main", "", str(FONT_DIR / FONT_REGULAR))
        pdf.add_font("main", "B", str(FONT_DIR / FONT_BOLD))
        pdf.set_text_shaping(True)  # direction comes from the text itself (Unicode bidi), so Arabic runs right to left
        pdf.add_page()
        w = pdf.epw

        # header band
        pdf.set_fill_color(*NAVY)
        pdf.rect(0, 0, 210, 30, "F")
        pdf.set_fill_color(*ORANGE)
        pdf.rect(0, 30, 210, 1.5, "F")
        pdf.set_xy(15, 9)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("main", "B", 18)
        pdf.cell(w, 12, t["title"], align=align)
        pdf.set_xy(15, 9)
        pdf.set_font("main", "B", 13)
        pdf.set_text_color(*ORANGE)
        pdf.cell(w, 12, "AI SafeSight", align="L" if rtl else "R")
        pdf.set_y(38)

        # info grid: 4 boxes
        sev_color = RED if inc["severity"] == "high" else AMBER
        info = [(t["report_no"], f"#{inc['id']}", NAVY), (t["date"], format_date(when, lang), NAVY),
                (t["time"], format_time(when, lang), NAVY), (t["camera"], str(inc["camera"]), NAVY),
                (t["severity"], t[inc["severity"]], sev_color)]
        if rtl:
            info = info[::-1]
        box_w = w / len(info)
        y = pdf.get_y()
        for i, (label, value, color) in enumerate(info):
            x = 15 + i * box_w
            pdf.set_draw_color(*BORDER)
            pdf.rect(x + 1, y, box_w - 2, 18)
            pdf.set_xy(x + 1, y + 2)
            pdf.set_font("main", "", 8)
            pdf.set_text_color(*MUTED)
            pdf.cell(box_w - 2, 5, label, align="C")
            pdf.set_xy(x + 1, y + 8)
            pdf.set_font("main", "B", 10 if len(value) < 18 else 8)
            pdf.set_text_color(*color)
            pdf.cell(box_w - 2, 7, value, align="C")
        pdf.set_y(y + 24)

        # summary sentence
        pdf.set_text_color(*NAVY)
        pdf.set_font("main", "", 11)
        pdf.multi_cell(w, 7, t["summary"].format(count=inc["violations"], camera=inc["camera"],
                                                date=format_date(when, lang), time=format_time(when, lang)),
                       align=align, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("main", "", 10)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(w, 6, t["persons"].format(persons=inc["persons"]), align=align, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        # details table
        self._heading(pdf, t["details"], align)
        cols = [(t["col_type"], 0.46), (t["col_count"], 0.14), (t["col_severity"], 0.2), (t["col_conf"], 0.2)]
        rows = [[t.get(r["label"], r["label"]), str(r["n"]), t.get(r["severity"], r["severity"]),
                 f"{round(r['conf'] * 100)}%"] for r in items]
        if rtl:
            cols, rows = cols[::-1], [r[::-1] for r in rows]
        pdf.set_fill_color(241, 245, 249)
        pdf.set_font("main", "B", 9)
        pdf.set_text_color(*NAVY)
        for title, frac in cols:
            pdf.cell(w * frac, 8, title, border=1, align="C", fill=True)
        pdf.ln()
        pdf.set_font("main", "", 10)
        for row in rows:
            for (title, frac), value in zip(cols, row):
                pdf.cell(w * frac, 8, value, border=1, align="C")
            pdf.ln()
        pdf.ln(5)

        # snapshot
        snap = self.snapshot_dir / inc["snapshot"]
        if snap.exists():
            self._heading(pdf, t["snapshot"], align)
            with Image.open(snap) as im:
                ratio = im.height / im.width
            img_w = w
            img_h = img_w * ratio
            max_h = 95
            if img_h > max_h:
                img_h, img_w = max_h, max_h / ratio
            if pdf.get_y() + img_h > pdf.h - 40:
                pdf.add_page()
            pdf.image(str(snap), x=15 + (w - img_w) / 2, w=img_w, h=img_h)
            pdf.ln(5)

        # required actions
        self._heading(pdf, t["actions"], align)
        pdf.set_font("main", "", 10)
        pdf.set_text_color(*NAVY)
        for r in items:
            key = f"action_{r['label']}"
            if key in t:
                if rtl:
                    # the bidi engine would put a leading bullet on the left, so draw it ourselves on the right
                    y = pdf.get_y()
                    pdf.set_xy(15, y)
                    pdf.multi_cell(w - 6, 6.5, t[key], align="R", new_x="LMARGIN", new_y="NEXT")
                    after = pdf.get_y()
                    pdf.set_xy(15 + w - 5, y)
                    pdf.cell(5, 6.5, "•", align="R")
                    pdf.set_xy(15, after)
                else:
                    pdf.multi_cell(w, 6.5, "• " + t[key], align=align, new_x="LMARGIN", new_y="NEXT")

        # footer (turn off page breaks first, otherwise writing near the bottom opens a new page)
        pdf.set_auto_page_break(False)
        pdf.set_y(-20)
        pdf.set_draw_color(*BORDER)
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())
        pdf.set_font("main", "", 8)
        pdf.set_text_color(*MUTED)
        pdf.multi_cell(w, 5, t["footer"].format(weights=inc["weights"]), align="C", new_x="LMARGIN", new_y="NEXT")
        return bytes(pdf.output())

    @staticmethod
    def _heading(pdf: FPDF, text: str, align: str) -> None:
        pdf.set_font("main", "B", 12)
        pdf.set_text_color(*NAVY)
        pdf.cell(pdf.epw, 8, text, align=align, new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*ORANGE)
        pdf.set_line_width(0.6)
        pdf.line(15, pdf.get_y(), 195, pdf.get_y())
        pdf.set_line_width(0.2)
        pdf.ln(3)
