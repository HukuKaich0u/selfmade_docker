from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from iruka_cnn.common.labels import Phrase
from iruka_cnn.common.utils import stable_seed


@dataclass(frozen=True)
class SyllableTemplate:
    duration: float
    gap_after: float
    start_hz: float
    end_hz: float
    curve: float
    harmonic_mix: tuple[float, float, float]
    tremolo_hz: float
    vibrato_hz: float
    vibrato_depth: float


@dataclass(frozen=True)
class PhraseTemplate:
    phrase_key: str
    lead_silence: float
    trail_silence: float
    noise_mix: float
    syllables: tuple[SyllableTemplate, ...]


def template_from_phrase(phrase: Phrase) -> PhraseTemplate:
    rng = np.random.default_rng(stable_seed(f"{phrase.key}:{phrase.text}"))
    syllable_count = int(rng.integers(2, 5))
    syllables: list[SyllableTemplate] = []
    base_hz = float(rng.uniform(3200.0, 7600.0))
    for idx in range(syllable_count):
        start_hz = float(np.clip(base_hz + rng.normal(0.0, 650.0) + idx * rng.uniform(-160.0, 220.0), 2400.0, 9800.0))
        end_hz = float(np.clip(start_hz + rng.normal(0.0, 900.0), 2200.0, 10200.0))
        harmonic_a = float(rng.uniform(0.70, 0.92))
        harmonic_b = float(rng.uniform(0.08, 0.22))
        harmonic_c = max(0.02, 1.0 - harmonic_a - harmonic_b)
        syllables.append(
            SyllableTemplate(
                duration=float(rng.uniform(0.18, 0.48)),
                gap_after=float(rng.uniform(0.04, 0.20)),
                start_hz=start_hz,
                end_hz=end_hz,
                curve=float(rng.uniform(-0.9, 0.9)),
                harmonic_mix=(harmonic_a, harmonic_b, harmonic_c),
                tremolo_hz=float(rng.uniform(2.0, 8.0)),
                vibrato_hz=float(rng.uniform(5.0, 14.0)),
                vibrato_depth=float(rng.uniform(0.006, 0.025)),
            )
        )
    return PhraseTemplate(
        phrase_key=phrase.key,
        lead_silence=float(rng.uniform(0.06, 0.18)),
        trail_silence=float(rng.uniform(0.10, 0.24)),
        noise_mix=float(rng.uniform(0.003, 0.020)),
        syllables=tuple(syllables),
    )
