from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import torch
from tqdm.auto import tqdm

from iruka_cnn.common.device import resolve_device
from iruka_cnn.common.io import write_array
from iruka_cnn.receiver.features import LogMelExtractor
from iruka_cnn.receiver.preprocess import load_and_preprocess
from iruka_cnn.training.dataset import AudioRecord, load_records, save_records


def feature_path_from_audio_path(audio_path: str | Path) -> str:
    return str(Path(audio_path).with_suffix(".npy"))


def ensure_feature_cache(
    config: dict,
    data_root: str | Path = "data",
    splits: Iterable[str] = ("train", "val", "test"),
) -> dict[str, dict[str, int]]:
    if not bool(config.get("dataset", {}).get("cache_features", True)):
        return {}
    cache_dtype = _resolve_cache_dtype(config.get("dataset", {}).get("cache_dtype", "float16"))
    device = resolve_device(config["training"].get("device", "auto"))
    extractor = LogMelExtractor(
        sample_rate=config["audio"]["sample_rate"],
        n_fft=config["features"]["n_fft"],
        hop_length=config["features"]["hop_length"],
        n_mels=config["features"]["n_mels"],
        f_min=config["features"]["f_min"],
        f_max=config["features"]["f_max"],
        top_db=config["features"]["top_db"],
    ).to(device)
    batch_size = int(config["training"].get("batch_size", 32))

    summaries: dict[str, dict[str, int]] = {}
    for split in splits:
        records = load_records(data_root, split)
        if not records:
            summaries[split] = {"cached": 0, "skipped": 0, "missing": 0}
            continue
        summary = _cache_split_features(
            records=records,
            split=split,
            sample_rate=int(config["audio"]["sample_rate"]),
            clip_seconds=float(config["audio"]["clip_seconds"]),
            extractor=extractor,
            device=device,
            batch_size=batch_size,
            cache_dtype=cache_dtype,
        )
        save_records(data_root, split, records)
        summaries[split] = summary
    return summaries


def _cache_split_features(
    records: list[AudioRecord],
    split: str,
    sample_rate: int,
    clip_seconds: float,
    extractor: LogMelExtractor,
    device: torch.device,
    batch_size: int,
    cache_dtype: np.dtype,
) -> dict[str, int]:
    cached = 0
    skipped = 0
    pending_waveforms: list[torch.Tensor] = []
    pending_records: list[AudioRecord] = []
    progress = tqdm(total=len(records), desc=f"Cache {split}", unit="feat", dynamic_ncols=True)

    def flush_pending() -> None:
        nonlocal cached
        if not pending_records:
            return
        batch = torch.stack(pending_waveforms, dim=0).to(device)
        with torch.inference_mode():
            features = extractor(batch).cpu()
        for record, feature in zip(pending_records, features, strict=True):
            if record.feature_path is None:
                raise RuntimeError(f"feature_path が未設定です: {record.path}")
            array = feature.to(dtype=torch.float32).numpy().astype(cache_dtype, copy=False)
            write_array(record.feature_path, array)
            cached += 1
        pending_waveforms.clear()
        pending_records.clear()

    for record in records:
        if record.feature_path is None:
            record.feature_path = feature_path_from_audio_path(record.path)
        feature_path = Path(record.feature_path)
        if feature_path.exists():
            skipped += 1
            progress.update(1)
            progress.set_postfix(cached=cached, skipped=skipped)
            continue
        waveform, _ = load_and_preprocess(record.path, sample_rate, clip_seconds)
        pending_waveforms.append(waveform)
        pending_records.append(record)
        if len(pending_records) >= batch_size:
            flush_pending()
        progress.update(1)
        progress.set_postfix(cached=cached, skipped=skipped)

    flush_pending()
    progress.close()
    return {"cached": cached, "skipped": skipped, "missing": 0}


def _resolve_cache_dtype(dtype_name: str) -> np.dtype:
    if str(dtype_name).lower() == "float32":
        return np.float32
    return np.float16
