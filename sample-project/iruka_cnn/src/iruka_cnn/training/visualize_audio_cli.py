from __future__ import annotations

import argparse
import json
from pathlib import Path

from iruka_cnn.common.config import load_yaml
from iruka_cnn.common.io import read_wav
from iruka_cnn.common.labels import PhraseDictionary
from iruka_cnn.sender.generator import DolphinWhistleGenerator
from iruka_cnn.training.visualization import default_visualization_output_path, render_audio_overview


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WAV または定型文の波形・スペクトログラムを可視化します。")
    parser.add_argument("--config", default="configs/baseline.yaml", help="設定ファイルパス")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--wav", dest="wav_path", help="可視化する WAV パス")
    source.add_argument("--text", dest="phrase_text", help="可視化する登録済み定型文")
    parser.add_argument("--seed", type=int, default=None, help="--text 用の生成 seed")
    parser.add_argument("--out", default=None, help="出力 PNG パス")
    parser.add_argument("--title", default=None, help="図のタイトル")
    parser.add_argument("--show", action="store_true", help="PNG 保存後に matplotlib で表示する")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_yaml(args.config)
    output_path = Path(args.out) if args.out else default_visualization_output_path(Path(config["experiment"]["output_dir"]) / "reports")

    if args.wav_path:
        waveform, source_rate = read_wav(args.wav_path)
        title = args.title or Path(args.wav_path).name
        input_payload = {"input_path": args.wav_path}
    else:
        dictionary = PhraseDictionary.from_yaml(config["dictionary"]["phrases_path"])
        try:
            phrase = dictionary.get_by_text(args.phrase_text)
        except KeyError as exc:
            raise SystemExit(f"未登録の定型文です: {args.phrase_text}") from exc
        generator = DolphinWhistleGenerator(
            sample_rate=int(config["audio"]["sample_rate"]),
            min_duration_seconds=float(config["audio"]["min_phrase_seconds"]),
            max_duration_seconds=float(config["audio"]["max_phrase_seconds"]),
        )
        generated = generator.generate(phrase=phrase, seed=args.seed)
        waveform = generated.waveform
        source_rate = generated.sample_rate
        title = args.title or f"generated_phrase_seed_{generated.seed}"
        input_payload = {"input_text": phrase.text, "phrase_key": phrase.key, "seed": generated.seed}

    result = render_audio_overview(
        waveform=waveform,
        source_rate=source_rate,
        config=config,
        output_path=output_path,
        title=title,
        show=args.show,
    )
    print(
        json.dumps(
            {
                "output_path": str(result.output_path),
                "source_sample_rate": result.source_sample_rate,
                "model_sample_rate": result.model_sample_rate,
                "audio_stats": result.audio_stats,
                "title": title,
                **input_payload,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
