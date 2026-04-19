from __future__ import annotations

import argparse
import json
from pathlib import Path

from iruka_cnn.common.config import load_yaml
from iruka_cnn.common.io import write_wav
from iruka_cnn.common.labels import PhraseDictionary
from iruka_cnn.sender.generator import DolphinWhistleGenerator
from iruka_cnn.sender.streaming import DolphinPhraseStreamer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="自由文から登録済み定型文だけを抽出し、ストリーミング用 WAV を作ります。")
    parser.add_argument("--config", default="configs/baseline.yaml", help="設定ファイルパス")
    parser.add_argument(
        "--text",
        default="こんにちは、了解しました。元気ですか？停止してください",
        help="入力テキスト。登録済み定型文だけが送信対象になります。",
    )
    parser.add_argument("--out", default="artifacts/send/stream_demo.wav", help="出力 WAV パス")
    parser.add_argument("--gap-ms", type=int, default=300, help="フレーズ間に入れる無音長 (ms)")
    parser.add_argument("--seed", type=int, default=7, help="生成 seed")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    config = load_yaml(args.config)
    dictionary = PhraseDictionary.from_yaml(config["dictionary"]["phrases_path"])
    generator = DolphinWhistleGenerator(
        sample_rate=int(config["audio"]["sample_rate"]),
        min_duration_seconds=float(config["audio"]["min_phrase_seconds"]),
        max_duration_seconds=float(config["audio"]["max_phrase_seconds"]),
    )
    streamer = DolphinPhraseStreamer(dictionary, generator, segment_gap_ms=args.gap_ms)
    result = streamer.synthesize_text(args.text, seed=args.seed)
    output_path = write_wav(args.out, result.waveform, result.sample_rate)
    print(
        json.dumps(
            {
                "input_text": args.text,
                "output_path": str(output_path),
                "sample_rate": result.sample_rate,
                "segment_gap_ms": args.gap_ms,
                "seed": args.seed,
                "emitted_texts": result.emitted_texts,
                "dropped_fragments": result.dropped_fragments,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
