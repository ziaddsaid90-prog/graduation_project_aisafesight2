"""
TITAN AI - train a YOLOv11 detector on prepared/titan_v1.

Before running:
    python tools/prepare_dataset.py remap
    python tools/prepare_dataset.py build --pin framing=train

Examples:
    python src/training/train.py                              # yolo11s, imgsz 960 (baseline)
    python src/training/train.py --model yolo11n.pt --name v1_n960
    python src/training/train.py --imgsz 640 --batch 8        # if the GPU runs out of memory
    python src/training/train.py --resume runs/titan/v1_11s_960/weights/last.pt

Outputs go to runs/titan/<name>/ (weights/best.pt, results.csv, confusion matrix, PR curves).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = ROOT / "prepared" / "titan_v1" / "data.yaml"


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(DEFAULT_DATA), help="data.yaml written by prepare_dataset.py build")
    ap.add_argument("--model", default="yolo11s.pt", help="pretrained weights: yolo11n/s/m.pt")
    ap.add_argument("--imgsz", type=int, default=960, help="960 helps small objects seen from CCTV height")
    ap.add_argument("--epochs", type=int, default=100)
    ap.add_argument("--patience", type=int, default=25, help="stop early after N epochs without improvement")
    ap.add_argument("--batch", type=float, default=-1,
                    help="-1 = auto (fits GPU memory), or a fixed number like 4/8/16")
    ap.add_argument("--workers", type=int, default=2, help="dataloader processes; keep low on Windows")
    ap.add_argument("--device", default=None, help="0 for the first GPU, 'cpu' to force CPU")
    ap.add_argument("--name", default=None, help="run name (default: v1_<model>_<imgsz>)")
    ap.add_argument("--project", default=str(ROOT / "runs" / "titan"))
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--resume", default=None, help="path to last.pt to continue an interrupted run")
    return ap.parse_args()


def preflight(data: Path):
    """Fail early with a clear message instead of a long Ultralytics traceback."""
    if not data.exists():
        sys.exit(f"data.yaml not found: {data}\n"
                 "Run:  python tools/prepare_dataset.py remap\n"
                 "      python tools/prepare_dataset.py build --pin framing=train")

    report = data.parent / "build_report.txt"
    if report.exists():
        for line in report.read_text(encoding="utf-8").splitlines():
            if line.startswith("WARNING"):
                print(f"[build_report] {line}")
                print("               Those classes will show no val metrics - check them by eye with predict.")

    import torch
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        print(f"GPU: {p.name}, {p.total_memory / 1024**3:.1f} GB")
    else:
        print("WARNING: CUDA not available - training will run on the CPU and be very slow.\n"
              "         Reinstall torch with CUDA (see src/training/README.md) or use the Colab notebook.")


def main():
    args = parse_args()
    from ultralytics import YOLO

    if args.resume:
        YOLO(args.resume).train(resume=True)
        return

    data = Path(args.data).resolve()
    preflight(data)

    name = args.name or f"v1_{Path(args.model).stem.replace('yolo', '')}_{args.imgsz}"
    batch = int(args.batch) if args.batch >= 1 or args.batch == -1 else args.batch

    model = YOLO(args.model)            # downloads the COCO-pretrained weights on first use
    model.train(
        data=str(data),
        imgsz=args.imgsz,
        epochs=args.epochs,
        patience=args.patience,
        batch=batch,
        workers=args.workers,
        device=args.device,
        project=args.project,
        name=name,
        seed=args.seed,
        deterministic=True,
        cos_lr=True,          # smooth learning-rate decay, helps on small datasets
        close_mosaic=10,      # turn mosaic off for the last 10 epochs so the model sees whole images
        amp=True,             # mixed precision: faster and uses less GPU memory
        plots=True,
        exist_ok=False,
    )

    best = Path(args.project) / name / "weights" / "best.pt"
    print(f"\nDone. Best weights: {best}")
    print(f"Next: python src/training/evaluate.py --weights {best}")


if __name__ == "__main__":   # required on Windows when workers > 0
    main()
