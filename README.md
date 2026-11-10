# TITAN AI – Construction Site Safety Dataset

The dataset and data tools for TITAN AI, a CCTV-based construction-site safety monitoring system (graduation project).

> **Stage 1 (now):** build a first detector from public and collected images.
> **Stage 2 (later):** add real TITAN site footage, label it, and fine-tune the Stage 1 model on it.

---

## 1. Setup (each team member, once)

```bash
# 1. Install Git and Git LFS (https://git-lfs.com), then:
git lfs install

# 2. Clone (images are downloaded through LFS automatically)
git clone https://github.com/YOUANNA13/graduation_project_aisafesight.git
cd graduation_project_aisafesight

# 3. Python 3.9+ with Pillow
pip install pillow
```

## 2. Folder structure

```
TITAN_AI_Dataset/
├── Construction_PPE_500/        public PPE subset, already labelled (do not edit)
├── raw/                         original files, never edited
│   ├── barwita/                 74 wheelbarrow images (web)
│   ├── mixer/                   52 concrete mixer truck images (web)
│   └── framing/                 15 s overhead site video + 151 extracted frames
├── annotated/                   what we train on
│   ├── barwita/   images/ labels/ annotation_report.txt   (72 images)
│   ├── mixer/     images/ labels/ annotation_report.txt   (47 images)
│   └── framing/   images/ labels/ annotation_report.txt   (31 keyframes, every 5th frame)
├── preview/<source>/            annotated images with boxes drawn on, for review only
├── tools/                       prepare_dataset.py (remap/build/check), prelabel.py
└── prepared/                    generated training set (not in git, rebuilt locally)
```

| Folder | Labels? | Status |
|---|---|---|
| `Construction_PPE_500/` | Yes (original 12 classes, remapped by `remap`) | **Ready** |
| `annotated/barwita/`, `annotated/mixer/`, `annotated/framing/` | Yes (TITAN v1 classes) | **Labelled 2026-11-10**, see each `annotation_report.txt` for images that need manual review |
| `raw/` | No | Kept for reference. Duplicates, collages and images with burned-in boxes were left out of `annotated/` |

**Chain barrier:** classes 8/9 (`chain_closed`, `chain_open`) are labelled only in `annotated/framing/` (real footage).
**Not in this repo:** `closed_open chain/` (AI-generated chain images). Do not label or train on it; more real chain footage comes with the TITAN recordings.

**Never commit TITAN company footage to this repository.** Raw site recordings go to the team's private storage.

## 3. Classes (TITAN v1)

The ID order is fixed. Configure your annotation tool with exactly this order:

| ID | Class | Label it when… |
|---|---|---|
| 0 | `person` | Any visible person (more than ~30% visible) |
| 1 | `helmet` | A hard hat being **worn** on a head (not one carried in a hand) |
| 2 | `no_helmet` | A visible head with no hard hat |
| 3 | `vest` | A hi-vis vest or jacket being worn |
| 4 | `no_vest` | A visible upper body with no hi-vis |
| 5 | `wheelbarrow` | A manual wheelbarrow or two-wheel concrete cart |
| 6 | `mixer_truck` | A concrete mixer truck |
| 7 | `vehicle_other` | Any other vehicle (truck, car, loader, forklift) |
| 8 | `chain_closed` | The entrance chain barrier hanging between its two posts (entrance blocked). One box around both posts and the chain |
| 9 | `chain_open` | The same barrier lowered to the ground or unhooked (entrance passable). Same box: both posts and the chain |

### Labelling rules (read before starting)
1. **Label every class present in the image**, not only the folder's class. A worker in a mixer photo still gets `person`, `helmet`/`no_helmet` and `vest`/`no_vest` boxes.
2. Draw tight boxes. Label partly hidden objects if more than ~30% is visible.
3. Occlusion alone is not "missing PPE". Use `no_helmet`/`no_vest` only when the head or torso is clearly visible.
4. Skip unusable images (watermark covering the object, collage, drawing) by not copying them into `annotated/<source>/images/`, or list them in `annotated/exclude.txt`, e.g. `barwita/17.jpg`.
5. An **empty** `.txt` means "checked, contains none of our classes".
6. Before starting, the labellers label the same 20 images and compare results, so everyone labels the same way.

### How to export labels
Label in **CVAT** or **Label Studio** and export as **YOLO** format. Put the image in `annotated/<source>/images/`
and its `.txt` in `annotated/<source>/labels/` with the same file name: `annotated/barwita/labels/105.txt` for
`annotated/barwita/images/105.jpg`. Source names are: `barwita`, `mixer`, `framing`.

## 4. Team assignments (Stage 1)

| Member | Works on | Writes only in | Branch |
|---|---|---|---|
| Member 1 (data lead) | `framing` keyframes + runs `build`/`check`, reviews label PRs | `annotated/framing/`, `tools/` | `label/framing` |
| Member 2 | `mixer` (52 images) | `annotated/mixer/` | `label/mixer` |
| Member 3 | `barwita` (74 images) | `annotated/barwita/` | `label/barwita` |
| Member 4 | Video pipeline: video/RTSP → pretrained YOLO + ByteTrack → evidence frames | `src/pipeline/` | `feat/pipeline` |
| Member 5 | Event engine (zones, rules, tests) + record our own Hikvision test footage | `src/events/`, `configs/` | `feat/events` |

Each person writes only in their own folder, so pull requests don't conflict.

### Daily git workflow
```bash
git checkout main && git pull
git checkout -b label/barwita        # once; afterwards: git checkout label/barwita && git merge main
# ... add/modify your files ...
git add annotated/barwita
git commit -m "Label barwita 100-130"
git push -u origin label/barwita     # then open a Pull Request on GitHub
```

## 5. Building the training set

```bash
python tools/prepare_dataset.py remap                    # once: Construction_PPE_500 -> TITAN classes
python tools/prepare_dataset.py build --pin framing=train
python tools/prepare_dataset.py check --n 40             # look at prepared/qa/ to review boxes
python tools/prepare_dataset.py check --source barwita   # review one folder's labels
```

`build` splits by **group** (frames of one video or photos of one scene always stay together) and stops
if any group would land in both train and val. See `prepared/titan_v1/build_report.txt`.

## 6. Roadmap

- **Now:** label `framing`, `mixer`, `barwita` → first training run (pretrained YOLO small/nano, imgsz 960) → per-class error analysis.
- **Before TITAN footage:** record our own overhead test video with the Hikvision camera (people with/without PPE, pushing a wheelbarrow). This is the test set and is never used for training.
- **After TITAN footage:** label TITAN frames (more chain barrier examples) → fine-tune the Stage 1 model → evaluate on unseen TITAN recording days.

## Attribution
`Construction_PPE_500` is a subset of the **Ultralytics Construction-PPE Dataset**, Ultralytics team, November 2026, CC BY 4.0
(https://docs.ultralytics.com/datasets/detect/construction-ppe). Changes: random 500-image subset (seed 42),
train/val folders merged; see `Construction_PPE_500/subset_report.txt`.
