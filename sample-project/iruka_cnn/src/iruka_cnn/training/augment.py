from __future__ import annotations

import math

import torch
import torch.nn.functional as F
import torchaudio.functional as F_audio

from iruka_cnn.receiver.preprocess import normalize_audio, trim_and_pad


class WaveformAugmentor:
    def __init__(self, sample_rate: int, clip_seconds: float, config: dict) -> None:
        self.sample_rate = sample_rate
        self.clip_seconds = clip_seconds
        self.config = config
        self.target_samples = int(sample_rate * clip_seconds)

    def __call__(self, waveform: torch.Tensor) -> torch.Tensor:
        out = waveform.clone()
        if torch.rand(1).item() < 0.9:
            gain_db = float(torch.empty(1).uniform_(-self.config["gain_db"], self.config["gain_db"]).item())
            out = out * (10.0 ** (gain_db / 20.0))
        if torch.rand(1).item() < 0.45:
            out = self._speed_perturb(out)
        if torch.rand(1).item() < 0.35:
            out = self._pitch_perturb(out)
        if torch.rand(1).item() < 0.35:
            out = self._reverb(out)
        if torch.rand(1).item() < 0.55:
            out = self._noise(out)
        if torch.rand(1).item() < 0.30:
            out = self._eq(out)
        if torch.rand(1).item() < 0.50:
            out = self._silence_jitter(out)
        out = normalize_audio(trim_and_pad(out, self.target_samples))
        return out

    def degrade(self, waveform: torch.Tensor) -> torch.Tensor:
        out = normalize_audio(self._noise(self._reverb(self._eq(waveform))))
        return trim_and_pad(out, self.target_samples)

    def _speed_perturb(self, waveform: torch.Tensor) -> torch.Tensor:
        low, high = self.config["speed_range"]
        speed = float(torch.empty(1).uniform_(low, high).item())
        resized = F.interpolate(
            waveform.view(1, 1, -1),
            scale_factor=1.0 / speed,
            mode="linear",
            align_corners=False,
        ).view(-1)
        return trim_and_pad(resized, self.target_samples)

    def _pitch_perturb(self, waveform: torch.Tensor) -> torch.Tensor:
        semitones = float(self.config["pitch_semitones"])
        shift = float(torch.empty(1).uniform_(-semitones, semitones).item())
        factor = 2.0 ** (shift / 12.0)
        shifted = F_audio.resample(
            waveform.view(1, -1),
            self.sample_rate,
            max(1, int(self.sample_rate * factor)),
        ).view(-1)
        restored = F.interpolate(
            shifted.view(1, 1, -1),
            size=waveform.numel(),
            mode="linear",
            align_corners=False,
        ).view(-1)
        return restored

    def _reverb(self, waveform: torch.Tensor) -> torch.Tensor:
        seconds = max(0.04, float(self.config["reverb_decay"]))
        impulse_len = max(64, int(self.sample_rate * seconds))
        t = torch.linspace(0.0, seconds, impulse_len)
        decay = torch.exp(-t * (12.0 / seconds))
        decay[0] = 1.0
        echo_offset = min(impulse_len - 1, max(1, impulse_len // 8))
        decay[echo_offset] += 0.4
        impulse = (decay / decay.abs().sum()).view(1, 1, -1)
        reverbed = F.conv1d(waveform.view(1, 1, -1), impulse, padding=impulse_len - 1).view(-1)
        return reverbed[: waveform.numel()]

    def _noise(self, waveform: torch.Tensor) -> torch.Tensor:
        snr_low, snr_high = self.config["noise_snr_db"]
        snr_db = float(torch.empty(1).uniform_(snr_low, snr_high).item())
        signal_power = waveform.pow(2).mean().clamp_min(1e-6)
        noise_power = signal_power / (10.0 ** (snr_db / 10.0))
        white = torch.randn_like(waveform)
        pinkish = torch.cumsum(white, dim=0)
        pinkish = pinkish - pinkish.mean()
        pinkish = pinkish / pinkish.abs().max().clamp_min(1e-6)
        return waveform + pinkish * math.sqrt(float(noise_power))

    def _eq(self, waveform: torch.Tensor) -> torch.Tensor:
        strength = float(self.config["eq_strength_db"])
        spec = torch.fft.rfft(waveform)
        freqs = torch.linspace(0.0, 1.0, spec.numel(), device=spec.device)
        low_gain = float(torch.empty(1).uniform_(-strength, strength).item())
        high_gain = float(torch.empty(1).uniform_(-strength, strength).item())
        mid_gain = float(torch.empty(1).uniform_(-strength, strength).item())
        curve_db = low_gain * (1.0 - freqs) + high_gain * freqs
        curve_db += mid_gain * torch.exp(-((freqs - 0.45) ** 2) / 0.03)
        curve = torch.pow(torch.tensor(10.0, device=spec.device), curve_db / 20.0)
        return torch.fft.irfft(spec * curve, n=waveform.numel())

    def _silence_jitter(self, waveform: torch.Tensor) -> torch.Tensor:
        max_shift = int(self.sample_rate * float(self.config["silence_jitter_ms"]) / 1000.0)
        shift = int(torch.randint(-max_shift, max_shift + 1, (1,)).item())
        if shift == 0:
            return waveform
        out = torch.zeros_like(waveform)
        if shift > 0:
            out[shift:] = waveform[:-shift]
        else:
            out[:shift] = waveform[-shift:]
        return out


class FeatureAugmentor:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.gain_db = float(config.get("feature_gain_db", 1.5))
        self.noise_std = float(config.get("feature_noise_std", 0.025))
        self.time_shift_frames = int(config.get("feature_time_shift_frames", 12))
        self.time_mask_max_frames = int(config.get("feature_time_mask_max_frames", 18))
        self.freq_mask_max_bins = int(config.get("feature_freq_mask_max_bins", 6))
        self.mel_shift_max_bins = int(config.get("feature_mel_shift_max_bins", 2))

    def __call__(
        self,
        features: torch.Tensor,
        labels: torch.Tensor | None = None,
        silence_index: int | None = None,
    ) -> torch.Tensor:
        out = features.clone()
        if out.ndim != 4:
            raise ValueError(f"feature tensor must be 4D, got shape={tuple(out.shape)}")
        active_indices = self._active_indices(out, labels=labels, silence_index=silence_index)
        if active_indices.numel() == 0:
            return out
        out = self._apply_gain(out, active_indices)
        out = self._apply_noise(out, active_indices)
        out = self._apply_roll_and_masks(out, active_indices)
        return out

    def _active_indices(
        self,
        features: torch.Tensor,
        labels: torch.Tensor | None,
        silence_index: int | None,
    ) -> torch.Tensor:
        active_mask = torch.ones(features.shape[0], dtype=torch.bool, device=features.device)
        if labels is not None and silence_index is not None:
            active_mask = labels != silence_index
        return active_mask.nonzero(as_tuple=True)[0]

    def _apply_gain(self, features: torch.Tensor, active_indices: torch.Tensor) -> torch.Tensor:
        gain_db = torch.empty(active_indices.numel(), 1, 1, 1, device=features.device).uniform_(
            -self.gain_db,
            self.gain_db,
        )
        gain = torch.pow(torch.full_like(gain_db, 10.0), gain_db / 20.0)
        features[active_indices] = features[active_indices] * gain
        return features

    def _apply_noise(self, features: torch.Tensor, active_indices: torch.Tensor) -> torch.Tensor:
        noise_scale = torch.empty(active_indices.numel(), 1, 1, 1, device=features.device).uniform_(
            0.0,
            self.noise_std,
        )
        features[active_indices] = features[active_indices] + torch.randn_like(features[active_indices]) * noise_scale
        return features

    def _apply_roll_and_masks(self, features: torch.Tensor, active_indices: torch.Tensor) -> torch.Tensor:
        for index in active_indices.tolist():
            sample = features[index]
            if self.time_shift_frames > 0:
                shift = int(torch.randint(-self.time_shift_frames, self.time_shift_frames + 1, (1,), device=features.device).item())
                if shift != 0:
                    sample = torch.roll(sample, shifts=shift, dims=-1)
            if self.mel_shift_max_bins > 0:
                mel_shift = int(torch.randint(-self.mel_shift_max_bins, self.mel_shift_max_bins + 1, (1,), device=features.device).item())
                if mel_shift != 0:
                    sample = torch.roll(sample, shifts=mel_shift, dims=-2)
            if self.time_mask_max_frames > 0:
                mask_width = int(torch.randint(0, self.time_mask_max_frames + 1, (1,), device=features.device).item())
                if mask_width > 0 and mask_width < sample.shape[-1]:
                    start = int(torch.randint(0, sample.shape[-1] - mask_width + 1, (1,), device=features.device).item())
                    sample[:, :, start : start + mask_width] = 0.0
            if self.freq_mask_max_bins > 0:
                mask_height = int(torch.randint(0, self.freq_mask_max_bins + 1, (1,), device=features.device).item())
                if mask_height > 0 and mask_height < sample.shape[-2]:
                    start = int(torch.randint(0, sample.shape[-2] - mask_height + 1, (1,), device=features.device).item())
                    sample[:, start : start + mask_height, :] = 0.0
            features[index] = sample
        return features
