import base64, io, json, random, sys, time, urllib.request, uuid
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

API = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ROUNDS = int(sys.argv[2]) if len(sys.argv) > 2 else 12
src = Image.open(str(Path(__file__).resolve().parents[1] / "Frontend" / "sample.jpg")).convert("RGB")


def post(path, body):
    req = urllib.request.Request(API + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req))


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def snapshot(box):
    img = src.copy()
    ImageDraw.Draw(img).rectangle(box, outline=(220, 38, 38), width=6)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


people = {cam: list(range(1, random.randint(3, 6))) for cam in ("cam1", "cam2", "cam3")}
open_events = []
next_id = 100
for r in range(ROUNDS):
    for cam, ids in people.items():
        if random.random() < 0.4:
            next_id += 1
            ids.append(next_id)
        post("/api/ingest/tracks", {"camera_id": cam, "ts": now(), "track_ids": ids})
    if open_events and random.random() < 0.5:
        ev = open_events.pop(0)
        post("/api/ingest/events", {**ev, "state": "end", "ts": now()})
        print("end  ", ev["camera_id"], ev["violation"], flush=True)
    if random.random() < 0.7:
        cam = random.choice(list(people))
        box = [430, 150, 640, 640]
        ev = {"event_id": str(uuid.uuid4()), "camera_id": cam, "track_id": random.choice(people[cam]),
              "violation": random.choices(["no_helmet", "no_vest", "no_helmet_no_vest"], [5, 4, 1])[0],
              "ts": now(), "confidence": round(random.uniform(0.6, 0.95), 2), "bbox": box}
        res = post("/api/ingest/events", {**ev, "state": "start", "snapshot_jpeg_base64": snapshot(box)})
        open_events.append(ev)
        print("start", cam, ev["violation"], res["alert_id"][:8], flush=True)
    time.sleep(5)
