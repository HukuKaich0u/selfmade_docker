from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import torch
import torchaudio.functional as F_audio

from iruka_cnn.common.io import read_wav


def rms_dbfs(waveform: torch.Tensor) -> float:
    rms = torch.sqrt(torch.mean(torch.square(waveform)) + 1e-12)
    return 20.0 * math.log10(float(rms) + 1e-12)


def resample_if_needed(waveform: torch.Tensor, source_rate: int, target_rate: int) -> torch.Tensor:
    if source_rate == target_rate:
        return waveform
    return F_audio.resample(waveform.unsqueeze(0), source_rate, target_rate).squeeze(0)


def normalize_audio(waveform: torch.Tensor) -> torch.Tensor:
    peak = waveform.abs().max()
    if float(peak) > 0:
        waveform = waveform / peak * 0.98
    rms = torch.sqrt(torch.mean(torch.square(waveform)) + 1e-12)
    if float(rms) > 1e-6:
        waveform = waveform / rms * 0.16
    return waveform.clamp(-1.0, 1.0)


def trim_and_pad(waveform: torch.Tensor, target_samples: int) -> torch.Tensor:
    current = waveform.shape[-1]
    if current == target_samples:
        return waveform
    if current > target_samples:
        start = (current - target_samples) // 2
        return waveform[start : start + target_samples]
    pad_total = target_samples - current
    left = pad_total // 2
    right = pad_total - left
    return torch.nn.functional.pad(waveform, (left, right))


def preprocess_waveform(
    waveform: np.ndarray | torch.Tensor,
    source_rate: int,
    sample_rate: int,
    clip_seconds: float,
) -> tuple[torch.Tensor, dict[str, float]]:
    if isinstance(waveform, torch.Tensor):
        tensor = waveform.detach().to(dtype=torch.float32)
    else:
        tensor = torch.from_numpy(np.asarray(waveform, dtype=np.float32))
    if tensor.ndim > 1:
        if tensor.shape[0] <= 8:
            tensor = tensor.mean(dim=0)
        else:
            tensor = tensor.mean(dim=-1)
    tensor = tensor.reshape(-1)
    tensor = resample_if_needed(tensor, source_rate=source_rate, target_rate=sample_rate)
    raw_dbfs = rms_dbfs(tensor) if tensor.numel() > 0 else -120.0
    tensor = normalize_audio(tensor)
    tensor = trim_and_pad(tensor, int(sample_rate * clip_seconds))
    stats = {
        "source_sample_rate": float(source_rate),
        "sample_rate": float(sample_rate),
        "rms_dbfs": raw_dbfs,
        "duration_seconds": float(tensor.shape[-1] / sample_rate),
    }
    return tensor, stats


def load_and_preprocess(
    path: str | Path,
    sample_rate: int,
    clip_seconds: float,
) -> tuple[torch.Tensor, dict[str, float]]:
    waveform_np, source_rate = read_wav(path)
    return preprocess_waveform(
        waveform=waveform_np,
        source_rate=source_rate,
        sample_rate=sample_rate,
        clip_seconds=clip_seconds,
    )
