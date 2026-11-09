"""
TITAN AI - dataset preparation tool (Person 1 / data lead).

Never modifies source folders. Everything it writes goes under  <root>/prepared/.

Subcommands
-----------
  remap   Convert Construction_PPE_500 (12 Ultralytics classes) to the TITAN v1
          taxonomy and write it to prepared/ppe_remapped/.
  build   Collect every source, assign groups, make a group-wise train/val split,
          validate labels, and write prepared/titan_v1/ (images, labels, data.yaml,
          manifest.csv, build_report.txt).
  check   Draw boxes on a random sample of a built dataset so a human can review
          the labels (prepared/qa/).

Typical order
-------------
  python tools/prepare_dataset.py remap
  python tools/prepare_dataset.py build            # re-run whenever new labels arrive
  python tools/prepare_dataset.py check --n 40

Where labels for our own (unlabelled) folders go
------------------------------------------------
Annotators export YOLO .txt files (TITAN class IDs, see CLASSES) into
    <root>/annotations/<source name>/<image stem>.txt
e.g. annotations/barwita/105.txt, annotations/framing/frame_00041_t0004000ms.txt

  * An image counts as labelled only if its .txt exists.
  * An EMPTY .txt means "checked, contains none of our classes" (a background image).
  * Images the team decides not to use go in annotations/exclude.txt, one
    "<source>/<image file name>" per line. Do this for skipped images, because
    CVAT/Label Studio exports write an empty .txt for every image, even unlabelled ones.

Requires only: Python 3.9+, Pillow (for `check`).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import random
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent          # D:\TITAN_AI_Dataset
PREPARED = ROOT / "prepared"
ANNOT = ROOT / "annotations"
IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# ---------------------------------------------------------------------------
# TITAN v1 taxonomy. The ORDER is the class ID. Annotation tools must use the
# exact same order. Change only with team agreement, then re-run remap + build.
# ---------------------------------------------------------------------------
CLASSES = [
    "person",         # 0
    "helmet",         # 1
    "no_helmet",      # 2
    "vest",           # 3
    "no_vest",        # 4
    "wheelbarrow",    # 5
    "mixer_truck",    # 6
    "vehicle_other",  # 7
]

# Ultralytics Construction-PPE id -> TITAN id. Ids not listed are dropped
# (gloves, boots, goggles and their no_* versions: not visible from CCTV height).
PPE_TO_TITAN = {
    5: 0,    # Person    -> person
    0: 1,    # helmet    -> helmet
    6: 2,    # no_helmet -> no_helmet
    2: 3,    # vest      -> vest
    11: 4,   # no_vest   -> no_vest
    10: 7,   # forklift  -> vehicle_other
}


# ---------------------------------------------------------------------------
# Sources. Add new folders here (e.g. our own Hikvision recordings, TITAN footage).
#   group_fn(image_path) -> group name. Images in the same group ALWAYS land in
#   the same split (frames of one video, photos of one scene, near-duplicates).
#   step: keep every Nth image (for dense video frames).
#   pin:  force the whole source into one split ("train" / "val"), or None.
# ---------------------------------------------------------------------------
@dataclass
class Source:
    name: str
    images: Path
    labels: Path | None              # None -> labels come from annotations/<name>/
    group_fn: Callable[[Path], str]
    step: int = 1
    pin: str | None = None


def own_group(prefix: str) -> Callable[[Path], str]:
    return lambda p: f"{prefix}:{p.stem}"


def barwita_group(p: Path) -> str:
    n = int(p.stem) if p.stem.isdigit() else -1
    if 100 <= n <= 119:
        return "barwita:street_scene_100_119"   # ~12 phone photos of one location
    if n in (124, 166):
        return "barwita:near_dup_124_166"       # visually identical pair
    return f"barwita:{p.stem}"


SOURCES = [
    Source("ppe", PREPARED / "ppe_remapped" / "images", PREPARED / "ppe_remapped" / "labels",
           own_group("ppe")),
    Source("barwita", ROOT / "barwita", None, barwita_group),
    Source("mixer", ROOT / "Concrete Mixer Truck" / "Concrete Mixer Truck", None, own_group("mixer")),
    # One 15 s clip = one group. Every 5th frame = one frame per ~0.5 s.
    Source("framing", ROOT / "framing" / "original_video_frames", None,
           lambda p: "framing:original_video", step=5),
]


# ---------------------------------------------------------------------------
# Label helpers
# ---------------------------------------------------------------------------
def parse_yolo(path: Path, n_classes: int):
    """Return (rows, problem). rows = [(cls, x, y, w, h)]."""
    rows = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5:
            return [], f"line {i}: expected 5 values, got {len(parts)}"
        try:
            c = float(parts[0]); x, y, w, h = map(float, parts[1:])
        except ValueError:
            return [], f"line {i}: non-numeric value"
        if c != int(c) or not 0 <= int(c) < n_classes:
            return [], f"line {i}: class id {parts[0]} outside 0..{n_classes - 1}"
        if not all(0 <= v <= 1 for v in (x, y, w, h)) or w <= 0 or h <= 0:
            return [], f"line {i}: coordinates outside 0..1"
        rows.append((int(c), x, y, w, h))
    return rows, None


def write_yolo(path: Path, rows):
    path.write_text("".join(f"{c} {x:.6f} {y:.6f} {w:.6f} {h:.6f}\n" for c, x, y, w, h in rows),
                    encoding="utf-8")


def list_images(folder: Path):
    return sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXTS)


def safe_reset(folder: Path):
    """Delete a folder only if it lives inside prepared/ (never touch sources)."""
    folder = folder.resolve()
    if PREPARED.resolve() not in folder.parents:
        sys.exit(f"Refusing to delete {folder}: not inside {PREPARED}")
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)


def split_of(group: str, val_ratio: float, seed: int) -> str:
    """Deterministic: a group keeps its split when new images or groups are added."""
    h = int(hashlib.sha256(f"{seed}:{group}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
    return "val" if h < val_ratio else "train"


# ---------------------------------------------------------------------------
# remap
# ---------------------------------------------------------------------------
def cmd_remap(args):
    src = ROOT / "Construction_PPE_500"
    out = PREPARED / "ppe_remapped"
    safe_reset(out)
    (out / "images").mkdir(); (out / "labels").mkdir()

    kept, dropped, problems = Counter(), Counter(), []
    for img in list_images(src / "images"):
        lbl = src / "labels" / f"{img.stem}.txt"
        if not lbl.exists():
            problems.append(f"{img.name}: missing label"); continue
        rows, err = parse_yolo(lbl, 12)
        if err:
            problems.append(f"{lbl.name}: {err}"); continue
        new = []
        for c, *box in rows:
            if c in PPE_TO_TITAN:
                new.append((PPE_TO_TITAN[c], *box)); kept[PPE_TO_TITAN[c]] += 1
            else:
                dropped[c] += 1
        shutil.copy2(img, out / "images" / img.name)
        write_yolo(out / "labels" / lbl.name, new)

    report = [f"Remapped Construction_PPE_500 -> {out}",
              f"Images written: {len(list_images(out / 'images'))}",
              f"Problems: {len(problems)}", *problems, "", "Kept boxes (TITAN ids):"]
    report += [f"  {i} {CLASSES[i]:<14}{kept[i]:>6}" for i in range(len(CLASSES))]
    report += ["Dropped boxes (original Ultralytics ids): " + str(dict(sorted(dropped.items())))]
    (out / "remap_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def load_excludes():
    f = ANNOT / "exclude.txt"
    if not f.exists():
        return set()
    return {l.strip().replace("\\", "/") for l in f.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")}


def cmd_build(args):
    pins = dict(p.split("=", 1) for p in args.pin)     # --pin framing=train
    excludes = load_excludes()
    rows, problems = [], []

    for s in SOURCES:
        if not s.images.exists():
            problems.append(f"[{s.name}] image folder not found: {s.images}"); continue
        lbl_dir = s.labels or (ANNOT / s.name)
        for img in list_images(s.images)[:: s.step]:
            key = f"{s.name}/{img.name}"
            lbl = lbl_dir / f"{img.stem}.txt"
            r = {"uid": f"{s.name}__{img.name}", "source": s.name, "group": s.group_fn(img),
                 "src_image": str(img.relative_to(ROOT)), "src_label": "", "status": "", "split": "",
                 "n_boxes": 0, "classes": ""}
            if key in excludes:
                r["status"] = "excluded"
            elif not lbl.exists():
                r["status"] = "unlabelled"
            else:
                boxes, err = parse_yolo(lbl, len(CLASSES))
                r["src_label"] = str(lbl.relative_to(ROOT))
                if err:
                    r["status"] = "invalid_label"; problems.append(f"{key}: {err}")
                else:
                    r["status"] = "ready"; r["n_boxes"] = len(boxes)
                    r["classes"] = " ".join(str(c) for c in sorted({b[0] for b in boxes}))
                    r["_boxes"] = boxes
            rows.append(r)

    # Group-wise split. Pins win; otherwise a stable hash of the group name.
    for r in rows:
        if r["status"] == "ready":
            src_pin = pins.get(r["source"]) or next(s.pin for s in SOURCES if s.name == r["source"])
            r["split"] = src_pin or split_of(r["group"], args.val_ratio, args.seed)

    # Leakage check: no group may appear in two splits.
    g_splits = defaultdict(set)
    for r in rows:
        if r["split"]:
            g_splits[r["group"]].add(r["split"])
    leaks = [g for g, s in g_splits.items() if len(s) > 1]
    if leaks:
        sys.exit(f"LEAKAGE: groups in more than one split: {leaks[:10]}")

    out = PREPARED / "titan_v1"
    safe_reset(out)
    for sp in ("train", "val"):
        (out / "images" / sp).mkdir(parents=True); (out / "labels" / sp).mkdir(parents=True)
    for r in rows:
        if r["status"] != "ready":
            continue
        img = ROOT / r["src_image"]
        shutil.copy2(img, out / "images" / r["split"] / r["uid"])
        write_yolo(out / "labels" / r["split"] / f"{Path(r['uid']).stem}.txt", r["_boxes"])

    (out / "data.yaml").write_text(
        f"# Generated by tools/prepare_dataset.py - do not edit by hand\n"
        f"path: {out.as_posix()}\ntrain: images/train\nval: images/val\n"
        f"names:\n" + "".join(f"  {i}: {n}\n" for i, n in enumerate(CLASSES)), encoding="utf-8")

    cols = ["uid", "source", "group", "status", "split", "n_boxes", "classes", "src_image", "src_label"]
    for target in (out / "manifest.csv", PREPARED / "manifest.csv"):
        with target.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader(); w.writerows(rows)

    # Report
    status = Counter((r["source"], r["status"]) for r in rows)
    lines = [f"Build: {out}", f"val_ratio={args.val_ratio} seed={args.seed} pins={pins or 'none'}", "",
             f"{'source':<10}{'ready':>7}{'unlabelled':>12}{'excluded':>10}{'invalid':>9}"]
    for s in SOURCES:
        lines.append(f"{s.name:<10}{status[(s.name, 'ready')]:>7}{status[(s.name, 'unlabelled')]:>12}"
                     f"{status[(s.name, 'excluded')]:>10}{status[(s.name, 'invalid_label')]:>9}")
    lines += ["", f"{'id':>3} {'class':<14}" + "".join(f"{sp + ' boxes':>12}{sp + ' imgs':>11}" for sp in ("train", "val"))]
    for i, n in enumerate(CLASSES):
        cells = ""
        for sp in ("train", "val"):
            rs = [r for r in rows if r["split"] == sp]
            cells += f"{sum(1 for r in rs for b in r['_boxes'] if b[0] == i):>12}"
            cells += f"{sum(1 for r in rs if any(b[0] == i for b in r['_boxes'])):>11}"
        lines.append(f"{i:>3} {n:<14}{cells}")
    for sp in ("train", "val"):
        rs = [r for r in rows if r["split"] == sp]
        lines.append(f"{sp}: {len(rs)} images from {len({r['group'] for r in rs})} groups, "
                     f"{sum(1 for r in rs if r['n_boxes'] == 0)} background")
    empty_cls = [CLASSES[i] for i in range(len(CLASSES))
                 if not any(b[0] == i for r in rows if r["split"] == "val" for b in r["_boxes"])]
    if empty_cls:
        lines.append(f"WARNING: no val examples for: {', '.join(empty_cls)} (cannot be evaluated yet)")
    lines += ["", "Leakage check: OK (every group is in exactly one split)",
              f"Problems: {len(problems)}", *problems]
    (out / "build_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------
def cmd_check(args):
    from PIL import Image, ImageDraw
    ds = Path(args.dataset)
    imgs = [p for sp in ("train", "val") for p in list_images(ds / "images" / sp)]
    if args.source:
        imgs = [p for p in imgs if p.name.startswith(args.source + "__")]
    random.Random(args.seed).shuffle(imgs)
    out = PREPARED / "qa"
    safe_reset(out)
    colors = ["#e6194b", "#3cb44b", "#ffe119", "#4363d8", "#f58231", "#911eb4", "#42d4f4", "#f032e6"]
    for img in imgs[: args.n]:
        lbl = ds / "labels" / img.parent.name / f"{img.stem}.txt"
        boxes, _ = parse_yolo(lbl, len(CLASSES)) if lbl.exists() else ([], None)
        with Image.open(img) as im:
            im = im.convert("RGB")
            W, H = im.size
            d = ImageDraw.Draw(im)
            lw = max(2, W // 400)
            for c, x, y, w, h in boxes:
                x0, y0, x1, y1 = (x - w / 2) * W, (y - h / 2) * H, (x + w / 2) * W, (y + h / 2) * H
                d.rectangle([x0, y0, x1, y1], outline=colors[c], width=lw)
                d.text((x0 + 3, max(0, y0 - 12)), CLASSES[c], fill=colors[c])
            im.thumbnail((1280, 1280))
            im.save(out / f"{img.parent.name}__{img.stem}.jpg", quality=85)
    print(f"Wrote {min(args.n, len(imgs))} review images to {out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("remap")
    b = sub.add_parser("build")
    b.add_argument("--val-ratio", type=float, default=0.2)
    b.add_argument("--seed", type=int, default=42)
    b.add_argument("--pin", action="append", default=[], metavar="SOURCE=SPLIT",
                   help="force a whole source into train or val, e.g. --pin framing=train")
    c = sub.add_parser("check")
    c.add_argument("--dataset", default=str(PREPARED / "titan_v1"))
    c.add_argument("--n", type=int, default=40)
    c.add_argument("--source", default=None, help="only images from this source, e.g. barwita")
    c.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    {"remap": cmd_remap, "build": cmd_build, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    main()
