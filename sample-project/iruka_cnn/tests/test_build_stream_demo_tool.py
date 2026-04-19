from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


def _load_build_stream_demo_main():
    path = Path("tools/build_stream_demo.py")
    spec = spec_from_file_location("build_stream_demo", path)
    assert spec is not None
    assert spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


def test_build_stream_demo_tool_writes_wav(tmp_path, monkeypatch) -> None:
    build_stream_demo_main = _load_build_stream_demo_main()
    output_path = tmp_path / "stream_demo.wav"
    monkeypatch.setattr(
        "sys.argv",
        [
            "build_stream_demo.py",
            "--config",
            "configs/smoke.yaml",
            "--text",
            "こんにちは、了解しました。元気ですか？停止してください",
            "--out",
            str(output_path),
            "--seed",
            "7",
        ],
    )

    build_stream_demo_main()

    assert output_path.exists()
    assert output_path.stat().st_size > 0
