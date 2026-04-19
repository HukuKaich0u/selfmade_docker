from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from iruka_cnn.receiver.streaming import StreamingReceiver


class DummyReceiver:
    def __init__(self) -> None:
        self.config = {
            "audio": {
                "sample_rate": 1000,
                "silence_threshold_dbfs": -35.0,
                "clip_seconds": 2.5,
            },
            "streaming": {
                "frame_ms": 20,
                "start_ms": 60,
                "end_ms": 240,
                "provisional_interval_ms": 150,
                "min_provisional_ms": 700,
                "stability_count": 3,
                "min_segment_ms": 300,
                "max_segment_seconds": 2.8,
            },
        }
        self.thresholds = {
            "confidence_threshold": 0.5,
            "margin_threshold": 0.02,
            "top_k": 5,
        }

    def predict_waveform(self, waveform, source_rate=None, include_embedding=False):
        samples = np.asarray(waveform, dtype=np.float32).reshape(-1)
        mean = float(samples.mean()) if samples.size else 0.0
        if abs(mean) < 0.05:
            label = "unknown"
            score = 0.81
            second_label = "了解しました"
        elif mean > 0.0:
            label = "了解しました"
            score = 0.93
            second_label = "停止してください"
        else:
            label = "停止してください"
            score = 0.91
            second_label = "了解しました"
        return SimpleNamespace(
            predicted_label=label,
            predicted_text=label,
            confidence=score,
            raw_top_label=label,
            top_k=[
                {"label": label, "score": score},
                {"label": second_label, "score": 0.03},
            ],
            is_unknown=label == "unknown",
            is_silence=False,
            embedding=None,
            audio_stats={},
        )


def _run_stream(streaming: StreamingReceiver, waveform: np.ndarray) -> list:
    sample_rate = streaming.sample_rate
    chunk_samples = int(sample_rate * 20 / 1000.0)
    events = []
    for start in range(0, waveform.shape[0], chunk_samples):
        end = min(waveform.shape[0], start + chunk_samples)
        events.extend(streaming.push_audio_chunk(waveform[start:end], timestamp_ms=start * 1000.0 / sample_rate))
    events.extend(streaming.flush())
    return events


def test_streaming_receiver_emits_provisional_and_final_events() -> None:
    streaming = StreamingReceiver(DummyReceiver())
    waveform = np.concatenate(
        [
            np.full(1200, 0.7, dtype=np.float32),
            np.zeros(320, dtype=np.float32),
        ]
    )

    events = _run_stream(streaming, waveform)

    provisional = [event for event in events if not event.is_final]
    finals = [event for event in events if event.is_final]
    assert provisional
    assert len(finals) == 1
    assert provisional[0].label == "了解しました"
    assert finals[0].label == "了解しました"
    assert provisional[0].segment_id == finals[0].segment_id
    assert finals[0].start_ms < finals[0].end_ms


def test_streaming_receiver_splits_two_phrase_stream() -> None:
    streaming = StreamingReceiver(DummyReceiver())
    waveform = np.concatenate(
        [
            np.full(1200, 0.7, dtype=np.float32),
            np.zeros(300, dtype=np.float32),
            np.full(1200, -0.7, dtype=np.float32),
            np.zeros(320, dtype=np.float32),
        ]
    )

    events = _run_stream(streaming, waveform)

    finals = [event for event in events if event.is_final]
    assert [event.label for event in finals] == ["了解しました", "停止してください"]
    assert finals[0].segment_id != finals[1].segment_id
    assert finals[0].end_ms <= finals[1].start_ms


def test_streaming_receiver_discards_too_short_segment() -> None:
    streaming = StreamingReceiver(DummyReceiver())
    waveform = np.concatenate(
        [
            np.full(200, 0.7, dtype=np.float32),
            np.zeros(320, dtype=np.float32),
        ]
    )

    events = _run_stream(streaming, waveform)

    assert not events


def test_streaming_receiver_emits_unknown_for_unknown_burst() -> None:
    streaming = StreamingReceiver(DummyReceiver())
    waveform = np.concatenate(
        [
            np.tile(np.array([0.8, -0.8], dtype=np.float32), 450),
            np.zeros(320, dtype=np.float32),
        ]
    )

    events = _run_stream(streaming, waveform)

    finals = [event for event in events if event.is_final]
    assert len(finals) == 1
    assert finals[0].label == "unknown"
