from __future__ import annotations

import argparse
import json
from time import perf_counter

import torch

from iruka_cnn.common.config import load_yaml
from iruka_cnn.common.device import resolve_device
from iruka_cnn.common.labels import LabelEncoder, PhraseDictionary
from iruka_cnn.common.utils import set_global_seed
from iruka_cnn.receiver.features import LogMelExtractor
from iruka_cnn.receiver.model import SpectrogramCNN
from iruka_cnn.training.augment import FeatureAugmentor, WaveformAugmentor
from iruka_cnn.training.datagen import generate_dataset
from iruka_cnn.training.dataset import FeatureDataset, WaveformDataset, make_dataloader, resolve_num_workers
from iruka_cnn.training.feature_cache import ensure_feature_cache


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="先頭 train step の速度を計測します。")
    parser.add_argument("--config", default="configs/baseline.yaml", help="設定ファイルパス")
    parser.add_argument("--steps", type=int, default=20, help="計測する train step 数")
    parser.add_argument("--regen-dataset", action="store_true", help="データセットを再生成してから計測する")
    return parser


def build_feature_extractor(config: dict, device: torch.device) -> LogMelExtractor:
    return LogMelExtractor(
        sample_rate=config["audio"]["sample_rate"],
        n_fft=config["features"]["n_fft"],
        hop_length=config["features"]["hop_length"],
        n_mels=config["features"]["n_mels"],
        f_min=config["features"]["f_min"],
        f_max=config["features"]["f_max"],
        top_db=config["features"]["top_db"],
    ).to(device)


def main() -> None:
    args = build_parser().parse_args()
    config = load_yaml(args.config)
    set_global_seed(int(config["experiment"]["seed"]))

    if args.regen_dataset:
        generate_dataset(config)
    elif bool(config.get("dataset", {}).get("cache_features", True)):
        ensure_feature_cache(config, splits=("train",))

    dictionary = PhraseDictionary.from_yaml(config["dictionary"]["phrases_path"])
    encoder = LabelEncoder(dictionary.labels())
    device = resolve_device(config["training"].get("device", "auto"))
    cache_features = bool(config.get("dataset", {}).get("cache_features", True))
    augmentation_mode = str(config.get("augmentation", {}).get("mode", "feature")).lower()
    batch_size = int(config["training"]["batch_size"])

    if cache_features:
        dataset = FeatureDataset(data_root="data", split="train", dictionary=dictionary)
        feature_extractor = None
    else:
        dataset = WaveformDataset(
            data_root="data",
            split="train",
            dictionary=dictionary,
            sample_rate=config["audio"]["sample_rate"],
            clip_seconds=config["audio"]["clip_seconds"],
            augmentor=None,
        )
        feature_extractor = build_feature_extractor(config, device)

    loader = make_dataloader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=config["training"].get("num_workers", "auto"),
        persistent_workers=bool(config["training"].get("persistent_workers", True)),
        prefetch_factor=int(config["training"].get("prefetch_factor", 4)),
    )

    model = SpectrogramCNN(
        num_classes=encoder.num_classes,
        embedding_dim=int(config["training"]["embedding_dim"]),
    ).to(device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(config["training"]["learning_rate"]),
        weight_decay=float(config["training"]["weight_decay"]),
    )
    criterion = torch.nn.CrossEntropyLoss()

    feature_augmentor = None
    silence_index = encoder.encode("silence")
    if cache_features and bool(config["augmentation"].get("enable", True)) and augmentation_mode == "feature":
        feature_augmentor = FeatureAugmentor(config["augmentation"])

    iterator = iter(loader)
    fetch_times: list[float] = []
    step_times: list[float] = []

    for _ in range(args.steps):
        fetch_start = perf_counter()
        batch_inputs, targets = next(iterator)
        fetch_times.append(perf_counter() - fetch_start)

        step_start = perf_counter()
        model.train()
        optimizer.zero_grad(set_to_none=True)

        if feature_extractor is None:
            features = batch_inputs.to(device)
        else:
            features = feature_extractor(batch_inputs.to(device))
        labels = targets.to(device)
        if feature_augmentor is not None:
            features = feature_augmentor(features, labels=labels, silence_index=silence_index)

        logits, _ = model(features)
        loss = criterion(logits, labels)
        loss.backward()
        optimizer.step()

        if device.type == "mps":
            torch.mps.synchronize()
        elif device.type == "cuda":
            torch.cuda.synchronize(device)

        step_times.append(perf_counter() - step_start)

    payload = {
        "config": args.config,
        "device": str(device),
        "cache_features": cache_features,
        "augmentation_mode": augmentation_mode,
        "steps": args.steps,
        "batch_size": batch_size,
        "resolved_num_workers": resolve_num_workers(config["training"].get("num_workers", "auto")),
        "mean_fetch_sec": sum(fetch_times) / len(fetch_times),
        "mean_train_step_sec": sum(step_times) / len(step_times),
        "first_fetch_sec": fetch_times[0],
        "first_train_step_sec": step_times[0],
        "last_fetch_sec": fetch_times[-1],
        "last_train_step_sec": step_times[-1],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
