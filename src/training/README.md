# Training YOLOv11 (TITAN v1)

## 1. Environment (once, from the repo root)
```bash
python -m venv .venv
.venv\Scripts\activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
pip install -r src/training/requirements.txt
python -c "import torch; print(torch.cuda.is_available())"   # must print True
```

## 2. Build the dataset
```bash
python tools/prepare_dataset.py remap
python tools/prepare_dataset.py build --pin framing=train
```
`chain_closed` / `chain_open` exist only in `framing`, which is pinned to train, so they have no
val metrics yet. Judge them by eye with `--source` predictions until TITAN footage arrives.

## 3. Train
```bash
python src/training/train.py                    # yolo11s, imgsz 960, auto batch
```
Out of GPU memory? `--imgsz 640` or `--model yolo11n.pt`. Interrupted? `--resume runs/titan/<name>/weights/last.pt`.

## 4. Evaluate
```bash
python src/training/evaluate.py --weights runs/titan/v1_11s_960/weights/best.pt --source raw/framing/original_video.mp4
```
Prints per-class P / R / mAP (weakest first) and saves the confusion matrix and annotated video.

## Colab
`notebooks/train_yolo11.ipynb` does the same steps on a free T4 GPU and downloads the results.
