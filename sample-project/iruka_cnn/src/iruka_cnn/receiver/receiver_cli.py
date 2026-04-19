from __future__ import annotations

import argparse
import json

from iruka_cnn.receiver.infer import Receiver


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="イルカ風WAVを分類して定型文を推定します。")
    parser.add_argument("--in", dest="input_path", required=True, help="入力WAVパス")
    parser.add_argument("--model", default="artifacts/models/best.pt", help="学習済みモデルパス")
    parser.add_argument("--device", default="auto", help="auto / mps / cpu")
    parser.add_argument("--with-embedding", action="store_true", help="埋め込みベクトルも出力する")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    receiver = Receiver(checkpoint_path=args.model, device_name=args.device)
    result = receiver.predict_file(args.input_path, include_embedding=args.with_embedding)
    print(
        json.dumps(
            {
                "predicted_text": result.predicted_text,
                "predicted_label": result.predicted_label,
                "raw_top_label": result.raw_top_label,
                "confidence": round(result.confidence, 6),
                "top_k": result.top_k,
                "unknown": result.is_unknown,
                "silence": result.is_silence,
                "embedding": result.embedding,
                "audio_stats": result.audio_stats,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
