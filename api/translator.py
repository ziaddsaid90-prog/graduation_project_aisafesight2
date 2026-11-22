"""
Machine translation English <-> Arabic with local MarianMT models (Helsinki-NLP), on the GPU when there is one.

- Models are downloaded once from Hugging Face into the user cache, then work offline.
- Every translation is stored in SQLite (table translations), so a text is translated only once.
- api/translation_fixes.json holds corrections for texts the model gets wrong. A fix always wins
  over the model. To correct a translation, add it there and restart the API.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Callable

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

MODELS = {("en", "ar"): "Helsinki-NLP/opus-mt-en-ar", ("ar", "en"): "Helsinki-NLP/opus-mt-ar-en"}
# opus-mt-en-ar can write several Arabic variants; this token asks for standard Arabic
TARGET_PREFIX = {("en", "ar"): ">>ara<< "}
MAX_TEXTS = 300
MAX_CHARS = 1000

SCHEMA = """
CREATE TABLE IF NOT EXISTS translations (
    source_lang TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    source_text TEXT NOT NULL,
    translation TEXT NOT NULL,
    PRIMARY KEY (source_lang, target_lang, source_text)
);
"""


class Translator:
    def __init__(self, connect: Callable[[], sqlite3.Connection], fixes_file: Path):
        self.connect = connect
        self.fixes_file = fixes_file
        self.fixes = self._load_fixes()
        self._models: dict = {}
        self._lock = threading.Lock()
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def _load_fixes(self) -> dict:
        """{"en->ar": {"Sign in": "تسجيل الدخول", ...}, "ar->en": {...}}"""
        if not self.fixes_file.exists():
            return {}
        data = json.loads(self.fixes_file.read_text(encoding="utf-8"))
        return {pair: {k.strip(): v for k, v in table.items()} for pair, table in data.items() if not pair.startswith("_")}

    def preload(self) -> None:
        """Load both models in the background so the first request is fast."""
        def work():
            for pair in MODELS:
                try:
                    self._model(pair)
                except Exception as exc:
                    print(f"[translate] could not load {MODELS[pair]}: {exc}")
        threading.Thread(target=work, daemon=True).start()

    def _model(self, pair):
        with self._lock:
            if pair not in self._models:
                import torch
                from transformers import MarianMTModel, MarianTokenizer
                device = "cuda" if torch.cuda.is_available() else "cpu"
                tok = MarianTokenizer.from_pretrained(MODELS[pair])
                model = MarianMTModel.from_pretrained(MODELS[pair]).to(device).eval()
                self._models[pair] = (tok, model, device)
                print(f"[translate] {MODELS[pair]} ready on {device}")
            return self._models[pair]

    def translate(self, texts: list[str], source: str, target: str) -> list[str]:
        pair = (source, target)
        if source == target:
            return list(texts)
        if pair not in MODELS:
            raise ValueError(f"Only en->ar and ar->en are supported, not {source}->{target}")

        fixes = self.fixes.get(f"{source}->{target}", {})
        result: list[str | None] = [None] * len(texts)
        todo: dict[str, list[int]] = {}
        for i, text in enumerate(texts):
            # keep leading/trailing spaces (e.g. "Violations detected: ") around the translated core
            core = text.strip()
            if not core:
                result[i] = text
            elif core in fixes:
                result[i] = text.replace(core, fixes[core])
            else:
                todo.setdefault(core, []).append(i)

        if todo:
            cores = list(todo)
            with self.connect() as conn:
                cached = {}
                for start in range(0, len(cores), 500):   # SQLite limits the number of ? per query
                    chunk = cores[start:start + 500]
                    rows = conn.execute(
                        f"SELECT source_text, translation FROM translations WHERE source_lang = ? AND target_lang = ? "
                        f"AND source_text IN ({','.join('?' * len(chunk))})", (source, target, *chunk)).fetchall()
                    cached.update({r[0]: r[1] for r in rows})
            missing = [c for c in cores if c not in cached]
            if missing:
                new = self._run_model(pair, missing)
                with self.connect() as conn:
                    conn.executemany("INSERT OR REPLACE INTO translations VALUES (?, ?, ?, ?)",
                                     [(source, target, s, t) for s, t in zip(missing, new)])
                cached.update(zip(missing, new))
            for core, indexes in todo.items():
                for i in indexes:
                    result[i] = texts[i].replace(core, cached[core])
        return result  # type: ignore[return-value]

    def _run_model(self, pair, texts: list[str]) -> list[str]:
        import torch
        tok, model, device = self._model(pair)
        prefix = TARGET_PREFIX.get(pair, "")
        out: list[str] = []
        for start in range(0, len(texts), 16):
            batch = tok([prefix + t for t in texts[start:start + 16]], return_tensors="pt",
                        padding=True, truncation=True).to(device)
            with torch.no_grad():
                generated = model.generate(**batch, num_beams=4, max_new_tokens=256)
            out += tok.batch_decode(generated, skip_special_tokens=True)
        return out
