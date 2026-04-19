from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from time import perf_counter

import torch
from tqdm.auto import tqdm

from iruka_cnn.common.config import load_yaml
from iruka_cnn.common.device import resolve_device
from iruka_cnn.common.io import ensure_parent
from iruka_cnn.common.labels import LabelEncoder, PhraseDictionary
from iruka_cnn.common.utils import set_global_seed, write_text_json
from iruka_cnn.receiver.features import LogMelExtractor
from iruka_cnn.receiver.model import SpectrogramCNN
from iruka_cnn.training.augment import FeatureAugmentor, WaveformAugmentor
from iruka_cnn.training.datagen import generate_dataset
from iruka_cnn.training.dataset import (
    FeatureDataset,
    WaveformDataset,
    load_records,
    make_dataloader,
    metadata_path,
    resolve_num_workers,
)
from iruka_cnn.training.feature_cache import ensure_feature_cache
from iruka_cnn.training.metrics import apply_thresholds, optimize_thresholds, summarize_metrics
from iruka_cnn.training.prototypes import build_class_prototypes
from iruka_cnn.training.visualization import maybe_create_train_plotter


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="イルカ風音声分類モデルを学習します。")
    parser.add_argument("--config", default="configs/baseline.yaml", help="設定ファイルパス")
    parser.add_argument("--regen-dataset", action="store_true", help="学習データを再生成する")
    return parser


def _log(message: str) -> None:
    tqdm.write(message)


def _build_feature_extractor(config: dict, device: torch.device) -> LogMelExtractor:
    return LogMelExtractor(
        sample_rate=config["audio"]["sample_rate"],
        n_fft=config["features"]["n_fft"],
        hop_length=config["features"]["hop_length"],
        n_mels=config["features"]["n_mels"],
        f_min=config["features"]["f_min"],
        f_max=config["features"]["f_max"],
        top_db=config["features"]["top_db"],
    ).to(device)


def _ensure_dataset(config: dict, regen: bool) -> str:
    if regen or not metadata_path("data", "train").exists():
        _log("[data] 学習データを生成します。")
        generate_dataset(config)
        return "generated"
    _log("[data] 既存の学習データを再利用します。")
    if bool(config.get("dataset", {}).get("cache_features", True)):
        cache_summary = ensure_feature_cache(config, splits=("train", "val", "test"))
        for split, split_result in cache_summary.items():
            _log(
                "[cache] split={split} cached={cached} skipped={skipped}".format(
                    split=split,
                    cached=split_result["cached"],
                    skipped=split_result["skipped"],
                )
            )
    return "reused"


def _compute_class_weights(records: list, encoder: LabelEncoder) -> torch.Tensor:
    counts = Counter(record.label for record in records)
    total = sum(counts.values())
    weights = []
    for label in encoder.labels:
        count = counts.get(label, 1)
        weights.append(total / (len(encoder.labels) * count))
    return torch.tensor(weights, dtype=torch.float32)


def _format_counter(counter: Counter) -> str:
    ordered = {key: counter[key] for key in sorted(counter)}
    return json.dumps(ordered, ensure_ascii=False, sort_keys=False)


def _summarize_batch_predictions(logits: torch.Tensor, labels: torch.Tensor) -> dict[str, float | int]:
    with torch.no_grad():
        probs = torch.softmax(logits.detach(), dim=-1)
        scores, indices = torch.topk(probs, k=min(2, probs.shape[-1]), dim=-1)
        top1_scores = scores[:, 0]
        if scores.shape[-1] == 1:
            margins = top1_scores
        else:
            margins = top1_scores - scores[:, 1]
        correct = int((indices[:, 0] == labels).sum().item())
        size = int(labels.shape[0])
        top1_sum = float(top1_scores.sum().item())
        margin_sum = float(margins.sum().item())
    return {
        "correct": correct,
        "size": size,
        "batch_acc": correct / max(size, 1),
        "batch_top1": top1_sum / max(size, 1),
        "batch_margin": margin_sum / max(size, 1),
        "top1_sum": top1_sum,
        "margin_sum": margin_sum,
    }


