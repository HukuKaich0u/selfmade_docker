from __future__ import annotations

import importlib
import queue
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

from iruka_cnn.common.config import load_yaml
from iruka_cnn.common.io import write_wav
from iruka_cnn.common.labels import PhraseDictionary
from iruka_cnn.receiver.infer import Receiver
from iruka_cnn.receiver.streaming import StreamingPredictionEvent, StreamingReceiver
from iruka_cnn.sender.generator import DolphinWhistleGenerator
from iruka_cnn.sender.streaming import DolphinPhraseStreamer


class AcousticDemoError(RuntimeError):
    """音響デモの実行失敗。"""


@dataclass(frozen=True)
class ResolvedAudioDevice:
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_samplerate: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AcousticDemoResult:
    input_text: str
    emitted_texts: list[str]
    dropped_fragments: list[str]
    played_path: Path
    recorded_path: Path
    sample_rate: int
    events: list[StreamingPredictionEvent]
    input_device: ResolvedAudioDevice
    output_device: ResolvedAudioDevice
    segment_gap_ms: int
    pre_roll_ms: int
    tail_ms: int
    chunk_ms: int

    def to_summary_dict(self) -> dict[str, Any]:
        return {
            "type": "summary",
            "input_text": self.input_text,
            "sample_rate": self.sample_rate,
            "segment_gap_ms": self.segment_gap_ms,
            "pre_roll_ms": self.pre_roll_ms,
            "tail_ms": self.tail_ms,
            "chunk_ms": self.chunk_ms,
            "played_path": str(self.played_path),
            "recorded_path": str(self.recorded_path),
            "emitted_texts": self.emitted_texts,
            "dropped_fragments": self.dropped_fragments,
            "input_device": self.input_device.to_dict(),
            "output_device": self.output_device.to_dict(),
            "events": [event.to_dict() for event in self.events],
        }


def _load_sounddevice() -> Any:
    try:
        return importlib.import_module("sounddevice")
    except Exception as exc:  # pragma: no cover - import path is environment dependent.
        raise AcousticDemoError(
            "sounddevice を読み込めませんでした。`uv sync --extra dev` のあと、必要なら `brew install portaudio` を確認してください。"
        ) from exc


def list_audio_devices(sounddevice_module: Any | None = None) -> list[ResolvedAudioDevice]:
    sd = sounddevice_module or _load_sounddevice()
    try:
        devices = sd.query_devices()
    except Exception as exc:  # pragma: no cover - hardware error path.
        raise AcousticDemoError(f"音声デバイス一覧の取得に失敗しました: {exc}") from exc
    return [
        ResolvedAudioDevice(
            index=index,
            name=str(device["name"]),
            max_input_channels=int(device.get("max_input_channels", 0)),
            max_output_channels=int(device.get("max_output_channels", 0)),
            default_samplerate=float(device.get("default_samplerate", 0.0)),
        )
        for index, device in enumerate(devices)
    ]


def resolve_audio_device(
    selector: str | int | None,
    *,
    direction: str,
    sounddevice_module: Any | None = None,
) -> ResolvedAudioDevice:
    if direction not in {"input", "output"}:
        raise ValueError(f"direction は input/output のみ許可します: {direction}")
    sd = sounddevice_module or _load_sounddevice()
    devices = list_audio_devices(sd)
    channel_key = "max_input_channels" if direction == "input" else "max_output_channels"
    eligible = [device for device in devices if getattr(device, channel_key) > 0]
    if not eligible:
        raise AcousticDemoError(f"{direction} 用に使える音声デバイスが見つかりません。")
    if selector is None:
        return _resolve_default_device(sd=sd, devices=devices, direction=direction)
    if isinstance(selector, str):
        stripped = selector.strip()
        if stripped.isdigit():
            selector = int(stripped)
        else:
            lowered = stripped.casefold()
            matches = [device for device in eligible if lowered in device.name.casefold()]
            if not matches:
                raise AcousticDemoError(
                    f"{direction} デバイス `{selector}` が見つかりません。`--list-devices` で候補を確認してください。"
                )
            if len(matches) > 1:
                candidates = ", ".join(f"{device.index}:{device.name}" for device in matches)
                raise AcousticDemoError(f"{direction} デバイス `{selector}` は曖昧です: {candidates}")
            return matches[0]
    if isinstance(selector, int):
        matches = [device for device in eligible if device.index == selector]
        if not matches:
            raise AcousticDemoError(
                f"{direction} デバイス index={selector} は使えません。`--list-devices` で候補を確認してください。"
            )
        return matches[0]
    raise AcousticDemoError(f"{direction} デバイス指定を解釈できませんでした: {selector!r}")


