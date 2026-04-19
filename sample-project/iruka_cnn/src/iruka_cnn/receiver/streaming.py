from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import torch

from iruka_cnn.common.labels import SILENCE_LABEL, UNKNOWN_LABEL


@dataclass(frozen=True)
class StreamingPredictionEvent:
    segment_id: int
    label: str
    text: str
    confidence: float
    is_final: bool
    start_ms: float
    end_ms: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class StreamingReceiver:
    def __init__(self, receiver: Any) -> None:
        self.receiver = receiver
        self.sample_rate = int(receiver.config["audio"]["sample_rate"])
        self.energy_threshold_dbfs = float(receiver.config["audio"]["silence_threshold_dbfs"])
        streaming_config = receiver.config.get("streaming", {})
        self.frame_ms = int(streaming_config.get("frame_ms", 20))
        self.frame_samples = max(1, int(self.sample_rate * self.frame_ms / 1000.0))
        self.start_frames = max(1, int(np.ceil(float(streaming_config.get("start_ms", 60)) / self.frame_ms)))
        self.end_frames = max(1, int(np.ceil(float(streaming_config.get("end_ms", 240)) / self.frame_ms)))
        self.provisional_interval_samples = max(
            1,
            int(self.sample_rate * float(streaming_config.get("provisional_interval_ms", 150)) / 1000.0),
        )
        self.min_provisional_samples = max(
            1,
            int(self.sample_rate * float(streaming_config.get("min_provisional_ms", 700)) / 1000.0),
        )
        self.min_segment_samples = max(
            1,
            int(self.sample_rate * float(streaming_config.get("min_segment_ms", 300)) / 1000.0),
        )
        self.max_segment_samples = max(
            1,
            int(self.sample_rate * float(streaming_config.get("max_segment_seconds", 2.8))),
        )
        self.stability_count = max(1, int(streaming_config.get("stability_count", 3)))
        self._base_timestamp_ms = 0.0
        self._base_timestamp_fixed = False
        self._received_samples = 0
        self._processed_samples = 0
        self._frame_buffer = np.zeros(0, dtype=np.float32)
        self._speech_streak = 0
        self._pending_frames: list[np.ndarray] = []
        self._pending_start_sample: int | None = None
        self._in_segment = False
        self._next_segment_id = 0
        self._segment_id: int | None = None
        self._segment_start_sample = 0
        self._segment_frames: list[np.ndarray] = []
        self._segment_silence_frames = 0
        self._last_provisional_eval_samples = 0
        self._provisional_history: deque[tuple[str, float] | None] = deque(maxlen=self.stability_count)
        self._last_emitted_provisional_label: str | None = None

    def push_audio_chunk(
        self,
        chunk: np.ndarray | torch.Tensor,
        timestamp_ms: float | None = None,
    ) -> list[StreamingPredictionEvent]:
        samples = self._to_numpy_samples(chunk)
        chunk_start_sample = self._received_samples
        if timestamp_ms is not None and not self._base_timestamp_fixed:
            self._base_timestamp_ms = float(timestamp_ms) - (chunk_start_sample * 1000.0 / self.sample_rate)
            self._base_timestamp_fixed = True
        self._received_samples += int(samples.shape[0])
        if samples.size == 0:
            return []
        self._frame_buffer = np.concatenate([self._frame_buffer, samples.astype(np.float32, copy=False)])
        events: list[StreamingPredictionEvent] = []
        while self._frame_buffer.shape[0] >= self.frame_samples:
            frame = self._frame_buffer[: self.frame_samples]
            self._frame_buffer = self._frame_buffer[self.frame_samples :]
            frame_start_sample = self._processed_samples
            frame_end_sample = frame_start_sample + self.frame_samples
            self._processed_samples = frame_end_sample
            events.extend(self._process_frame(frame, frame_start_sample, frame_end_sample))
        return events

    def flush(self) -> list[StreamingPredictionEvent]:
        if not self._in_segment:
            self._frame_buffer = np.zeros(0, dtype=np.float32)
            self._clear_pending()
            return []
        events = self._finalize_segment(
            end_sample=self._received_samples,
            drop_trailing_silence=False,
            partial_tail=self._frame_buffer.copy(),
        )
        self._frame_buffer = np.zeros(0, dtype=np.float32)
        return events

    def _process_frame(
        self,
        frame: np.ndarray,
        frame_start_sample: int,
        frame_end_sample: int,
    ) -> list[StreamingPredictionEvent]:
        is_speech = self._frame_dbfs(frame) > self.energy_threshold_dbfs
        if not self._in_segment:
            return self._process_idle_frame(frame, frame_start_sample, is_speech)
        self._segment_frames.append(frame.copy())
        if is_speech:
            self._segment_silence_frames = 0
        else:
            self._segment_silence_frames += 1
        if self._segment_silence_frames >= self.end_frames:
            end_sample = frame_end_sample - self._segment_silence_frames * self.frame_samples
            return self._finalize_segment(end_sample=end_sample, drop_trailing_silence=True)
        useful_samples = self._segment_useful_samples(drop_trailing_silence=True)
        if useful_samples >= self.max_segment_samples:
            return self._finalize_segment(
                end_sample=self._segment_start_sample + useful_samples,
                drop_trailing_silence=True,
            )
        return self._maybe_emit_provisional()

    def _process_idle_frame(
        self,
        frame: np.ndarray,
        frame_start_sample: int,
        is_speech: bool,
    ) -> list[StreamingPredictionEvent]:
        if not is_speech:
            self._clear_pending()
            return []
        if self._speech_streak == 0:
            self._pending_start_sample = frame_start_sample
        self._speech_streak += 1
        self._pending_frames.append(frame.copy())
        if self._speech_streak < self.start_frames:
            return []
        self._open_segment()
        return self._maybe_emit_provisional()

    def _open_segment(self) -> None:
        self._in_segment = True
        self._segment_id = self._next_segment_id
        self._next_segment_id += 1
        self._segment_start_sample = self._pending_start_sample or 0
        self._segment_frames = [frame.copy() for frame in self._pending_frames]
        self._segment_silence_frames = 0
        self._last_provisional_eval_samples = 0
        self._provisional_history = deque(maxlen=self.stability_count)
        self._last_emitted_provisional_label = None
        self._clear_pending()

    def _clear_pending(self) -> None:
        self._speech_streak = 0
        self._pending_frames = []
        self._pending_start_sample = None

    def _reset_segment(self) -> None:
        self._in_segment = False
        self._segment_id = None
        self._segment_start_sample = 0
        self._segment_frames = []
        self._segment_silence_frames = 0
        self._last_provisional_eval_samples = 0
        self._provisional_history = deque(maxlen=self.stability_count)
        self._last_emitted_provisional_label = None

    def _segment_useful_samples(self, drop_trailing_silence: bool) -> int:
        total = len(self._segment_frames) * self.frame_samples
        if drop_trailing_silence:
            total -= self._segment_silence_frames * self.frame_samples
        return max(0, total)

    def _maybe_emit_provisional(self) -> list[StreamingPredictionEvent]:
        useful_samples = self._segment_useful_samples(drop_trailing_silence=True)
        if useful_samples < self.min_provisional_samples:
            return []
        if useful_samples - self._last_provisional_eval_samples < self.provisional_interval_samples:
            return []
        self._last_provisional_eval_samples = useful_samples
        waveform = self._build_segment_waveform(drop_trailing_silence=True)
        if waveform.size < self.min_provisional_samples:
            return []
        result = self.receiver.predict_waveform(waveform, source_rate=self.sample_rate)
        candidate = self._candidate_from_result(result)
        self._provisional_history.append(candidate)
        if len(self._provisional_history) < self.stability_count:
            return []
        if candidate is None:
            return []
        if any(item is None or item[0] != candidate[0] for item in self._provisional_history):
            return []
        if candidate[0] == self._last_emitted_provisional_label:
            return []
        self._last_emitted_provisional_label = candidate[0]
        return [
            StreamingPredictionEvent(
                segment_id=int(self._segment_id or 0),
                label=candidate[0],
                text=candidate[0],
                confidence=round(candidate[1], 6),
                is_final=False,
                start_ms=self._sample_to_ms(self._segment_start_sample),
                end_ms=self._sample_to_ms(self._segment_start_sample + useful_samples),
            )
        ]

    def _finalize_segment(
        self,
        end_sample: int,
        drop_trailing_silence: bool,
        partial_tail: np.ndarray | None = None,
    ) -> list[StreamingPredictionEvent]:
        waveform = self._build_segment_waveform(
            drop_trailing_silence=drop_trailing_silence,
            partial_tail=partial_tail,
        )
        segment_id = int(self._segment_id or 0)
        start_sample = self._segment_start_sample
        self._reset_segment()
        if waveform.size < self.min_segment_samples:
            return []
        result = self.receiver.predict_waveform(waveform, source_rate=self.sample_rate)
        if result.is_silence:
            return []
        return [
            StreamingPredictionEvent(
                segment_id=segment_id,
                label=result.predicted_label,
                text=result.predicted_text,
                confidence=round(result.confidence, 6),
                is_final=True,
                start_ms=self._sample_to_ms(start_sample),
                end_ms=self._sample_to_ms(max(start_sample, end_sample)),
            )
        ]

    def _build_segment_waveform(
        self,
        drop_trailing_silence: bool,
        partial_tail: np.ndarray | None = None,
    ) -> np.ndarray:
        keep_frames = len(self._segment_frames)
        if drop_trailing_silence and self._segment_silence_frames > 0:
            keep_frames = max(0, keep_frames - self._segment_silence_frames)
        parts = [frame for frame in self._segment_frames[:keep_frames]]
        if partial_tail is not None and partial_tail.size > 0:
            parts.append(partial_tail.astype(np.float32, copy=False))
        if not parts:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(parts).astype(np.float32, copy=False)

    def _candidate_from_result(self, result: Any) -> tuple[str, float] | None:
        if result.raw_top_label in (UNKNOWN_LABEL, SILENCE_LABEL):
            return None
        second_score = float(result.top_k[1]["score"]) if len(result.top_k) > 1 else 0.0
        margin = float(result.confidence) - second_score
        if float(result.confidence) < float(self.receiver.thresholds.get("confidence_threshold", 0.72)):
            return None
        if margin < float(self.receiver.thresholds.get("margin_threshold", 0.12)):
            return None
        return result.raw_top_label, float(result.confidence)

    def _sample_to_ms(self, sample_index: int) -> float:
        return round(self._base_timestamp_ms + sample_index * 1000.0 / self.sample_rate, 3)

    @staticmethod
    def _to_numpy_samples(chunk: np.ndarray | torch.Tensor) -> np.ndarray:
        if isinstance(chunk, torch.Tensor):
            array = chunk.detach().cpu().numpy()
        else:
            array = np.asarray(chunk)
        array = np.asarray(array, dtype=np.float32)
        if array.ndim > 1:
            if array.shape[0] <= 8:
                array = array.mean(axis=0)
            else:
                array = array.mean(axis=-1)
        return array.reshape(-1)

    @staticmethod
    def _frame_dbfs(frame: np.ndarray) -> float:
        if frame.size == 0:
            return -120.0
        rms = float(np.sqrt(np.mean(np.square(frame)) + 1e-12))
        return 20.0 * float(np.log10(rms + 1e-12))