def _forward_pass(
    model: SpectrogramCNN,
    batch_inputs: torch.Tensor,
    labels: torch.Tensor,
    device: torch.device,
    feature_extractor: LogMelExtractor | None = None,
    feature_augmentor: FeatureAugmentor | None = None,
    silence_index: int | None = None,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    if feature_extractor is None:
        features = batch_inputs.to(device)
    else:
        features = feature_extractor(batch_inputs.to(device))
    labels = labels.to(device)
    if feature_augmentor is not None:
        features = feature_augmentor(features, labels=labels, silence_index=silence_index)
    logits, embeddings = model(features)
    return logits, embeddings, labels


def _collect_predictions(
    model: SpectrogramCNN,
    loader,
    device: torch.device,
    labels: list[str],
    include_embeddings: bool = False,
    degrader: WaveformAugmentor | None = None,
    desc: str | None = None,
    feature_extractor=None,
    criterion: torch.nn.Module | None = None,
) -> dict:
    model.eval()
    all_true: list[str] = []
    top1_labels: list[str] = []
    top1_scores: list[float] = []
    top2_scores: list[float] = []
    embeddings_list: list[torch.Tensor] = []
    seen = 0
    raw_top1_correct = 0
    top1_score_sum = 0.0
    margin_sum = 0.0
    loss_sum = 0.0
    loss_steps = 0
    progress = (
        tqdm(
            loader,
            desc=desc,
            unit="batch",
            leave=False,
            dynamic_ncols=True,
            total=len(loader),
        )
        if desc is not None
        else None
    )
    iterator = progress if progress is not None else loader
    with torch.inference_mode():
        for inputs, target in iterator:
            if feature_extractor is None:
                features = inputs.to(device)
                target_device = target.to(device)
            else:
                waveforms = inputs
                if degrader is not None:
                    waveforms = torch.stack([degrader.degrade(waveform) for waveform in waveforms], dim=0)
                features = feature_extractor(waveforms.to(device))
                target_device = target.to(device)
            logits, embeddings = model(features)
            if criterion is not None:
                loss_sum += float(criterion(logits, target_device).item())
                loss_steps += 1
            probs = torch.softmax(logits, dim=-1)
            scores, indices = torch.topk(probs, k=min(2, probs.shape[-1]), dim=-1)
            all_true.extend(labels[int(item)] for item in target.tolist())
            top1_labels.extend(labels[int(idx)] for idx in indices[:, 0].cpu().tolist())
            batch_top1_scores = scores[:, 0].cpu()
            top1_scores.extend(float(value) for value in batch_top1_scores.tolist())
            if scores.shape[-1] == 1:
                top2_scores.extend(0.0 for _ in range(scores.shape[0]))
                batch_margin = batch_top1_scores
            else:
                batch_top2_scores = scores[:, 1].cpu()
                top2_scores.extend(float(value) for value in batch_top2_scores.tolist())
                batch_margin = batch_top1_scores - batch_top2_scores
            if include_embeddings:
                embeddings_list.append(embeddings.cpu())
            seen += int(target.shape[0])
            raw_top1_correct += int((indices[:, 0].cpu() == target).sum().item())
            top1_score_sum += float(batch_top1_scores.sum().item())
            margin_sum += float(batch_margin.sum().item())
            if progress is not None:
                progress.set_postfix(
                    items=seen,
                    raw_acc=f"{raw_top1_correct / max(seen, 1):.4f}",
                    avg_top1=f"{top1_score_sum / max(seen, 1):.4f}",
                    avg_margin=f"{margin_sum / max(seen, 1):.4f}",
                )
    if progress is not None:
        progress.close()
    result = {
        "y_true": all_true,
        "top1_labels": top1_labels,
        "top1_scores": top1_scores,
        "top2_scores": top2_scores,
        "avg_loss": loss_sum / max(loss_steps, 1) if criterion is not None else None,
        "raw_top1_accuracy": raw_top1_correct / max(seen, 1),
        "avg_top1_score": top1_score_sum / max(seen, 1),
        "avg_margin": margin_sum / max(seen, 1),
    }
    if include_embeddings:
        result["embeddings"] = torch.cat(embeddings_list, dim=0) if embeddings_list else torch.empty(0)
    return result


def main() -> None:
    args = build_parser().parse_args()
    config = load_yaml(args.config)
    set_global_seed(int(config["experiment"]["seed"]))
    dataset_status = _ensure_dataset(config, regen=args.regen_dataset)

    dictionary = PhraseDictionary.from_yaml(config["dictionary"]["phrases_path"])
    encoder = LabelEncoder(dictionary.labels())
    device = resolve_device(config["training"].get("device", "auto"))
    output_dir = Path(config["experiment"]["output_dir"])
    model_dir = output_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    cache_features = bool(config.get("dataset", {}).get("cache_features", True))
    augmentation_mode = str(config.get("augmentation", {}).get("mode", "feature")).lower()

    if cache_features:
        train_dataset = FeatureDataset(data_root="data", split="train", dictionary=dictionary)
        train_clean_dataset = FeatureDataset(data_root="data", split="train", dictionary=dictionary)
        val_dataset = FeatureDataset(data_root="data", split="val", dictionary=dictionary)
    else:
        waveform_augmentor = WaveformAugmentor(
            sample_rate=config["audio"]["sample_rate"],
            clip_seconds=config["audio"]["clip_seconds"],
            config=config["augmentation"],
        ) if config["augmentation"].get("enable", True) else None
        train_dataset = WaveformDataset(
            data_root="data",
            split="train",
            dictionary=dictionary,
            sample_rate=config["audio"]["sample_rate"],
            clip_seconds=config["audio"]["clip_seconds"],
            augmentor=waveform_augmentor,
        )
        train_clean_dataset = WaveformDataset(
            data_root="data",
            split="train",
            dictionary=dictionary,
            sample_rate=config["audio"]["sample_rate"],
            clip_seconds=config["audio"]["clip_seconds"],
            augmentor=None,
        )
        val_dataset = WaveformDataset(
            data_root="data",
            split="val",
            dictionary=dictionary,
            sample_rate=config["audio"]["sample_rate"],
            clip_seconds=config["audio"]["clip_seconds"],
            augmentor=None,
        )

    train_records = load_records("data", "train")
    val_records = load_records("data", "val")
    batch_size = int(config["training"]["batch_size"])
    resolved_workers = resolve_num_workers(config["training"].get("num_workers", "auto"))
    persistent_workers = bool(config["training"].get("persistent_workers", True))
    prefetch_factor = int(config["training"].get("prefetch_factor", 4))
    train_loader = make_dataloader(
        train_dataset,
        batch_size=batch_size,
        shuffle=True,
        num_workers=resolved_workers,
        persistent_workers=persistent_workers,
        prefetch_factor=prefetch_factor,
    )
    train_clean_loader = make_dataloader(
        train_clean_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=resolved_workers,
        persistent_workers=persistent_workers,
        prefetch_factor=prefetch_factor,
    )
    val_loader = make_dataloader(
        val_dataset,
        batch_size=batch_size,
        shuffle=False,
        num_workers=resolved_workers,
        persistent_workers=persistent_workers,
        prefetch_factor=prefetch_factor,
    )

    model = SpectrogramCNN(
        num_classes=encoder.num_classes,
        embedding_dim=int(config["training"]["embedding_dim"]),
    ).to(device)
    feature_extractor = None if cache_features else _build_feature_extractor(config, device)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=float(config["training"]["learning_rate"]),
        weight_decay=float(config["training"]["weight_decay"]),
    )
    weight_tensor = None
    if bool(config["training"].get("class_weighting", True)):
        weight_tensor = _compute_class_weights(train_records, encoder).to(device)
    criterion = torch.nn.CrossEntropyLoss(weight=weight_tensor)

    train_counter = Counter(record.label for record in train_records)
    val_counter = Counter(record.label for record in val_records)
    _log(
        "[train] start experiment={name} device={device} seed={seed} dataset={dataset_status}".format(
            name=config["experiment"]["name"],
            device=device,
            seed=config["experiment"]["seed"],
            dataset_status=dataset_status,
        )
    )
    _log(
        "[train] classes={classes} train_samples={train_samples} val_samples={val_samples} batch_size={batch_size} epochs={epochs}".format(
            classes=encoder.num_classes,
            train_samples=len(train_dataset),
            val_samples=len(val_dataset),
            batch_size=batch_size,
            epochs=config["training"]["epochs"],
        )
    )
    _log(f"[train] train_label_counts={_format_counter(train_counter)}")
    _log(f"[train] val_label_counts={_format_counter(val_counter)}")
    if weight_tensor is not None:
        weight_summary = {
            label: round(float(weight), 4)
            for label, weight in zip(encoder.labels, weight_tensor.detach().cpu().tolist(), strict=True)
        }
        _log(f"[train] class_weights={json.dumps(weight_summary, ensure_ascii=False)}")
    _log(
        "[train] loaders: cache_features={cache_features} augmentation_mode={augmentation_mode} resolved_num_workers={workers} persistent_workers={persistent_workers} prefetch_factor={prefetch}".format(
            cache_features=cache_features,
            augmentation_mode=augmentation_mode,
            workers=resolved_workers,
            persistent_workers=persistent_workers if resolved_workers > 0 else False,
            prefetch=prefetch_factor if resolved_workers > 0 else 0,
        )
    )

    best_macro_f1 = -1.0
    best_checkpoint_path = model_dir / "best.pt"
    history: list[dict] = []
    best_thresholds = config.get("inference", {}).copy()
    total_epochs = int(config["training"]["epochs"])
    redraw_every_batches = 10
    global_batch_step = 0
    epoch_progress = tqdm(range(1, total_epochs + 1), desc="Epochs", unit="epoch", dynamic_ncols=True)
    feature_augmentor = None
    if cache_features and bool(config["augmentation"].get("enable", True)) and augmentation_mode == "feature":
        feature_augmentor = FeatureAugmentor(config["augmentation"])
    silence_index = encoder.encode("silence")
    plotter = maybe_create_train_plotter(model_dir / "training_live.png", warn_callback=_log)
    if plotter is not None:
        _log(
            "[plot] live plot enabled: path={path} backend={backend} window={window}".format(
                path=model_dir / "training_live.png",
                backend=plotter.backend,
                window="on" if plotter.show_window else "off",
            )
        )

    try:
        for epoch in epoch_progress:
            epoch_start = perf_counter()
            model.train()
            train_loss = 0.0
            train_steps = 0
            train_correct = 0
            train_seen = 0
            train_top1_sum = 0.0
            train_margin_sum = 0.0
            train_progress = tqdm(
                train_loader,
                desc=f"Train {epoch}/{total_epochs}",
                unit="batch",
                leave=False,
                dynamic_ncols=True,
                total=len(train_loader),
            )
            for batch_inputs, target in train_progress:
                optimizer.zero_grad(set_to_none=True)
                logits, _, labels = _forward_pass(
                    model,
                    batch_inputs,
                    target,
                    device,
                    feature_extractor=feature_extractor,
                    feature_augmentor=feature_augmentor,
                    silence_index=silence_index,
                )
                loss = criterion(logits, labels)
                loss.backward()
                optimizer.step()
                batch_summary = _summarize_batch_predictions(logits, labels)
                train_loss += float(loss.item())
                train_steps += 1
                global_batch_step += 1
                train_correct += int(batch_summary["correct"])
                train_seen += int(batch_summary["size"])
                train_top1_sum += float(batch_summary["top1_sum"])
                train_margin_sum += float(batch_summary["margin_sum"])
                if plotter is not None:
                    plotter.update_batch(
                        global_step=global_batch_step,
                        loss=float(loss.item()),
                        accuracy=float(batch_summary["batch_acc"]),
                    )
                    if train_steps % redraw_every_batches == 0 or train_steps == len(train_loader):
                        plotter.redraw()
                train_progress.set_postfix(
                    batch_loss=f"{loss.item():.4f}",
                    avg_loss=f"{train_loss / max(train_steps, 1):.4f}",
                    batch_acc=f"{float(batch_summary['batch_acc']):.4f}",
                    avg_acc=f"{train_correct / max(train_seen, 1):.4f}",
                    avg_conf=f"{train_top1_sum / max(train_seen, 1):.4f}",
                    avg_margin=f"{train_margin_sum / max(train_seen, 1):.4f}",
                    seen=train_seen,
                    lr=f"{optimizer.param_groups[0]['lr']:.2e}",
                )
            train_progress.close()

            val_predictions = _collect_predictions(
                model=model,
                loader=val_loader,
                device=device,
                labels=encoder.labels,
                desc=f"Val {epoch}/{total_epochs}",
                feature_extractor=feature_extractor,
                criterion=criterion,
            )
            thresholds = optimize_thresholds(
                y_true=val_predictions["y_true"],
                top1_labels=val_predictions["top1_labels"],
                top1_scores=val_predictions["top1_scores"],
                top2_scores=val_predictions["top2_scores"],
                labels=encoder.labels,
            )
            val_pred = apply_thresholds(
                val_predictions["top1_labels"],
                val_predictions["top1_scores"],
                val_predictions["top2_scores"],
                confidence_threshold=float(thresholds["confidence_threshold"]),
                margin_threshold=float(thresholds["margin_threshold"]),
            )
            val_metrics = summarize_metrics(val_predictions["y_true"], val_pred, encoder.labels)
            epoch_result = {
                "epoch": epoch,
                "train_loss": train_loss / max(train_steps, 1),
                "train_accuracy": train_correct / max(train_seen, 1),
                "train_avg_top1": train_top1_sum / max(train_seen, 1),
                "train_avg_margin": train_margin_sum / max(train_seen, 1),
                "val_loss": float(val_predictions["avg_loss"] or 0.0),
                "val_accuracy": val_metrics["accuracy"],
                "val_macro_f1": val_metrics["macro_f1"],
                "val_raw_top1_accuracy": val_predictions["raw_top1_accuracy"],
                "val_avg_top1": val_predictions["avg_top1_score"],
                "val_avg_margin": val_predictions["avg_margin"],
                "confidence_threshold": thresholds["confidence_threshold"],
                "margin_threshold": thresholds["margin_threshold"],
            }
            history.append(epoch_result)
            if plotter is not None:
                plotter.update_epoch(
                    epoch=epoch,
                    train_loss=epoch_result["train_loss"],
                    val_loss=epoch_result["val_loss"],
                    train_accuracy=epoch_result["train_accuracy"],
                    val_accuracy=epoch_result["val_accuracy"],
                    val_macro_f1=epoch_result["val_macro_f1"],
                )
                plotter.redraw()
            if val_metrics["macro_f1"] > best_macro_f1:
                best_macro_f1 = val_metrics["macro_f1"]
                best_thresholds = thresholds
                checkpoint = {
                    "config": config,
                    "label_vocab": dictionary.to_label_vocab(),
                    "model_state": model.state_dict(),
                    "thresholds": {
                        "confidence_threshold": float(best_thresholds["confidence_threshold"]),
                        "margin_threshold": float(best_thresholds["margin_threshold"]),
                        "top_k": int(config["inference"]["top_k"]),
                    },
                    "metrics": {
                        "val_accuracy": float(val_metrics["accuracy"]),
                        "val_macro_f1": float(val_metrics["macro_f1"]),
                    },
                }
                torch.save(checkpoint, best_checkpoint_path)
                _log(
                    "[checkpoint] epoch={epoch} best 更新: val_macro_f1={val_macro_f1:.4f} path={path}".format(
                        epoch=epoch,
                        val_macro_f1=val_metrics["macro_f1"],
                        path=best_checkpoint_path,
                    )
                )
            elapsed = perf_counter() - epoch_start
            epoch_progress.set_postfix(
                train_loss=f"{epoch_result['train_loss']:.4f}",
                val_loss=f"{epoch_result['val_loss']:.4f}",
                train_acc=f"{epoch_result['train_accuracy']:.4f}",
                val_acc=f"{epoch_result['val_accuracy']:.4f}",
                val_f1=f"{epoch_result['val_macro_f1']:.4f}",
                best_f1=f"{best_macro_f1:.4f}",
            )
            _log(
                "[epoch {epoch}/{total}] time={elapsed:.1f}s train_loss={train_loss:.4f} val_loss={val_loss:.4f} train_acc={train_acc:.4f} train_conf={train_conf:.4f} train_margin={train_margin:.4f} val_raw_acc={val_raw_acc:.4f} val_acc={val_acc:.4f} val_macro_f1={val_f1:.4f} val_conf={val_conf:.4f} val_margin={val_margin:.4f} conf={conf:.2f} margin={margin:.2f}".format(
                    epoch=epoch,
                    total=total_epochs,
                    elapsed=elapsed,
                    train_loss=epoch_result["train_loss"],
                    val_loss=epoch_result["val_loss"],
                    train_acc=epoch_result["train_accuracy"],
                    train_conf=epoch_result["train_avg_top1"],
                    train_margin=epoch_result["train_avg_margin"],
                    val_raw_acc=epoch_result["val_raw_top1_accuracy"],
                    val_acc=epoch_result["val_accuracy"],
                    val_f1=epoch_result["val_macro_f1"],
                    val_conf=epoch_result["val_avg_top1"],
                    val_margin=epoch_result["val_avg_margin"],
                    conf=epoch_result["confidence_threshold"],
                    margin=epoch_result["margin_threshold"],
                )
            )
    finally:
        epoch_progress.close()
        if plotter is not None:
            plotter.close()

    _log("[train] best モデルで prototype embedding を抽出します。")

    best_checkpoint = torch.load(best_checkpoint_path, map_location=device, weights_only=False)
    model.load_state_dict(best_checkpoint["model_state"])
    prototype_predictions = _collect_predictions(
        model=model,
        loader=train_clean_loader,
        device=device,
        labels=encoder.labels,
        include_embeddings=True,
        desc="Prototype embeddings",
        feature_extractor=feature_extractor,
    )
    prototypes = build_class_prototypes(
        prototype_predictions["embeddings"],
        prototype_predictions["y_true"],
    )

    write_text_json(model_dir / "label_vocab.json", dictionary.to_label_vocab())
    write_text_json(model_dir / "history.json", {"history": history})
    write_text_json(model_dir / "thresholds.json", best_checkpoint["thresholds"])
    write_text_json(model_dir / "prototypes.json", prototypes)
    _log(f"[train] history={model_dir / 'history.json'}")
    _log(f"[train] thresholds={model_dir / 'thresholds.json'}")
    _log(f"[train] prototypes={model_dir / 'prototypes.json'}")

    summary = {
        "checkpoint": str(best_checkpoint_path),
        "device": str(device),
        "epochs": int(config["training"]["epochs"]),
        "best_val_macro_f1": float(best_macro_f1),
        "thresholds": best_checkpoint["thresholds"],
        "history_path": str(ensure_parent(model_dir / "history.json")),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
