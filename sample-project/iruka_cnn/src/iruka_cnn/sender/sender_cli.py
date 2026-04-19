from __future__ import annotations

import argparse
import json
from pathlib import Path

from iruka_cnn.common.io import write_wav
from iruka_cnn.common.labels import PhraseDictionary
from iruka_cnn.sender.generator import DolphinWhistleGenerator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="定型文をイルカ風ホイッスルWAVへ変換します。")
    parser.add_argument("--text", required=True, help="登録済み定型文")
    parser.add_argument("--out", required=True, help="出力先WAVパス")
    parser.add_argument("--seed", type=int, default=None, help="バリエーション再現用シード")
    parser.add_argument("--phrases", default="data/phrases.yaml", help="定型文辞書パス")
    parser.add_argument("--sample-rate", type=int, default=24000, help="出力サンプルレート")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    dictionary = PhraseDictionary.from_yaml(args.phrases)
    try:
        phrase = dictionary.get_by_text(args.text)
    except KeyError as exc:
        valid = " / ".join(dictionary.texts())
        raise SystemExit(f"未登録の定型文です: {args.text}\n利用可能: {valid}") from exc
    generator = DolphinWhistleGenerator(sample_rate=args.sample_rate)
    signal = generator.generate(phrase=phrase, seed=args.seed)
    output_path = write_wav(Path(args.out), signal.waveform, signal.sample_rate)
    result = {
        "phrase_text": signal.phrase_text,
        "phrase_key": signal.phrase_key,
        "seed": signal.seed,
        "sample_rate": signal.sample_rate,
        "duration_seconds": round(signal.duration_seconds, 4),
        "wav_path": str(output_path),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
