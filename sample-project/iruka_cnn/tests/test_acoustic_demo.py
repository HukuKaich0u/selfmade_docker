from __future__ import annotations

import threading
import time
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from iruka_cnn.demo import acoustic


class DummyReceiver:
    def __init__(self, checkpoint_path: str | Path, device_name: str = "auto") -> None:
        del checkpoint_path, device_name
        self.config = {
            "audio": {
                "sample_rate": 24000,
                "silence_threshold_dbfs": -48.0,
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
        del source_rate, include_embedding
        samples = np.asarray(waveform, dtype=np.float32).reshape(-1)
        mean = float(samples.mean()) if samples.size else 0.0
        if mean > 0.05:
            label = "了解しました"
            score = 0.91
        elif mean < -0.05:
            label = "停止してください"
            score = 0.9
        else:
            label = "unknown"
            score = 0.82
        second_label = "停止してください" if label == "了解しました" else "了解しました"
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


class FakeGenerator:
    def __init__(self, sample_rate: int, min_duration_seconds: float, max_duration_seconds: float) -> None:
        del min_duration_seconds, max_duration_seconds
        self.sample_rate = sample_rate

    def generate(self, phrase, seed=None):
        del seed
        amplitude = 0.8 if phrase.text == "了解しました" else -0.8
        return SimpleNamespace(
            waveform=np.full(int(self.sample_rate * 1.6), amplitude, dtype=np.float32),
        )


class FakeStatus:
    def __bool__(self) -> bool:
        return False

    def __str__(self) -> str:
        return "ok"


class FakeSoundDevice:
    class CallbackStop(Exception):
        pass

    def __init__(self) -> None:
        self._devices = [
            {
                "name": "Built-in Microphone",
                "max_input_channels": 1,
                "max_output_channels": 0,
                "default_samplerate": 24000.0,
            },
            {
                "name": "MacBook Pro Speakers",
                "max_input_channels": 0,
                "max_output_channels": 2,
                "default_samplerate": 24000.0,
            },
            {
                "name": "USB Audio Codec",
                "max_input_channels": 1,
                "max_output_channels": 1,
                "default_samplerate": 24000.0,
            },
        ]
        self.default = SimpleNamespace(device=(0, 1))

    def query_devices(self):
        return list(self._devices)

    def Stream(self, **kwargs):
        return _FakeStream(parent=self, **kwargs)


class _FakeStream:
    def __init__(
        self,
        *,
        parent: FakeSoundDevice,
        samplerate: int,
        blocksize: int,
        dtype: str,
        channels: tuple[int, int],
        device: tuple[int, int],
        callback,
    ) -> None:
        del parent, samplerate, dtype, device
        self.blocksize = blocksize
        self.input_channels = channels[0]
        self.output_channels = channels[1]
        self.callback = callback
        self.active = False
        self._thread: threading.Thread | None = None

    def __enter__(self):
        self.active = True

        def runner() -> None:
            previous_output = np.zeros((self.blocksize, self.output_channels), dtype=np.float32)
            while self.active:
                indata = np.zeros((self.blocksize, self.input_channels), dtype=np.float32)
                copy_count = min(previous_output.shape[0], self.blocksize)
                indata[:copy_count, 0] = previous_output[:copy_count, 0] * 0.85
                outdata = np.zeros((self.blocksize, self.output_channels), dtype=np.float32)
                try:
                    self.callback(indata, outdata, self.blocksize, None, FakeStatus())
                except FakeSoundDevice.CallbackStop:
                    self.active = False
                previous_output = outdata.copy()
                time.sleep(0.0005)

        self._thread = threading.Thread(target=runner, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        self.active = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        return False


def _load_demo_speaker_mic_main():
    path = Path("tools/demo_speaker_mic_stream.py")
    spec = spec_from_file_location("demo_speaker_mic_stream", path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_audio_device_supports_index_and_name() -> None:
    fake_sd = FakeSoundDevice()

    input_device = acoustic.resolve_audio_device("built-in", direction="input", sounddevice_module=fake_sd)
    output_device = acoustic.resolve_audio_device(1, direction="output", sounddevice_module=fake_sd)

    assert input_device.index == 0
    assert output_device.name == "MacBook Pro Speakers"


def test_resolve_audio_device_rejects_ambiguous_name() -> None:
    fake_sd = FakeSoundDevice()

    with pytest.raises(acoustic.AcousticDemoError):
        acoustic.resolve_audio_device("i", direction="input", sounddevice_module=fake_sd)


def test_resolve_audio_device_rejects_unknown_name() -> None:
    fake_sd = FakeSoundDevice()

    with pytest.raises(acoustic.AcousticDemoError):
        acoustic.resolve_audio_device("does-not-exist", direction="output", sounddevice_module=fake_sd)


def test_run_acoustic_demo_records_and_emits_events(tmp_path, monkeypatch) -> None:
    fake_sd = FakeSoundDevice()
    monkeypatch.setattr(acoustic, "Receiver", DummyReceiver)
    monkeypatch.setattr(acoustic, "DolphinWhistleGenerator", FakeGenerator)
    played_path = tmp_path / "played.wav"
    recorded_path = tmp_path / "recorded.wav"
    observed_events: list[dict[str, object]] = []

    result = acoustic.run_acoustic_demo(
        config_path="configs/smoke.yaml",
        text="了解しました。停止してください",
        model_path="artifacts/models/best.pt",
        out_played=played_path,
        out_recorded=recorded_path,
        seed=7,
        sounddevice_module=fake_sd,
        on_event=lambda event: observed_events.append(event.to_dict()),
    )

    assert played_path.exists()
    assert recorded_path.exists()
    assert result.emitted_texts == ["了解しました", "停止してください"]
    assert result.recorded_path == recorded_path
    assert result.played_path == played_path
    finals = [event for event in result.events if event.is_final]
    assert len(finals) == 2
    assert [event.label for event in finals] == ["了解しました", "停止してください"]
    assert any(not event["is_final"] for event in observed_events)


def test_demo_speaker_mic_cli_lists_devices(monkeypatch, capsys) -> None:
    demo_module = _load_demo_speaker_mic_main()
    fake_devices = [
        acoustic.ResolvedAudioDevice(
            index=0,
            name="Built-in Microphone",
            max_input_channels=1,
            max_output_channels=0,
            default_samplerate=24000.0,
        ),
        acoustic.ResolvedAudioDevice(
            index=1,
            name="MacBook Pro Speakers",
            max_input_channels=0,
            max_output_channels=2,
            default_samplerate=24000.0,
        ),
    ]
    monkeypatch.setattr("sys.argv", ["demo_speaker_mic_stream.py", "--list-devices"])
    monkeypatch.setattr(demo_module, "list_audio_devices", lambda: fake_devices)

    demo_module.main()

    captured = capsys.readouterr()
    assert "Built-in Microphone" in captured.out
    assert "MacBook Pro Speakers" in captured.out
