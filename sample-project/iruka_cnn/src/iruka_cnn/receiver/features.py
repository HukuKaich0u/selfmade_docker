from __future__ import annotations

import torch
import torchaudio.transforms as T_audio


class LogMelExtractor(torch.nn.Module):
    def __init__(
        self,
        sample_rate: int,
        n_fft: int,
        hop_length: int,
        n_mels: int,
        f_min: float,
        f_max: float,
        top_db: float,
    ) -> None:
        super().__init__()
        self.mel = T_audio.MelSpectrogram(
            sample_rate=sample_rate,
            n_fft=n_fft,
            hop_length=hop_length,
            n_mels=n_mels,
            f_min=f_min,
            f_max=f_max,
            power=2.0,
        )
        self.db = T_audio.AmplitudeToDB(stype="power", top_db=top_db)

    def forward(self, waveform: torch.Tensor) -> torch.Tensor:
        if waveform.dim() == 1:
            waveform = waveform.unsqueeze(0)
        mel = self.mel(waveform)
        log_mel = self.db(mel)
        mean = log_mel.mean(dim=(-2, -1), keepdim=True)
        std = log_mel.std(dim=(-2, -1), keepdim=True).clamp_min(1e-5)
        normalized = (log_mel - mean) / std
        return normalized.unsqueeze(1)
