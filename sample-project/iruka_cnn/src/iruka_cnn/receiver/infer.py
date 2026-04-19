from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch

from iruka_cnn.common.device import resolve_device
from iruka_cnn.common.labels import SILENCE_LABEL, UNKNOWN_LABEL
from iruka_cnn.receiver.features import LogMelExtractor
from iruka_cnn.receiver.model import SpectrogramCNN
from iruka_cnn.receiver.preprocess import load_and_preprocess, preprocess_waveform


@dataclass
class InferenceResult:
    predicted_label: str
    predicted_text: str
    confidence: float
    raw_top_label: str
    top_k: list[dict[str, float]]
    is_unknown: bool
    is_silence: bool
    embedding: list[float] | None
    audio_stats: dict[str, float]


class Receiver:
    def __init__(self, checkpoint_path: str | Path, device_name: str = "auto") -> None:
        checkpoint = torch.load(Path(checkpoint_path), map_location="cpu", weights_only=False)
        self.config = checkpoint["config"]
        self.label_vocab = checkpoint["label_vocab"]
        self.labels: list[str] = list(self.label_vocab["labels"])
        self.device = resolve_device(device_name or self.config["training"].get("device", "auto"))
        self.feature_extractor = LogMelExtractor(
            sample_rate=self.config["audio"]["sample_rate"],
            n_fft=self.config["features"]["n_fft"],
            hop_length=self.config["features"]["hop_length"],
            n_mels=self.config["features"]["n_mels"],
            f_min=self.config["features"]["f_min"],
            f_max=self.config["features"]["f_max"],
            top_db=self.config["features"]["top_db"],
        ).to(self.device)
        self.model = SpectrogramCNN(
            num_classes=len(self.labels),
            embedding_dim=self.config["training"]["embedding_dim"],
        ).to(self.device)
        self.model.load_state_dict(checkpoint["model_state"])
        self.model.eval()
        self.thresholds = checkpoint.get("thresholds", self.config.get("inference", {}))

    def predict_file(self, path: str | Path, include_embedding: bool = False) -> InferenceResult:
        waveform, audio_stats = load_and_preprocess(
            path=path,
            sample_rate=self.config["audio"]["sample_rate"],
            clip_seconds=self.config["audio"]["clip_seconds"],
        )
        return self._predict_preprocessed(waveform, audio_stats=audio_stats, include_embedding=include_embedding)

    def predict_waveform(
        self,
        waveform: np.ndarray | torch.Tensor,
        source_rate: int | None = None,
        include_embedding: bool = False,
    ) -> InferenceResult:
        processed, audio_stats = preprocess_waveform(
            waveform=waveform,
            source_rate=source_rate or int(self.config["audio"]["sample_rate"]),
            sample_rate=self.config["audio"]["sample_rate"],
            clip_seconds=self.config["audio"]["clip_seconds"],
        )
        return self._predict_preprocessed(processed, audio_stats=audio_stats, include_embedding=include_embedding)

    def _predict_preprocessed(
        self,
        waveform: torch.Tensor,
        audio_stats: dict[str, float],
        include_embedding: bool = False,
    ) -> InferenceResult:
        silence_threshold = float(self.config["audio"]["silence_threshold_dbfs"])
        if float(audio_stats["rms_dbfs"]) <= silence_threshold:
            return InferenceResult(
                predicted_label=SILENCE_LABEL,
                predicted_text=SILENCE_LABEL,
                confidence=1.0,
                raw_top_label=SILENCE_LABEL,
                top_k=[{"label": SILENCE_LABEL, "score": 1.0}],
                is_unknown=False,
                is_silence=True,
                embedding=None,
                audio_stats=audio_stats,
            )
        with torch.inference_mode():
            batch = waveform.unsqueeze(0).to(self.device)
            features = self.feature_extractor(batch)
            logits, embedding = self.model(features)
            probs = torch.softmax(logits, dim=-1).squeeze(0)
        top_scores, top_indices = torch.topk(
            probs,
            k=min(int(self.thresholds.get("top_k", 5)), probs.numel()),
        )
        top_k = [
            {"label": self.labels[int(index)], "score": float(score)}
            for score, index in zip(top_scores.cpu().tolist(), top_indices.cpu().tolist(), strict=True)
        ]
        raw_top_label = top_k[0]["label"]
        confidence = float(top_k[0]["score"])
        margin = confidence - float(top_k[1]["score"]) if len(top_k) > 1 else confidence
        predicted_label = raw_top_label
        if raw_top_label not in (UNKNOWN_LABEL, SILENCE_LABEL):
            if confidence < float(self.thresholds.get("confidence_threshold", 0.72)):
                predicted_label = UNKNOWN_LABEL
            elif margin < float(self.thresholds.get("margin_threshold", 0.12)):
                predicted_label = UNKNOWN_LABEL
        return InferenceResult(
            predicted_label=predicted_label,
            predicted_text=predicted_label,
            confidence=confidence,
            raw_top_label=raw_top_label,
            top_k=top_k,
            is_unknown=predicted_label == UNKNOWN_LABEL,
            is_silence=predicted_label == SILENCE_LABEL,
            embedding=embedding.squeeze(0).cpu().tolist() if include_embedding else None,
            audio_stats=audio_stats,
        )
