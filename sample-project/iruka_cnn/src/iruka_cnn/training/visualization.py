from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np
import torch
import torchaudio.transforms as T_audio

from iruka_cnn.common.io import ensure_parent
from iruka_cnn.receiver.features import LogMelExtractor
from iruka_cnn.receiver.preprocess import preprocess_waveform


_NON_INTERACTIVE_BACKENDS = {"agg", "pdf", "ps", "svg", "cairo", "template"}


def env_flag(name: str) -> bool:
    value = os.getenv(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def default_visualization_output_path(output_dir: str | Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(output_dir) / f"visualize_{timestamp}.png"


@dataclass(frozen=True)
class AudioVisualizationResult:
    output_path: Path
    source_sample_rate: int
    model_sample_rate: int
    audio_stats: dict[str, float]


class TrainPlotter:
    def __init__(
        self,
        output_path: str | Path,
        warn_callback: Callable[[str], None] | None = None,
        batch_window: int = 25,
    ) -> None:
        self.output_path = ensure_parent(output_path)
        self.warn_callback = warn_callback
        self.batch_window = max(1, int(batch_window))
        self.batch_steps: list[int] = []
        self.batch_losses: list[float] = []
        self.batch_accuracies: list[float] = []
        self.epochs: list[int] = []
        self.train_epoch_loss: list[float] = []
        self.val_epoch_loss: list[float] = []
        self.train_epoch_acc: list[float] = []
        self.val_epoch_acc: list[float] = []
        self.val_macro_f1: list[float] = []

        import matplotlib

        self._matplotlib = matplotlib
        self._show_window = True
        self._plt = self._load_pyplot(prefer_interactive=True)
        self._figure = None
        self._axes = None
        self._create_figure()

    @property
    def backend(self) -> str:
        return str(self._plt.get_backend())

    @property
    def show_window(self) -> bool:
        return self._show_window

    def update_batch(self, global_step: int, loss: float, accuracy: float) -> None:
        self.batch_steps.append(int(global_step))
        self.batch_losses.append(float(loss))
        self.batch_accuracies.append(float(accuracy))

    def update_epoch(
        self,
        epoch: int,
        train_loss: float,
        val_loss: float,
        train_accuracy: float,
        val_accuracy: float,
        val_macro_f1: float,
    ) -> None:
        self.epochs.append(int(epoch))
        self.train_epoch_loss.append(float(train_loss))
        self.val_epoch_loss.append(float(val_loss))
        self.train_epoch_acc.append(float(train_accuracy))
        self.val_epoch_acc.append(float(val_accuracy))
        self.val_macro_f1.append(float(val_macro_f1))

    def redraw(self) -> None:
        self._render()

    def close(self) -> None:
        self._render()
        try:
            self._plt.ioff()
        except Exception:
            pass
        if self._figure is not None:
            self._plt.close(self._figure)

    def _load_pyplot(self, prefer_interactive: bool):
        import matplotlib.pyplot as plt

        backend = str(plt.get_backend())
        if prefer_interactive and self._is_non_interactive_backend(backend):
            self._show_window = False
            self._warn(f"[plot] backend={backend} のため PNG-only で継続します。")
        else:
            self._show_window = prefer_interactive
        if self._show_window:
            try:
                plt.ion()
            except Exception as exc:
                self._show_window = False
                self._warn(f"[plot] interactive mode 初期化に失敗したため PNG-only へ切り替えます: {exc}")
        return plt

    def _create_figure(self) -> None:
        self._figure, self._axes = self._plt.subplots(2, 2, figsize=(12, 8))
        self._figure.suptitle("Training Live Metrics")

    def _render(self) -> None:
        if self._figure is None or self._axes is None:
            self._create_figure()
        try:
            self._draw_axes()
            self._figure.tight_layout()
            self._figure.subplots_adjust(top=0.92)
            self._figure.savefig(self.output_path, dpi=160)
            if self._show_window:
                self._figure.canvas.draw_idle()
                self._figure.canvas.flush_events()
                self._plt.pause(0.001)
        except Exception as exc:
            if self._show_window and self._fallback_to_png_only(exc):
                self._draw_axes()
                self._figure.tight_layout()
                self._figure.subplots_adjust(top=0.92)
                self._figure.savefig(self.output_path, dpi=160)

    def _draw_axes(self) -> None:
        axes = self._axes
        assert axes is not None
        for ax in axes.flat:
            ax.clear()
            ax.grid(alpha=0.3)

        loss_x, loss_y = self._moving_average(self.batch_steps, self.batch_losses)
        acc_x, acc_y = self._moving_average(self.batch_steps, self.batch_accuracies)

        axes[0, 0].plot(loss_x, loss_y, color="tab:red")
        axes[0, 0].set_title("Train Batch Loss (moving avg)")
        axes[0, 0].set_xlabel("Global batch")
        axes[0, 0].set_ylabel("Loss")

        axes[0, 1].plot(acc_x, acc_y, color="tab:green")
        axes[0, 1].set_title("Train Batch Accuracy (moving avg)")
        axes[0, 1].set_xlabel("Global batch")
        axes[0, 1].set_ylabel("Accuracy")
        axes[0, 1].set_ylim(0.0, 1.02)

        if self.epochs:
            axes[1, 0].plot(self.epochs, self.train_epoch_loss, label="train_loss", marker="o", color="tab:red")
            axes[1, 0].plot(self.epochs, self.val_epoch_loss, label="val_loss", marker="o", color="tab:orange")
            axes[1, 0].set_title("Epoch Loss")
            axes[1, 0].set_xlabel("Epoch")
            axes[1, 0].set_ylabel("Loss")
            axes[1, 0].legend()

            axes[1, 1].plot(self.epochs, self.train_epoch_acc, label="train_acc", marker="o", color="tab:green")
            axes[1, 1].plot(self.epochs, self.val_epoch_acc, label="val_acc", marker="o", color="tab:blue")
            axes[1, 1].plot(self.epochs, self.val_macro_f1, label="val_macro_f1", marker="o", color="tab:purple")
            axes[1, 1].set_title("Epoch Metrics")
            axes[1, 1].set_xlabel("Epoch")
            axes[1, 1].set_ylabel("Score")
            axes[1, 1].set_ylim(0.0, 1.02)
            axes[1, 1].legend()

    def _fallback_to_png_only(self, exc: Exception) -> bool:
        try:
            self._warn(f"[plot] GUI backend 描画に失敗したため PNG-only へ切り替えます: {exc}")
            self._plt.close(self._figure)
            self._plt.switch_backend("Agg")
            self._show_window = False
            self._create_figure()
            return True
        except Exception as fallback_exc:
            self._warn(f"[plot] PNG-only へのフォールバックにも失敗しました: {fallback_exc}")
            return False

    def _moving_average(self, steps: list[int], values: list[float]) -> tuple[np.ndarray, np.ndarray]:
        if not steps or not values:
            return np.asarray([], dtype=np.float32), np.asarray([], dtype=np.float32)
        window = min(self.batch_window, len(values))
        if window == 1:
            return np.asarray(steps, dtype=np.float32), np.asarray(values, dtype=np.float32)
        kernel = np.ones(window, dtype=np.float32) / window
        averaged = np.convolve(np.asarray(values, dtype=np.float32), kernel, mode="valid")
        return np.asarray(steps[window - 1 :], dtype=np.float32), averaged

    def _warn(self, message: str) -> None:
        if self.warn_callback is not None:
            self.warn_callback(message)

    @staticmethod
    def _is_non_interactive_backend(backend: str) -> bool:
        return backend.strip().lower() in _NON_INTERACTIVE_BACKENDS


def maybe_create_train_plotter(
    output_path: str | Path,
    warn_callback: Callable[[str], None] | None = None,
) -> TrainPlotter | None:
    if not env_flag("IRUKA_ENABLE_TRAIN_PLOTS"):
        return None
    try:
        return TrainPlotter(output_path=output_path, warn_callback=warn_callback)
    except Exception as exc:
        if warn_callback is not None:
            warn_callback(f"[plot] live plot 初期化に失敗したため無効化します: {exc}")
        return None


def render_audio_overview(
    waveform: np.ndarray | torch.Tensor,
    source_rate: int,
    config: dict,
    output_path: str | Path,
    title: str,
    show: bool = False,
) -> AudioVisualizationResult:
    import matplotlib

    if not show and "MPLBACKEND" not in os.environ:
        matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    processed, audio_stats = preprocess_waveform(
        waveform=waveform,
        source_rate=source_rate,
        sample_rate=int(config["audio"]["sample_rate"]),
        clip_seconds=float(config["audio"]["clip_seconds"]),
    )
    processed = processed.detach().cpu().to(dtype=torch.float32)
    sample_rate = int(config["audio"]["sample_rate"])
    linear_db = _linear_spectrogram_db(
        processed,
        n_fft=int(config["features"]["n_fft"]),
        hop_length=int(config["features"]["hop_length"]),
    )
    mel_db = _mel_spectrogram_db(processed, config)
    model_input = _model_input_log_mel(processed, config)

    time_axis = np.arange(processed.shape[-1], dtype=np.float32) / float(sample_rate)
    output = ensure_parent(output_path)
    fig, axes = plt.subplots(2, 2, figsize=(14, 9))
    fig.suptitle(title)

    axes[0, 0].plot(time_axis, processed.cpu().numpy(), color="tab:blue", linewidth=0.8)
    axes[0, 0].set_title("Waveform (model input)")
    axes[0, 0].set_xlabel("Seconds")
    axes[0, 0].set_ylabel("Amplitude")
    axes[0, 0].grid(alpha=0.3)

    _imshow_feature(
        axes[0, 1],
        linear_db,
        title="Linear Spectrogram (dB)",
        xlabel="Frames",
        ylabel="Frequency bins",
    )
    _imshow_feature(
        axes[1, 0],
        mel_db,
        title="Mel Spectrogram (dB)",
        xlabel="Frames",
        ylabel="Mel bins",
    )
    _imshow_feature(
        axes[1, 1],
        model_input,
        title="Model Input Log-Mel (normalized)",
        xlabel="Frames",
        ylabel="Mel bins",
    )

    fig.tight_layout()
    fig.subplots_adjust(top=0.92)
    fig.savefig(output, dpi=180)
    if show:
        plt.show()
    plt.close(fig)

    return AudioVisualizationResult(
        output_path=Path(output),
        source_sample_rate=int(source_rate),
        model_sample_rate=sample_rate,
        audio_stats=audio_stats,
    )


def _linear_spectrogram_db(waveform: torch.Tensor, n_fft: int, hop_length: int) -> np.ndarray:
    window = torch.hann_window(n_fft, dtype=waveform.dtype, device=waveform.device)
    stft = torch.stft(
        waveform,
        n_fft=n_fft,
        hop_length=hop_length,
        window=window,
        return_complex=True,
    )
    magnitude = stft.abs().clamp_min(1e-6)
    db = 20.0 * torch.log10(magnitude)
    return db.cpu().numpy()


def _mel_spectrogram_db(waveform: torch.Tensor, config: dict) -> np.ndarray:
    mel = T_audio.MelSpectrogram(
        sample_rate=int(config["audio"]["sample_rate"]),
        n_fft=int(config["features"]["n_fft"]),
        hop_length=int(config["features"]["hop_length"]),
        n_mels=int(config["features"]["n_mels"]),
        f_min=float(config["features"]["f_min"]),
        f_max=float(config["features"]["f_max"]),
        power=2.0,
    )(waveform.unsqueeze(0))
    mel_db = T_audio.AmplitudeToDB(stype="power", top_db=float(config["features"]["top_db"]))(mel)
    return mel_db.squeeze(0).cpu().numpy()


def _model_input_log_mel(waveform: torch.Tensor, config: dict) -> np.ndarray:
    extractor = LogMelExtractor(
        sample_rate=int(config["audio"]["sample_rate"]),
        n_fft=int(config["features"]["n_fft"]),
        hop_length=int(config["features"]["hop_length"]),
        n_mels=int(config["features"]["n_mels"]),
        f_min=float(config["features"]["f_min"]),
        f_max=float(config["features"]["f_max"]),
        top_db=float(config["features"]["top_db"]),
    )
    features = extractor(waveform.unsqueeze(0))
    return features.squeeze(0).squeeze(0).cpu().numpy()


def _imshow_feature(ax, data: np.ndarray, title: str, xlabel: str, ylabel: str) -> None:
    image = ax.imshow(data, origin="lower", aspect="auto", interpolation="nearest", cmap="magma")
    ax.set_title(title)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.figure.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
