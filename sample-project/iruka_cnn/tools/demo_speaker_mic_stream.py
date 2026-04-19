from __future__ import annotations

import argparse
import json
import sys

from iruka_cnn.demo.acoustic import AcousticDemoError, list_audio_devices, run_acoustic_demo


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mac のスピーカー再生とマイク録音を通して、イルカ音声ストリーミング認識を実演します。"
    )
    parser.add_argument("--config", default="configs/baseline.yaml", help="設定ファイルパス")
    parser.add_argument(
        "--text",
        default="こんにちは、了解しました。元気ですか？停止してください",
        help="入力テキスト。登録済み定型文だけが送信対象になります。",
    )
    parser.add_argument("--model", default="artifacts/models/best.pt", help="学習済みモデルパス")
    parser.add_argument("--out-played", default="artifacts/send/acoustic_demo_played.wav", help="再生 WAV 保存先")
    parser.add_argument("--out-recorded", default="artifacts/recv/acoustic_demo_recorded.wav", help="録音 WAV 保存先")
    parser.add_argument("--gap-ms", type=int, default=300, help="フレーズ間に入れる無音長 (ms)")
    parser.add_argument("--seed", type=int, default=7, help="生成 seed")
    parser.add_argument("--chunk-ms", type=int, default=20, help="録音チャンク長 (ms)")
    parser.add_argument("--pre-roll-ms", type=int, default=300, help="再生前に入れる無音長 (ms)")
    parser.add_argument("--tail-ms", type=int, default=1200, help="再生後も録音を続ける長さ (ms)")
    parser.add_argument("--device", default="auto", help="推論デバイス。auto / mps / cpu")
    parser.add_argument("--input-device", help="録音デバイス index または name 部分一致")
    parser.add_argument("--output-device", help="再生デバイス index または name 部分一致")
    parser.add_argument("--list-devices", action="store_true", help="利用可能な音声デバイス一覧を表示して終了")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        if args.list_devices:
            payload = {
                "devices": [device.to_dict() for device in list_audio_devices()],
            }
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        result = run_acoustic_demo(
            config_path=args.config,
            text=args.text,
            model_path=args.model,
            out_played=args.out_played,
            out_recorded=args.out_recorded,
            gap_ms=args.gap_ms,
            seed=args.seed,
            chunk_ms=args.chunk_ms,
            pre_roll_ms=args.pre_roll_ms,
            tail_ms=args.tail_ms,
            device_name=args.device,
            input_device=args.input_device,
            output_device=args.output_device,
            on_event=lambda event: print(
                json.dumps(
                    {"type": "event", **event.to_dict()},
                    ensure_ascii=False,
                )
            ),
        )
    except AcousticDemoError as exc:
        print(f"[acoustic-demo] {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(json.dumps(result.to_summary_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
