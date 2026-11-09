"""
Create a reproducible random subset of the Ultralytics Construction-PPE dataset.

Images and labels are always selected as PAIRS (never independently).
The source dataset is only read, never modified.

Usage:
    python make_subset.py --src <dataset root> --out <output folder>            # preview (default, writes nothing)
    python make_subset.py --src <dataset root> --out <output folder> --copy     # copy files + write report
"""
import argparse
import csv
import hashlib
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path

IMG_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLITS = ("train", "val")


def load_names(src: Path) -> dict:
    names, inside = {}, False
    for line in (src / "data.yaml").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("names:"):
            inside = True
            continue
        if inside:
            if not line.startswith((" ", "\t")):
                break
            k, _, v = line.strip().partition(":")
            names[int(k)] = v.strip()
    return names


def check_label(path: Path, n_classes: int):
    """Return (problem or None, list of class ids)."""
    if not path.exists():
        return "missing label file", []
    classes = []
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        return f"unreadable: {e!r}", []
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5:
            return f"line {i}: expected 5 values, got {len(parts)}", []
        try:
            c = float(parts[0]); x, y, w, h = map(float, parts[1:])
        except ValueError:
            return f"line {i}: non-numeric value", []
        if c != int(c) or not 0 <= int(c) < n_classes:
            return f"line {i}: invalid class id {parts[0]}", []
        if not all(0.0 <= v <= 1.0 for v in (x, y, w, h)) or w <= 0 or h <= 0:
            return f"line {i}: coordinates out of range", []
        classes.append(int(c))
    return None, classes


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--copy", action="store_true", help="actually copy (default is preview only)")
    args = ap.parse_args()

    src, out = Path(args.src).resolve(), Path(args.out).resolve()
    if out == src or src in out.parents:
        sys.exit("Output folder must be outside the source dataset.")
    names = load_names(src)

    # 1. Build image->label pairs in a deterministic order
    pairs = []
    for split in SPLITS:
        for img in sorted((src / "images" / split).iterdir()):
            if img.is_file() and img.suffix.lower() in IMG_EXTS:
                pairs.append((split, img, src / "labels" / split / f"{img.stem}.txt"))
    stems = Counter(img.stem for _, img, _ in pairs)
    clashes = [s for s, c in stems.items() if c > 1]
    if clashes:
        sys.exit(f"Filename clash between splits, cannot flatten: {clashes[:5]}")

    # 2. Seeded shuffle, then take the first N pairs whose label is valid
    rng = random.Random(args.seed)
    order = pairs[:]
    rng.shuffle(order)
    selected, rejected = [], []
    for split, img, lbl in order:
        if len(selected) == args.n:
            break
        problem, classes = check_label(lbl, len(names))
        if problem:
            rejected.append((split, img.name, problem))
            continue
        selected.append((split, img, lbl, classes))
    if len(selected) < args.n:
        sys.exit(f"Only {len(selected)} valid pairs available, need {args.n}.")

    # 3. Summary
    box_count, img_count = Counter(), Counter()
    for *_, classes in selected:
        box_count.update(classes)
        img_count.update(set(classes))
    split_count = Counter(s for s, *_ in selected)
    empty = sum(1 for *_, c in selected if not c)

    lines = [
        f"Source: {src}",
        f"Output: {out}",
        f"Mode: {'COPY' if args.copy else 'PREVIEW (nothing written)'}",
        f"Seed: {args.seed}",
        f"Pairs in source: {len(pairs)} (" + ", ".join(f"{s}={sum(1 for p in pairs if p[0]==s)}" for s in SPLITS) + ")",
        f"Selected images: {len(selected)}",
        f"Selected from each split: " + ", ".join(f"{s}={split_count[s]}" for s in SPLITS),
        f"Missing/invalid labels encountered and replaced: {len(rejected)}",
        f"Selected labels with zero boxes (background images): {empty}",
        f"Total boxes in subset: {sum(box_count.values())}",
        "",
        f"{'id':>3}  {'class':<12}{'boxes':>7}{'images':>8}",
    ]
    for cid in sorted(names):
        lines.append(f"{cid:>3}  {names[cid]:<12}{box_count[cid]:>7}{img_count[cid]:>8}")
    for split, name, problem in rejected:
        lines.append(f"REJECTED [{split}] {name}: {problem}")
    print("\n".join(lines))

    if not args.copy:
        print("\nPreview only. Re-run with --copy to create the subset.")
        return

    # 4. Copy (refuse to overwrite anything)
    if out.exists() and any(out.iterdir()):
        sys.exit(f"Output folder {out} already exists and is not empty. Nothing copied.")
    (out / "images").mkdir(parents=True, exist_ok=True)
    (out / "labels").mkdir(parents=True, exist_ok=True)
    manifest, mismatches = [], 0
    for split, img, lbl, classes in selected:
        di, dl = out / "images" / img.name, out / "labels" / lbl.name
        shutil.copy2(img, di)
        shutil.copy2(lbl, dl)
        hi = sha256(img)
        if hi != sha256(di) or sha256(lbl) != sha256(dl):
            mismatches += 1
        manifest.append({"image": img.name, "label": lbl.name, "original_split": split,
                         "boxes": len(classes), "image_sha256": hi})

    n_img = sum(1 for p in (out / "images").iterdir() if p.is_file())
    n_lbl = sum(1 for p in (out / "labels").iterdir() if p.is_file())
    unpaired = {p.stem for p in (out / "images").iterdir()} ^ {p.stem for p in (out / "labels").iterdir()}

    with (out / "selection_manifest.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(manifest[0]))
        w.writeheader(); w.writerows(manifest)
    if (src / "LICENSE.txt").exists():
        shutil.copy2(src / "LICENSE.txt", out / "LICENSE.txt")

    report = lines + [
        "",
        "=== Copy verification ===",
        f"Image files in output: {n_img}",
        f"Label files in output: {n_lbl}",
        f"Unpaired files in output: {len(unpaired)}",
        f"Checksum mismatches after copy: {mismatches}",
        "",
        "Attribution: Ultralytics Construction-PPE Dataset, Ultralytics team, November 2026, CC BY 4.0.",
        "Changes: random subset of 500 images (seed above); train/val folders flattened into images/ and labels/;",
        "original split recorded in selection_manifest.csv. Files are otherwise unmodified.",
    ]
    (out / "subset_report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    (out / "subset_report.json").write_text(json.dumps({
        "seed": args.seed, "selected_images": n_img, "copied_labels": n_lbl,
        "rejected": [{"split": s, "file": n, "problem": p} for s, n, p in rejected],
        "split_counts": dict(split_count),
        "class_boxes": {names[c]: box_count[c] for c in sorted(names)},
        "class_images": {names[c]: img_count[c] for c in sorted(names)},
        "checksum_mismatches": mismatches, "unpaired": sorted(unpaired),
    }, indent=2), encoding="utf-8")
    shutil.copy2(Path(__file__), out / "make_subset.py")
    print("\n" + "\n".join(report[len(lines):]))


if __name__ == "__main__":
    main()
