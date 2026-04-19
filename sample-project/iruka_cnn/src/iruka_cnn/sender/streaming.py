from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Sequence

import numpy as np

from iruka_cnn.common.labels import Phrase, PhraseDictionary
from iruka_cnn.common.utils import stable_seed
from iruka_cnn.sender.generator import DolphinWhistleGenerator


_DROPPABLE_CHARS = " \t\r\n　、。！？!?.,，．"


@dataclass(frozen=True)
class AudioChunk:
    samples: np.ndarray
    start_ms: float
    end_ms: float


@dataclass(frozen=True)
class PhraseStreamBuildResult:
    waveform: np.ndarray
    sample_rate: int
    emitted_texts: list[str]
    emitted_keys: list[str]
    dropped_fragments: list[str]


class DolphinPhraseStreamer:
    def __init__(
        self,
        dictionary: PhraseDictionary,
        generator: DolphinWhistleGenerator,
        segment_gap_ms: int = 300,
    ) -> None:
        self.dictionary = dictionary
        self.generator = generator
        self.segment_gap_ms = max(0, int(segment_gap_ms))

    def synthesize_phrase_events(
        self,
        phrase_texts: Sequence[str],
        seed: int | None = None,
    ) -> PhraseStreamBuildResult:
        phrases: list[Phrase] = []
        dropped: list[str] = []
        for text in phrase_texts:
            try:
                phrases.append(self.dictionary.get_by_text(text))
            except KeyError:
                normalized = self._normalize_fragment(text)
                if normalized:
                    dropped.append(normalized)
        return self._render_phrases(phrases=phrases, dropped_fragments=dropped, seed=seed)

    def synthesize_text(
        self,
        text: str,
        seed: int | None = None,
    ) -> PhraseStreamBuildResult:
        phrases, dropped_fragments = self.extract_registered_phrases(text)
        return self._render_phrases(phrases=phrases, dropped_fragments=dropped_fragments, seed=seed)

    def extract_registered_phrases(self, text: str) -> tuple[list[Phrase], list[str]]:
        phrases = sorted(self.dictionary.phrases, key=lambda item: len(item.text), reverse=True)
        emitted: list[Phrase] = []
        dropped: list[str] = []
        pending_fragment: list[str] = []
        cursor = 0
        while cursor < len(text):
            match = next((phrase for phrase in phrases if text.startswith(phrase.text, cursor)), None)
            if match is None:
                pending_fragment.append(text[cursor])
                cursor += 1
                continue
            normalized = self._normalize_fragment("".join(pending_fragment))
            if normalized:
                dropped.append(normalized)
            pending_fragment.clear()
            emitted.append(match)
            cursor += len(match.text)
        normalized = self._normalize_fragment("".join(pending_fragment))
        if normalized:
            dropped.append(normalized)
        return emitted, dropped

    def iter_phrase_event_chunks(
        self,
        phrase_texts: Sequence[str],
        chunk_ms: int = 20,
        seed: int | None = None,
    ) -> Iterator[AudioChunk]:
        result = self.synthesize_phrase_events(phrase_texts=phrase_texts, seed=seed)
        yield from self.iter_audio_chunks(result.waveform, chunk_ms=chunk_ms)

    def iter_text_chunks(
        self,
        text: str,
        chunk_ms: int = 20,
        seed: int | None = None,
    ) -> Iterator[AudioChunk]:
        result = self.synthesize_text(text=text, seed=seed)
        yield from self.iter_audio_chunks(result.waveform, chunk_ms=chunk_ms)

    def iter_audio_chunks(
        self,
        waveform: np.ndarray,
        chunk_ms: int = 20,
    ) -> Iterator[AudioChunk]:
        chunk_samples = max(1, int(self.generator.sample_rate * chunk_ms / 1000.0))
        total_samples = int(waveform.shape[0])
        for start in range(0, total_samples, chunk_samples):
            end = min(total_samples, start + chunk_samples)
            yield AudioChunk(
                samples=waveform[start:end].astype(np.float32, copy=False),
                start_ms=start * 1000.0 / self.generator.sample_rate,
                end_ms=end * 1000.0 / self.generator.sample_rate,
            )

    def _render_phrases(
        self,
        phrases: Sequence[Phrase],
        dropped_fragments: Sequence[str],
        seed: int | None = None,
    ) -> PhraseStreamBuildResult:
        parts: list[np.ndarray] = []
        gap = np.zeros(int(self.generator.sample_rate * self.segment_gap_ms / 1000.0), dtype=np.float32)
        for index, phrase in enumerate(phrases):
            resolved_seed = None if seed is None else stable_seed(f"stream:{seed}:{phrase.key}:{index}")
            signal = self.generator.generate(phrase=phrase, seed=resolved_seed)
            parts.append(signal.waveform.astype(np.float32, copy=False))
            if index < len(phrases) - 1 and gap.size > 0:
                parts.append(gap.copy())
        waveform = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
        return PhraseStreamBuildResult(
            waveform=waveform.astype(np.float32, copy=False),
            sample_rate=self.generator.sample_rate,
            emitted_texts=[phrase.text for phrase in phrases],
            emitted_keys=[phrase.key for phrase in phrases],
            dropped_fragments=list(dropped_fragments),
        )

    @staticmethod
    def _normalize_fragment(fragment: str) -> str:
        return fragment.strip(_DROPPABLE_CHARS)
