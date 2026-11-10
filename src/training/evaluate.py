"""
TITAN AI - evaluate a trained model and look at its predictions.

Examples:
    # Per-class metrics on the val split (+ confusion matrix in runs/titan/eval_*)
    python src/training/evaluate.py --weights runs/titan/v1_11s_960/weights/best.pt

    # Also run predictions on a video or image folder and save annotated output
    python src/training/evaluate.py --weights runs/titan/v1_11s_960/weights/best.pt \
        --source raw/framing/original_video.mp4

Note: the framing video is in the TRAINING set, so predictions on it only show that
training worked. Real testing needs footage the model has never seen (Hikvision test video).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "prepared" / "titan_v1" / "data.yaml"


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--weights", required=True, help="path to best.pt")
    ap.add_argument("--data", default=str(DEFAULT_DATA))
    ap.add_argument("--imgsz", type=int, default=960, help="use the same size as training")
    ap.add_argument("--conf", type=float, default=0.25, help="confidence threshold for --source predictions")
    ap.add_argument("--source", default=None, help="video file, image, or folder to predict on")
    ap.add_argument("--device", default=None)
    ap.add_argument("--skip-val", action="store_true", help="only run predictions")
    return ap.parse_args()


def print_per_class(metrics, names):
    """Table of P / R / mAP50 / mAP50-95 per class, worst mAP50 first."""
    box = metrics.box
    rows = []
    for k, cls_id in enumerate(box.ap_class_index):
        p, r, ap50, ap = box.class_result(k)
        rows.append((names[int(cls_id)], p, r, ap50, ap))
    rows.sort(key=lambda x: x[3])
    print(f"\n{'class':<15}{'P':>7}{'R':>7}{'mAP50':>8}{'mAP50-95':>10}")
    for n, p, r, ap50, ap in rows:
        flag = "   <- weak" if ap50 < 0.5 else ""
        print(f"{n:<15}{p:>7.3f}{r:>7.3f}{ap50:>8.3f}{ap:>10.3f}{flag}")
    print(f"{'ALL':<15}{box.mp:>7.3f}{box.mr:>7.3f}{box.map50:>8.3f}{box.map:>10.3f}")

    missing = [n for i, n in names.items() if i not in set(int(c) for c in box.ap_class_index)]
    if missing:
        print(f"\nNo val examples (not evaluated): {', '.join(missing)}")


def main():
    args = parse_args()
    from ultralytics import YOLO

    weights = Path(args.weights)
    if not weights.exists():
        sys.exit(f"weights not found: {weights}")
    model = YOLO(str(weights))
    run_dir = weights.parent.parent          # runs/titan/<name>/

    if not args.skip_val:
        metrics = model.val(data=args.data, imgsz=args.imgsz, split="val", plots=True,
                            device=args.device, project=str(run_dir.parent), name=f"eval_{run_dir.name}")
        print_per_class(metrics, model.names)
        print(f"\nPlots (confusion matrix, PR curves): {metrics.save_dir}")

    if args.source:
        res = model.predict(source=args.source, imgsz=args.imgsz, conf=args.conf, device=args.device,
                            save=True, stream=True, project=str(run_dir.parent),
                            name=f"predict_{run_dir.name}")
        save_dir = None
        for r in res:                    # stream=True keeps memory low on long videos
            save_dir = r.save_dir
        print(f"\nAnnotated predictions saved to: {save_dir}")


if __name__ == "__main__":
    main()
