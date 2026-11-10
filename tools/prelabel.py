"""
Pre-label images with a pretrained COCO YOLO model and package the result for CVAT.

The model only knows COCO classes, so it pre-draws:
    person                     -> person (0)
    truck                      -> mixer_truck (6) or vehicle_other (7), see --truck-as
    car / bus / motorcycle     -> vehicle_other (7)
helmet / no_helmet / vest / no_vest / wheelbarrow must still be drawn by hand.
Every box MUST be reviewed in CVAT. These are suggestions, not ground truth.

Usage (from the repo root, inside .venv):
    python tools/prelabel.py --source mixer --images raw/mixer --truck-as mixer_truck

Output: prepared/prelabels/<source>/cvat_yolo11_<source>.zip  -> CVAT: Actions > Upload annotations > YOLO 1.1
        prepared/prelabels/<source>/preview/                  -> drawn boxes for a quick look
"""
import argparse
import sys
import zipfile
from pathlib import Path

from ultralytics import YOLO

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prepare_dataset import CLASSES, PREPARED, ROOT, list_images  # noqa: E402

COCO_TO_TITAN = {0: 0, 2: 7, 3: 7, 5: 7}   # person, car, motorcycle, bus
COCO_TRUCK = 7


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="annotation source name, e.g. mixer")
    ap.add_argument("--images", required=True, help="image folder, relative to repo root")
    ap.add_argument("--truck-as", choices=["mixer_truck", "vehicle_other"], default="vehicle_other")
    ap.add_argument("--model", default="yolo11l.pt")
    ap.add_argument("--conf", type=float, default=0.35)
    ap.add_argument("--imgsz", type=int, default=1280)
    args = ap.parse_args()

    mapping = dict(COCO_TO_TITAN)
    mapping[COCO_TRUCK] = CLASSES.index(args.truck_as)

    images = list_images(ROOT / args.images)
    out = PREPARED / "prelabels" / args.source
    (out / "preview").mkdir(parents=True, exist_ok=True)
    model = YOLO(args.model)

    labels, counts = {}, {c: 0 for c in CLASSES}
    for img in images:
        r = model.predict(str(img), conf=args.conf, imgsz=args.imgsz, verbose=False)[0]
        lines = []
        for cls, xywhn in zip(r.boxes.cls.tolist(), r.boxes.xywhn.tolist()):
            if int(cls) in mapping:
                t = mapping[int(cls)]
                counts[CLASSES[t]] += 1
                lines.append(f"{t} " + " ".join(f"{v:.6f}" for v in xywhn))
        labels[img.name] = "\n".join(lines) + ("\n" if lines else "")
        r.save(filename=str(out / "preview" / f"{img.stem}.jpg"))

    zpath = out / f"cvat_yolo11_{args.source}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("obj.names", "\n".join(CLASSES) + "\n")
        z.writestr("obj.data", f"classes = {len(CLASSES)}\nnames = data/obj.names\n"
                               f"train = data/train.txt\nbackup = backup/\n")
        z.writestr("train.txt", "".join(f"data/obj_train_data/{n}\n" for n in labels))
        for name, text in labels.items():
            z.writestr(f"obj_train_data/{Path(name).stem}.txt", text)

    print(f"Images: {len(images)}  |  images with no detections: "
          f"{sum(1 for t in labels.values() if not t)}")
    print("Pre-drawn boxes:", {k: v for k, v in counts.items() if v})
    print(f"CVAT upload file: {zpath}")
    print(f"Previews: {out / 'preview'}")


if __name__ == "__main__":
    main()
