from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, Dataset

from iruka_cnn.common.io import read_array
from iruka_cnn.common.labels import LabelEncoder, PhraseDictionary
from iruka_cnn.receiver.preprocess import load_and_preprocess
from iruka_cnn.training.augment import WaveformAugmentor


@dataclass
class AudioRecord:
    path: str
    label: str
    split: str
    seed: int
    feature_path: str | None = None


def metadata_path(data_root: str | Path, split: str) -> Path:
    return Path(data_root) / split / "metadata.jsonl"


def load_records(data_root: str | Path, split: str) -> list[AudioRecord]:
    records: list[AudioRecord] = []
    path = metadata_path(data_root, split)
    if not path.exists():
        return records
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            payload = json.loads(line)
            records.append(AudioRecord(**payload))
    return records


def save_records(data_root: str | Path, split: str, records: list[AudioRecord]) -> Path:
    path = metadata_path(data_root, split)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(
                json.dumps(
                    {
                        "path": record.path,
                        "label": record.label,
                        "split": record.split,
                        "seed": record.seed,
                        "feature_path": record.feature_path,
                    },
                    ensure_ascii=False,
                )
            )
            handle.write("\n")
    return path


class WaveformDataset(Dataset[tuple[torch.Tensor, torch.Tensor]]):
    def __init__(
        self,
        data_root: str | Path,
        split: str,
        dictionary: PhraseDictionary,
        sample_rate: int,
        clip_seconds: float,
        augmentor: WaveformAugmentor | None = None,
    ) -> None:
        self.records = load_records(data_root, split)
        self.sample_rate = sample_rate
        self.clip_seconds = clip_seconds
        self.augmentor = augmentor
        self.encoder = LabelEncoder(dictionary.labels())

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        record = self.records[index]
        waveform, _ = load_and_preprocess(record.path, self.sample_rate, self.clip_seconds)
        if self.augmentor is not None and record.label not in {"silence"}:
            waveform = self.augmentor(waveform)
        label = torch.tensor(self.encoder.encode(record.label), dtype=torch.long)
        return waveform, label


class FeatureDataset(Dataset[tuple[torch.Tensor, torch.Tensor]]):
    def __init__(
        self,
        data_root: str | Path,
        split: str,
        dictionary: PhraseDictionary,
    ) -> None:
        self.records = load_records(data_root, split)
        self.encoder = LabelEncoder(dictionary.labels())

    def __len__(self) -> int:
        return len(self.records)

    def __getitem__(self, index: int) -> tuple[torch.Tensor, torch.Tensor]:
        record = self.records[index]
        if record.feature_path is None:
            raise RuntimeError(f"feature_path が未設定です: {record.path}")
        feature = torch.from_numpy(read_array(record.feature_path).astype(np.float32, copy=False))
        label = torch.tensor(self.encoder.encode(record.label), dtype=torch.long)
        return feature, label


def resolve_num_workers(value: str | int | None) -> int:
    if value is None:
        return 0
    if isinstance(value, str):
        if value.lower() == "auto":
            cpu_count = os.cpu_count() or 1
            return max(1, min(8, cpu_count - 1))
        return max(0, int(value))
    return max(0, int(value))


def make_dataloader(
    dataset: Dataset,
    batch_size: int,
    shuffle: bool,
    num_workers: str | int | None,
    persistent_workers: bool = False,
    prefetch_factor: int = 2,
) -> DataLoader:
    resolved_workers = resolve_num_workers(num_workers)
    kwargs: dict[str, object] = {
        "batch_size": batch_size,
        "shuffle": shuffle,
        "num_workers": resolved_workers,
        "drop_last": False,
    }
    if resolved_workers > 0:
        kwargs["persistent_workers"] = persistent_workers
        kwargs["prefetch_factor"] = prefetch_factor
    return DataLoader(dataset, **kwargs)
