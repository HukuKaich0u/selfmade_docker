from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from iruka_cnn.common.config import load_yaml
from iruka_cnn.common.device import resolve_device
from iruka_cnn.common.io import write_json
from iruka_cnn.common.labels import LabelEncoder, PhraseDictionary
from iruka_cnn.receiver.features import LogMelExtractor
from iruka_cnn.receiver.model import SpectrogramCNN
from iruka_cnn.training.augment import WaveformAugmentor
from iruka_cnn.training.dataset import FeatureDataset, WaveformDataset, make_dataloader
from iruka_cnn.training.feature_cache import ensure_feature_cache
from iruka_cnn.training.metrics import apply_thresholds, render_confusion_matrix, summarize_metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="学習済みモデルを評価します。")
    parser.add_argument("--config", default="configs/baseline.yaml", help="設定ファイルパス")
    parser.add_argument("--checkpoint", default="artifacts/models/best.pt", help="学習済みモデルパス")
    parser.add_argument("--split", default="test", choices=["train", "val", "test"], help="評価対象split")
    parser.add_argument(
        "--condition",
        default=None,
        choices=["clean", "degraded"],
        help="評価条件。未指定時はconfigのevaluation.conditionを使用",
    )
    return parser


def _build_feature_extractor(config: dict) -> LogMelExtractor:
    return LogMelExtractor(
        sample_rate=config["audio"]["sample_rate"],
        n_fft=config["features"]["n_fft"],
        hop_length=config["features"]["hop_length"],
        n_mels=config["features"]["n_mels"],
        f_min=config["features"]["f_min"],
        f_max=config["features"]["f_max"],
        top_db=config["features"]["top_db"],
    )


def main() -> None:
    args = build_parser().parse_args()
    config = load_yaml(args.config)
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)
    config = checkpoint.get("config", config)
    dictionary = PhraseDictionary.from_yaml(config["dictionary"]["phrases_path"])
    encoder = LabelEncoder(dictionary.labels())
    device = resolve_device(config["training"].get("device", "auto"))
    condition = args.condition or config["evaluation"].get("condition", "clean")
    use_feature_cache = bool(config.get("dataset", {}).get("cache_features", True))
    if condition == "clean" and use_feature_cache:
        ensure_feature_cache(config, splits=(args.split,))
        dataset = FeatureDataset(
            data_root="data",
            split=args.split,
            dictionary=dictionary,
        )
    else:
        dataset = WaveformDataset(
            data_root="data",
            split=args.split,
            dictionary=dictionary,
            sample_rate=config["audio"]["sample_rate"],
            clip_seconds=config["audio"]["clip_seconds"],
            augmentor=None,
        )
    loader = make_dataloader(
        dataset,
        batch_size=int(config["training"]["batch_size"]),
        shuffle=False,
        num_workers=config["training"].get("num_workers", "auto"),
        persistent_workers=bool(config["training"].get("persistent_workers", True)),
        prefetch_factor=int(config["training"].get("prefetch_factor", 4)),
    )
    feature_extractor = None if condition == "clean" and use_feature_cache else _build_feature_extractor(config).to(device)
    model = SpectrogramCNN(
        num_classes=encoder.num_classes,
        embedding_dim=int(config["training"]["embedding_dim"]),
    ).to(device)
    model.load_state_dict(checkpoint["model_state"])
    model.eval()

    degrader = None
    if condition == "degraded":
        degrader = WaveformAugmentor(
            sample_rate=config["audio"]["sample_rate"],
            clip_seconds=config["audio"]["clip_seconds"],
            config=config["augmentation"],
        )

    y_true: list[str] = []
    top1_labels: list[str] = []
    top1_scores: list[float] = []
    top2_scores: list[float] = []

    with torch.inference_mode():
        for batch_inputs, target in loader:
            if feature_extractor is None:
                features = batch_inputs.to(device)
            else:
                waveforms = batch_inputs
                if degrader is not None:
                    waveforms = torch.stack([degrader.degrade(item) for item in waveforms], dim=0)
                features = feature_extractor(waveforms.to(device))
            logits, _ = model(features)
            probs = torch.softmax(logits, dim=-1)
            scores, indices = torch.topk(probs, k=min(2, probs.shape[-1]), dim=-1)
            y_true.extend(encoder.labels[int(item)] for item in target.tolist())
            top1_labels.extend(encoder.labels[int(item)] for item in indices[:, 0].cpu().tolist())
            top1_scores.extend(float(item) for item in scores[:, 0].cpu().tolist())
            if scores.shape[-1] == 1:
                top2_scores.extend(0.0 for _ in range(scores.shape[0]))
            else:
                top2_scores.extend(float(item) for item in scores[:, 1].cpu().tolist())

    thresholds = checkpoint.get("thresholds", config["inference"])
    y_pred = apply_thresholds(
        top1_labels,
        top1_scores,
        top2_scores,
        confidence_threshold=float(thresholds["confidence_threshold"]),
        margin_threshold=float(thresholds["margin_threshold"]),
    )
    metrics = summarize_metrics(y_true, y_pred, encoder.labels)
    reports_dir = Path(config["experiment"]["output_dir"]) / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{args.split}_{condition}_report.json"
    payload = {
        "split": args.split,
        "condition": condition,
        "thresholds": thresholds,
        "metrics": metrics,
    }
    write_json(report_path, payload)

    confusion_path = None
    if bool(config["evaluation"].get("render_confusion_matrix", True)):
        confusion_path = render_confusion_matrix(
            y_true=y_true,
            y_pred=y_pred,
            labels=encoder.labels,
            output_path=reports_dir / f"{args.split}_{condition}_confusion.png",
            title=f"{args.split} / {condition}",
        )
    print(
        json.dumps(
            {
                "report_path": str(report_path),
                "confusion_matrix_path": str(confusion_path) if confusion_path else None,
                "accuracy": metrics["accuracy"],
                "macro_f1": metrics["macro_f1"],
                "unknown_false_accept_rate": metrics["unknown_false_accept_rate"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
