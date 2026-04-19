from pathlib import Path

from iruka_cnn.common.config import load_yaml
from iruka_cnn.common.io import write_wav
from iruka_cnn.common.labels import PhraseDictionary
from iruka_cnn.sender.generator import DolphinWhistleGenerator
from iruka_cnn.training.visualization import maybe_create_train_plotter, render_audio_overview
from iruka_cnn.training.visualize_audio_cli import main as visualize_main


def test_train_plotter_writes_png_with_agg_backend(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("IRUKA_ENABLE_TRAIN_PLOTS", "1")
    monkeypatch.setenv("MPLBACKEND", "Agg")
    plot_path = tmp_path / "training_live.png"

    plotter = maybe_create_train_plotter(plot_path)

    assert plotter is not None
    plotter.update_batch(global_step=1, loss=1.2, accuracy=0.25)
    plotter.update_batch(global_step=2, loss=1.0, accuracy=0.5)
    plotter.update_epoch(
        epoch=1,
        train_loss=1.1,
        val_loss=0.9,
        train_accuracy=0.5,
        val_accuracy=0.6,
        val_macro_f1=0.55,
    )
    plotter.close()

    assert plot_path.exists()
    assert plot_path.stat().st_size > 0


def test_render_audio_overview_writes_png(tmp_path) -> None:
    config = load_yaml("configs/smoke.yaml")
    dictionary = PhraseDictionary.from_yaml(Path("data/phrases.yaml"))
    generator = DolphinWhistleGenerator(sample_rate=24000)
    phrase = dictionary.get_by_text("了解しました")
    generated = generator.generate(phrase, seed=3)
    output_path = tmp_path / "overview.png"

    result = render_audio_overview(
        waveform=generated.waveform,
        source_rate=generated.sample_rate,
        config=config,
        output_path=output_path,
        title="overview",
        show=False,
    )

    assert result.output_path == output_path
    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_visualize_audio_cli_supports_wav_and_text(tmp_path, monkeypatch) -> None:
    config = load_yaml("configs/smoke.yaml")
    dictionary = PhraseDictionary.from_yaml(Path("data/phrases.yaml"))
    generator = DolphinWhistleGenerator(sample_rate=24000)
    phrase = dictionary.get_by_text("停止してください")
    generated = generator.generate(phrase, seed=13)
    wav_path = tmp_path / "stop.wav"
    wav_output = tmp_path / "stop_viz.png"
    text_output = tmp_path / "text_viz.png"
    write_wav(wav_path, generated.waveform, generated.sample_rate)

    monkeypatch.setenv("MPLBACKEND", "Agg")
    monkeypatch.setattr(
        "sys.argv",
        [
            "visualize_audio_cli.py",
            "--config",
            "configs/smoke.yaml",
            "--wav",
            str(wav_path),
            "--out",
            str(wav_output),
        ],
    )
    visualize_main()

    monkeypatch.setattr(
        "sys.argv",
        [
            "visualize_audio_cli.py",
            "--config",
            "configs/smoke.yaml",
            "--text",
            "了解しました",
            "--seed",
            "7",
            "--out",
            str(text_output),
        ],
    )
    visualize_main()

    assert config["audio"]["sample_rate"] == 24000
    assert wav_output.exists()
    assert wav_output.stat().st_size > 0
    assert text_output.exists()
    assert text_output.stat().st_size > 0
