from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from tqdm.auto import tqdm

from iruka_cnn.common.config import load_yaml
from iruka_cnn.common.io import write_wav
from iruka_cnn.common.labels import PhraseDictionary, SILENCE_LABEL, UNKNOWN_LABEL
from iruka_cnn.common.utils import stable_seed
from iruka_cnn.training.dataset import AudioRecord, save_records
from iruka_cnn.training.feature_cache import ensure_feature_cache, feature_path_from_audio_path
from iruka_cnn.sender.generator import DolphinWhistleGenerator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="学習用WAVデータセットを生成します。")
    parser.add_argument("--config", default="configs/baseline.yaml", help="設定ファイルパス")
    parser.add_argument("--overwrite", action="store_true", help="既存データを上書き生成する")
    return parser


def _log(message: str) -> None:
    tqdm.write(message)


def generate_dataset(config: dict) -> dict[str, int]:
    dictionary = PhraseDictionary.from_yaml(config["dictionary"]["phrases_path"])
    generator = DolphinWhistleGenerator(
        sample_rate=config["audio"]["sample_rate"],
        min_duration_seconds=config["audio"].get("min_phrase_seconds", 1.0),
        max_duration_seconds=config["audio"].get("max_phrase_seconds", 2.5),
    )
    data_root = Path("data")
    overwrite = bool(config["dataset"].get("overwrite", False))
    if overwrite:
        _log("[data] 既存の train/val/test ディレクトリを削除して再生成します。")
        for split in ("train", "val", "test"):
            split_dir = data_root / split
            if split_dir.exists():
                shutil.rmtree(split_dir)
    counts = {
        "train": int(config["dataset"]["train_per_phrase"]),
        "val": int(config["dataset"]["val_per_phrase"]),
        "test": int(config["dataset"]["test_per_phrase"]),
    }
    generated = {"phrases": 0, "unknown": 0, "silence": 0, "features_cached": 0}
    cache_features = bool(config.get("dataset", {}).get("cache_features", True))
    for split, per_phrase in counts.items():
        records: list[AudioRecord] = []
        split_dir = data_root / split
        split_dir.mkdir(parents=True, exist_ok=True)
        split_generated = {"phrases": 0, "unknown": 0, "silence": 0}
        split_total = len(dictionary.phrases) * per_phrase
        split_total += int(config["dataset"]["unknown_per_split"])
        split_total += int(config["dataset"]["silence_per_split"])
        progress = tqdm(
            total=split_total,
            desc=f"Generate {split}",
            unit="wav",
            dynamic_ncols=True,
        )
        for phrase in dictionary.phrases:
            label_dir = split_dir / phrase.key
            label_dir.mkdir(parents=True, exist_ok=True)
            for idx in range(per_phrase):
                seed = stable_seed(f"{split}:{phrase.key}:{idx}")
                signal = generator.generate(phrase, seed=seed)
                output_path = label_dir / f"{idx:05d}.wav"
                write_wav(output_path, signal.waveform, signal.sample_rate)
                records.append(
                    AudioRecord(
                        path=str(output_path),
                        label=phrase.text,
                        split=split,
                        seed=seed,
                        feature_path=feature_path_from_audio_path(output_path) if cache_features else None,
                    )
                )
                generated["phrases"] += 1
                split_generated["phrases"] += 1
                progress.update(1)
                progress.set_postfix(
                    phrase=phrase.key,
                    phrase_wavs=split_generated["phrases"],
                    unknown=split_generated["unknown"],
                    silence=split_generated["silence"],
                )
        unknown_dir = split_dir / UNKNOWN_LABEL
        unknown_dir.mkdir(parents=True, exist_ok=True)
        for idx in range(int(config["dataset"]["unknown_per_split"])):
            seed = stable_seed(f"{split}:unknown:{idx}")
            signal = generator.generate_unknown(seed=seed)
            output_path = unknown_dir / f"{idx:05d}.wav"
            write_wav(output_path, signal.waveform, signal.sample_rate)
            records.append(
                AudioRecord(
                    path=str(output_path),
                    label=UNKNOWN_LABEL,
                    split=split,
                    seed=seed,
                    feature_path=feature_path_from_audio_path(output_path) if cache_features else None,
                )
            )
            generated["unknown"] += 1
            split_generated["unknown"] += 1
            progress.update(1)
            progress.set_postfix(
                phrase="unknown",
                phrase_wavs=split_generated["phrases"],
                unknown=split_generated["unknown"],
                silence=split_generated["silence"],
            )
        silence_dir = split_dir / SILENCE_LABEL
        silence_dir.mkdir(parents=True, exist_ok=True)
        for idx in range(int(config["dataset"]["silence_per_split"])):
            seed = stable_seed(f"{split}:silence:{idx}")
            signal = generator.generate_silence(duration_seconds=config["audio"]["clip_seconds"], seed=seed)
            output_path = silence_dir / f"{idx:05d}.wav"
            write_wav(output_path, signal.waveform, signal.sample_rate)
            records.append(
                AudioRecord(
                    path=str(output_path),
                    label=SILENCE_LABEL,
                    split=split,
                    seed=seed,
                    feature_path=feature_path_from_audio_path(output_path) if cache_features else None,
                )
            )
            generated["silence"] += 1
            split_generated["silence"] += 1
            progress.update(1)
            progress.set_postfix(
                phrase="silence",
                phrase_wavs=split_generated["phrases"],
                unknown=split_generated["unknown"],
                silence=split_generated["silence"],
            )
        metadata = save_records(data_root, split, records)
        progress.close()
        _log(
            "[data] split={split} 完了: phrase_wavs={phrases} unknown={unknown} silence={silence} metadata={metadata}".format(
                split=split,
                phrases=split_generated["phrases"],
                unknown=split_generated["unknown"],
                silence=split_generated["silence"],
                metadata=metadata,
            )
        )
    if cache_features:
        cache_summary = ensure_feature_cache(config, data_root=data_root, splits=counts.keys())
        generated["features_cached"] = sum(split_result["cached"] for split_result in cache_summary.values())
        for split, split_result in cache_summary.items():
            _log(
                "[cache] split={split} cached={cached} skipped={skipped}".format(
                    split=split,
                    cached=split_result["cached"],
                    skipped=split_result["skipped"],
                )
            )
    return generated


def main() -> None:
    args = build_parser().parse_args()
    config = load_yaml(args.config)
    if args.overwrite:
        config.setdefault("dataset", {})
        config["dataset"]["overwrite"] = True
    generated = generate_dataset(config)
    print(json.dumps(generated, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
