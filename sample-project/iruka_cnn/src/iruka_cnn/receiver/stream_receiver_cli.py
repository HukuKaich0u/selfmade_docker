from __future__ import annotations

import argparse
import json

import torch

from iruka_cnn.common.io import read_wav
from iruka_cnn.receiver.infer import Receiver
from iruka_cnn.receiver.preprocess import resample_if_needed
from iruka_cnn.receiver.streaming import StreamingReceiver


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="WAV をチャンク分割してストリーミング受信挙動を確認します。")
    parser.add_argument("--in", dest="input_path", required=True, help="入力 WAV パス")
    parser.add_argument("--model", default="artifacts/models/best.pt", help="学習済みモデルパス")
    parser.add_argument("--device", default="auto", help="auto / mps / cpu")
    parser.add_argument("--chunk-ms", type=int, default=20, help="ストリーミング擬似チャンク長 (ms)")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    receiver = Receiver(checkpoint_path=args.model, device_name=args.device)
    streaming = StreamingReceiver(receiver)
    waveform, source_rate = read_wav(args.input_path)
    stream_rate = source_rate
    if source_rate != streaming.sample_rate:
        waveform = (
            resample_if_needed(
                torch.from_numpy(waveform.astype("float32", copy=False)),
                source_rate=source_rate,
                target_rate=streaming.sample_rate,
            )
            .cpu()
            .numpy()
            .astype("float32", copy=False)
        )
        stream_rate = streaming.sample_rate
    chunk_samples = max(1, int(stream_rate * args.chunk_ms / 1000.0))
    events = []
    for start in range(0, waveform.shape[0], chunk_samples):
        end = min(waveform.shape[0], start + chunk_samples)
        timestamp_ms = start * 1000.0 / stream_rate
        events.extend(
            event.to_dict()
            for event in streaming.push_audio_chunk(
                waveform[start:end],
                timestamp_ms=timestamp_ms,
            )
        )
    events.extend(event.to_dict() for event in streaming.flush())
    print(
        json.dumps(
            {
                "input_path": args.input_path,
                "source_sample_rate": source_rate,
                "stream_sample_rate": stream_rate,
                "chunk_ms": args.chunk_ms,
                "events": events,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