def _resolve_default_device(sd: Any, devices: list[ResolvedAudioDevice], direction: str) -> ResolvedAudioDevice:
    default_devices = getattr(getattr(sd, "default", None), "device", None)
    if default_devices is None:
        raise AcousticDemoError(f"既定の {direction} デバイスを取得できませんでした。")
    default_index = default_devices[0 if direction == "input" else 1]
    if default_index is None or int(default_index) < 0:
        raise AcousticDemoError(f"既定の {direction} デバイスが未設定です。")
    matches = [device for device in devices if device.index == int(default_index)]
    if not matches:
        raise AcousticDemoError(f"既定の {direction} デバイス index={default_index} が見つかりません。")
    required_channels = "max_input_channels" if direction == "input" else "max_output_channels"
    if getattr(matches[0], required_channels) <= 0:
        raise AcousticDemoError(f"既定の {direction} デバイス {matches[0].name} は {direction} に使えません。")
    return matches[0]


def run_acoustic_demo(
    *,
    config_path: str | Path = "configs/baseline.yaml",
    text: str = "こんにちは、了解しました。元気ですか？停止してください",
    model_path: str | Path = "artifacts/models/best.pt",
    out_played: str | Path = "artifacts/send/acoustic_demo_played.wav",
    out_recorded: str | Path = "artifacts/recv/acoustic_demo_recorded.wav",
    gap_ms: int = 300,
    seed: int | None = 7,
    chunk_ms: int = 20,
    pre_roll_ms: int = 300,
    tail_ms: int = 1200,
    device_name: str = "auto",
    input_device: str | int | None = None,
    output_device: str | int | None = None,
    on_event: Callable[[StreamingPredictionEvent], None] | None = None,
    sounddevice_module: Any | None = None,
) -> AcousticDemoResult:
    config = load_yaml(config_path)
    dictionary = PhraseDictionary.from_yaml(config["dictionary"]["phrases_path"])
    generator = DolphinWhistleGenerator(
        sample_rate=int(config["audio"]["sample_rate"]),
        min_duration_seconds=float(config["audio"]["min_phrase_seconds"]),
        max_duration_seconds=float(config["audio"]["max_phrase_seconds"]),
    )
    streamer = DolphinPhraseStreamer(dictionary, generator, segment_gap_ms=gap_ms)
    build_result = streamer.synthesize_text(text=text, seed=seed)
    receiver = Receiver(checkpoint_path=model_path, device_name=device_name)
    streaming = StreamingReceiver(receiver)
    sample_rate = int(streaming.sample_rate)
    if sample_rate != int(build_result.sample_rate):
        raise AcousticDemoError(
            f"送信波形の sample_rate={build_result.sample_rate} と受信器の sample_rate={sample_rate} が一致しません。"
        )
    pre_roll = np.zeros(int(sample_rate * max(0, pre_roll_ms) / 1000.0), dtype=np.float32)
    tail = np.zeros(int(sample_rate * max(0, tail_ms) / 1000.0), dtype=np.float32)
    playback_waveform = np.concatenate([pre_roll, build_result.waveform.astype(np.float32, copy=False), tail]).astype(
        np.float32,
        copy=False,
    )
    played_path = write_wav(out_played, playback_waveform, sample_rate)
    sd = sounddevice_module or _load_sounddevice()
    resolved_input = resolve_audio_device(input_device, direction="input", sounddevice_module=sd)
    resolved_output = resolve_audio_device(output_device, direction="output", sounddevice_module=sd)
    chunk_samples = max(1, int(sample_rate * max(1, chunk_ms) / 1000.0))
    input_queue: queue.Queue[np.ndarray] = queue.Queue()
    status_messages: queue.Queue[str] = queue.Queue()
    playback_state = {"offset": 0}

    def callback(indata: np.ndarray, outdata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        del time_info
        if status:
            status_messages.put(str(status))
        samples = np.asarray(indata, dtype=np.float32)
        if samples.ndim == 2:
            captured = samples[:, 0].copy()
        else:
            captured = samples.reshape(-1).copy()
        input_queue.put(captured)
        outdata.fill(0)
        start = int(playback_state["offset"])
        end = min(start + frames, playback_waveform.shape[0])
        if end > start:
            chunk = playback_waveform[start:end]
            if outdata.ndim == 2:
                outdata[: chunk.shape[0], 0] = chunk
            else:
                outdata[: chunk.shape[0]] = chunk
        playback_state["offset"] = end
        if end >= playback_waveform.shape[0]:
            raise sd.CallbackStop()

    events: list[StreamingPredictionEvent] = []
    recorded_chunks: list[np.ndarray] = []
    next_timestamp_ms = 0.0
    try:
        stream = sd.Stream(
            samplerate=sample_rate,
            blocksize=chunk_samples,
            dtype="float32",
            channels=(1, 1),
            device=(resolved_input.index, resolved_output.index),
            callback=callback,
        )
    except Exception as exc:  # pragma: no cover - hardware error path.
        raise AcousticDemoError(f"音声ストリームを開けませんでした: {exc}") from exc
    try:
        with stream:
            while True:
                drained = _drain_input_queue(
                    input_queue=input_queue,
                    streaming=streaming,
                    recorded_chunks=recorded_chunks,
                    events=events,
                    next_timestamp_ms_ref=[next_timestamp_ms],
                    sample_rate=sample_rate,
                    on_event=on_event,
                )
                next_timestamp_ms += drained * 1000.0 / sample_rate
                if not getattr(stream, "active", False) and input_queue.empty():
                    break
                time.sleep(min(0.02, max(0.005, chunk_ms / 2000.0)))
    except Exception as exc:
        if isinstance(exc, AcousticDemoError):
            raise
        raise AcousticDemoError(f"音声ストリーム実行に失敗しました: {exc}") from exc
    while not input_queue.empty():
        drained = _drain_input_queue(
            input_queue=input_queue,
            streaming=streaming,
            recorded_chunks=recorded_chunks,
            events=events,
            next_timestamp_ms_ref=[next_timestamp_ms],
            sample_rate=sample_rate,
            on_event=on_event,
        )
        next_timestamp_ms += drained * 1000.0 / sample_rate
    for message in _drain_status_messages(status_messages):
        raise AcousticDemoError(f"音声入出力の警告を検出しました: {message}")
    final_events = streaming.flush()
    events.extend(final_events)
    if on_event is not None:
        for event in final_events:
            on_event(event)
    if not recorded_chunks:
        raise AcousticDemoError("録音データが空でした。マイク権限や入力デバイス設定を確認してください。")
    recorded_waveform = np.concatenate(recorded_chunks).astype(np.float32, copy=False)
    recorded_path = write_wav(out_recorded, recorded_waveform, sample_rate)
    return AcousticDemoResult(
        input_text=text,
        emitted_texts=build_result.emitted_texts,
        dropped_fragments=build_result.dropped_fragments,
        played_path=played_path,
        recorded_path=recorded_path,
        sample_rate=sample_rate,
        events=events,
        input_device=resolved_input,
        output_device=resolved_output,
        segment_gap_ms=gap_ms,
        pre_roll_ms=pre_roll_ms,
        tail_ms=tail_ms,
        chunk_ms=chunk_ms,
    )


def _drain_input_queue(
    *,
    input_queue: queue.Queue[np.ndarray],
    streaming: StreamingReceiver,
    recorded_chunks: list[np.ndarray],
    events: list[StreamingPredictionEvent],
    next_timestamp_ms_ref: list[float],
    sample_rate: int,
    on_event: Callable[[StreamingPredictionEvent], None] | None,
) -> int:
    drained_samples = 0
    while True:
        try:
            chunk = input_queue.get_nowait()
        except queue.Empty:
            break
        if chunk.size == 0:
            continue
        recorded_chunks.append(chunk.astype(np.float32, copy=False))
        new_events = streaming.push_audio_chunk(chunk, timestamp_ms=next_timestamp_ms_ref[0])
        events.extend(new_events)
        if on_event is not None:
            for event in new_events:
                on_event(event)
        drained_samples += int(chunk.shape[0])
        next_timestamp_ms_ref[0] += chunk.shape[0] * 1000.0 / sample_rate
    return drained_samples


def _drain_status_messages(status_messages: queue.Queue[str]) -> list[str]:
    messages: list[str] = []
    while True:
        try:
            messages.append(status_messages.get_nowait())
        except queue.Empty:
            return messages
