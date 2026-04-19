from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from iruka_cnn.common.labels import Phrase
from iruka_cnn.common.utils import rng_from_seed, stable_seed
from iruka_cnn.sender.templates import PhraseTemplate, SyllableTemplate, template_from_phrase


@dataclass
class GeneratedSignal:
    waveform: np.ndarray
    sample_rate: int
    duration_seconds: float
    phrase_text: str
    phrase_key: str
    seed: int


class DolphinWhistleGenerator:
    def __init__(
        self,
        sample_rate: int = 24000,
        min_duration_seconds: float = 1.0,
        max_duration_seconds: float = 2.5,
    ) -> None:
        self.sample_rate = sample_rate
        self.min_duration_seconds = min_duration_seconds
        self.max_duration_seconds = max_duration_seconds

    def generate(self, phrase: Phrase, seed: int | None = None) -> GeneratedSignal:
        resolved_seed = seed if seed is not None else stable_seed(f"variation:{phrase.key}:{np.random.randint(0, 1_000_000)}")
        rng = rng_from_seed(resolved_seed)
        template = template_from_phrase(phrase)
        waveform = self._fit_duration(self._render_template(template=template, rng=rng))
        peak = np.max(np.abs(waveform))
        if peak > 0:
            waveform = waveform / peak * 0.92
        return GeneratedSignal(
            waveform=waveform.astype(np.float32),
            sample_rate=self.sample_rate,
            duration_seconds=float(len(waveform) / self.sample_rate),
            phrase_text=phrase.text,
            phrase_key=phrase.key,
            seed=resolved_seed,
        )

    def generate_unknown(self, seed: int | None = None) -> GeneratedSignal:
        phrase = Phrase(key="unknown", text="unknown")
        resolved_seed = seed if seed is not None else stable_seed(f"unknown:{np.random.randint(0, 1_000_000)}")
        rng = rng_from_seed(resolved_seed)
        synthetic_phrase = Phrase(
            key=f"unknown_{resolved_seed}",
            text="未登録パターン",
        )
        template = template_from_phrase(synthetic_phrase)
        waveform = self._fit_duration(self._render_template(template, rng, unknown_mode=True))
        peak = np.max(np.abs(waveform))
        if peak > 0:
            waveform = waveform / peak * 0.85
        return GeneratedSignal(
            waveform=waveform.astype(np.float32),
            sample_rate=self.sample_rate,
            duration_seconds=float(len(waveform) / self.sample_rate),
            phrase_text=phrase.text,
            phrase_key=phrase.key,
            seed=resolved_seed,
        )

    def generate_silence(self, duration_seconds: float = 2.5, seed: int | None = None) -> GeneratedSignal:
        resolved_seed = seed if seed is not None else 0
        rng = rng_from_seed(resolved_seed)
        samples = int(duration_seconds * self.sample_rate)
        floor_noise = rng.normal(0.0, 0.0003, samples).astype(np.float32)
        return GeneratedSignal(
            waveform=floor_noise,
            sample_rate=self.sample_rate,
            duration_seconds=duration_seconds,
            phrase_text="silence",
            phrase_key="silence",
            seed=resolved_seed,
        )

    def _render_template(
        self,
        template: PhraseTemplate,
        rng: np.random.Generator,
        unknown_mode: bool = False,
    ) -> np.ndarray:
        parts: list[np.ndarray] = []
        parts.append(np.zeros(int(self.sample_rate * self._vary(template.lead_silence, rng, 0.25)), dtype=np.float32))
        for syllable in template.syllables:
            rendered = self._render_syllable(syllable, rng=rng, unknown_mode=unknown_mode)
            parts.append(rendered)
            parts.append(np.zeros(int(self.sample_rate * self._vary(syllable.gap_after, rng, 0.35)), dtype=np.float32))
        parts.append(np.zeros(int(self.sample_rate * self._vary(template.trail_silence, rng, 0.25)), dtype=np.float32))
        waveform = np.concatenate(parts) if parts else np.zeros(1, dtype=np.float32)
        colored_noise = self._colored_noise(len(waveform), rng) * self._vary(template.noise_mix, rng, 0.6)
        waveform = waveform + colored_noise.astype(np.float32)
        if unknown_mode:
            glitch = self._glitch_bursts(len(waveform), rng)
            waveform = waveform * rng.uniform(0.85, 1.05) + glitch
        return waveform.astype(np.float32)

    def _render_syllable(
        self,
        syllable: SyllableTemplate,
        rng: np.random.Generator,
        unknown_mode: bool,
    ) -> np.ndarray:
        duration = max(0.08, self._vary(syllable.duration, rng, 0.18))
        samples = max(8, int(duration * self.sample_rate))
        t = np.linspace(0.0, duration, samples, endpoint=False, dtype=np.float32)
        interp = np.linspace(0.0, 1.0, samples, endpoint=False, dtype=np.float32)
        curvature = np.power(interp, 1.0 + syllable.curve)
        freq = syllable.start_hz + (syllable.end_hz - syllable.start_hz) * curvature
        freq *= 1.0 + np.sin(2.0 * np.pi * self._vary(syllable.vibrato_hz, rng, 0.15) * t) * self._vary(syllable.vibrato_depth, rng, 0.30)
        if unknown_mode:
            freq *= 1.0 + 0.025 * np.sign(np.sin(2.0 * np.pi * rng.uniform(18.0, 40.0) * t))
        phase = 2.0 * np.pi * np.cumsum(freq) / self.sample_rate
        harmonics = np.zeros(samples, dtype=np.float32)
        for idx, amp in enumerate(syllable.harmonic_mix, start=1):
            phase_shift = rng.uniform(0.0, 2.0 * np.pi)
            harmonics += np.sin(idx * phase + phase_shift).astype(np.float32) * amp
        tremolo = 0.85 + 0.15 * np.sin(2.0 * np.pi * self._vary(syllable.tremolo_hz, rng, 0.25) * t)
        env = np.sin(np.pi * interp) ** rng.uniform(0.65, 1.35)
        env *= tremolo.astype(np.float32)
        return (harmonics * env).astype(np.float32)

    def _colored_noise(self, samples: int, rng: np.random.Generator) -> np.ndarray:
        white = rng.normal(0.0, 1.0, samples)
        pinkish = np.cumsum(white)
        pinkish = pinkish - pinkish.mean()
        scale = np.max(np.abs(pinkish)) or 1.0
        return (pinkish / scale).astype(np.float32)

    def _glitch_bursts(self, samples: int, rng: np.random.Generator) -> np.ndarray:
        burst = np.zeros(samples, dtype=np.float32)
        for _ in range(int(rng.integers(1, 4))):
            start = int(rng.integers(0, max(samples - 1, 1)))
            length = int(rng.integers(self.sample_rate // 100, self.sample_rate // 30))
            end = min(samples, start + length)
            noise = rng.normal(0.0, rng.uniform(0.02, 0.08), end - start)
            burst[start:end] += noise.astype(np.float32)
        return burst

    @staticmethod
    def _vary(value: float, rng: np.random.Generator, ratio: float) -> float:
        return float(value * (1.0 + rng.uniform(-ratio, ratio)))

    def _fit_duration(self, waveform: np.ndarray) -> np.ndarray:
        min_samples = int(self.sample_rate * self.min_duration_seconds)
        max_samples = int(self.sample_rate * self.max_duration_seconds)
        if waveform.shape[0] > max_samples:
            ratio = max_samples / waveform.shape[0]
            x_old = np.linspace(0.0, 1.0, waveform.shape[0], endpoint=False)
            x_new = np.linspace(0.0, 1.0, max_samples, endpoint=False)
            waveform = np.interp(x_new, x_old, waveform).astype(np.float32)
        if waveform.shape[0] < min_samples:
            pad_total = min_samples - waveform.shape[0]
            left = pad_total // 2
            right = pad_total - left
            waveform = np.pad(waveform, (left, right))
        return waveform.astype(np.float32)
