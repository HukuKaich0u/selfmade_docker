from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf


def ensure_parent(path: str | Path) -> Path:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    return output_path


def write_wav(path: str | Path, waveform: np.ndarray, sample_rate: int) -> Path:
    output_path = ensure_parent(path)
    sf.write(output_path, waveform.astype(np.float32), sample_rate)
    return output_path


def read_wav(path: str | Path) -> tuple[np.ndarray, int]:
    waveform, sample_rate = sf.read(Path(path), always_2d=False)
    waveform = np.asarray(waveform, dtype=np.float32)
    if waveform.ndim > 1:
        waveform = waveform.mean(axis=1)
    return waveform, int(sample_rate)


def write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    output_path = ensure_parent(path)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def write_array(path: str | Path, array: np.ndarray) -> Path:
    output_path = ensure_parent(path)
    np.save(output_path, array)
    return output_path


def read_array(path: str | Path) -> np.ndarray:
    return np.load(Path(path), allow_pickle=False)
