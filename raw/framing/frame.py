"""
Extract timestamped frames from a video for dataset building.

Examples:
    python extract_frames.py video_dataset.mp4              # 5 fps (default)
    python extract_frames.py video_dataset.mp4 --fps 2
    python extract_frames.py video_dataset.mp4 --fps 10 --clean   # timestamp + clean copies
    python extract_frames.py video_dataset.mp4 --no-overlay       # no timestamp on images
    python extract_frames.py video_dataset.mp4 --fps 5 --out my_frames

Install:
    pip install opencv-python
"""
import argparse
import csv
import os
import sys

import cv2


def fmt_hms(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def unique_dir(base: str) -> str:
    """Return base, or base_2, base_3 ... so an existing folder is never reused."""
    if not os.path.exists(base):
        return base
    n = 2
    while os.path.exists(f"{base}_{n}"):
        n += 1
    return f"{base}_{n}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="path to the video file")
    ap.add_argument("--fps", type=float, default=5.0, help="frames to save per second of video")
    ap.add_argument("--out", default=None, help="output folder (default: <video name>_frames)")
    ap.add_argument("--quality", type=int, default=95, help="JPEG quality 1-100")
    ap.add_argument("--no-overlay", action="store_true",
                    help="do NOT draw the timestamp on the images")
    ap.add_argument("--clean", action="store_true",
                    help="also save a clean copy (no timestamp) in <out>/clean")
    args = ap.parse_args()

    if not os.path.isfile(args.video):
        sys.exit(f"File not found: {args.video}")

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        sys.exit("Could not open the video.")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total / src_fps
    step = 1.0 / args.fps  # seconds between saved frames

    name = os.path.splitext(os.path.basename(args.video))[0]
    fps_tag = f"{args.fps:g}".replace(".", "p")
    out_dir = unique_dir(args.out or f"{name}_frames_{fps_tag}fps")
    os.makedirs(out_dir, exist_ok=True)
    clean_dir = os.path.join(out_dir, "clean")
    if args.clean:
        os.makedirs(clean_dir, exist_ok=True)

    print(f"Video: {args.video}")
    print(f"Source fps: {src_fps:.2f} | frames: {total} | duration: {duration:.2f}s")
    print(f"Saving {args.fps} frame(s) per second to: {out_dir}")

    rows = []
    saved = 0
    next_t = 0.0
    idx = 0  # source frame number

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / src_fps
        if t + 1e-9 >= next_t:
            saved += 1
            ms = int(round(t * 1000))
            fname = f"frame_{saved:05d}_t{ms:07d}ms.jpg"
            params = [cv2.IMWRITE_JPEG_QUALITY, args.quality]
            if args.clean:
                cv2.imwrite(os.path.join(clean_dir, fname), frame, params)
            out_img = frame
            if not args.no_overlay:
                out_img = frame.copy()
                label = fmt_hms(t)
                scale = max(0.6, frame.shape[1] / 1400)
                thick = max(1, int(round(scale * 2)))
                (tw, th), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
                x, y = 12, 12 + th
                cv2.rectangle(out_img, (x - 6, y - th - 6), (x + tw + 6, y + base + 4), (0, 0, 0), -1)
                cv2.putText(out_img, label, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                            scale, (255, 255, 255), thick, cv2.LINE_AA)
            cv2.imwrite(os.path.join(out_dir, fname), out_img, params)
            rows.append([saved, fname, round(t, 3), fmt_hms(t), idx])
            next_t += step
        idx += 1
    cap.release()

    csv_path = os.path.join(out_dir, "frames_manifest.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["frame_index", "filename", "timestamp_seconds", "timestamp_hms", "source_frame_number"])
        w.writerows(rows)

    print(f"Done. Saved {saved} frames.")
    print(f"Manifest: {csv_path}")


if __name__ == "__main__":
    main()