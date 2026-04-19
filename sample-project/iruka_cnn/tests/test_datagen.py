from pathlib import Path
import json

from iruka_cnn.common.labels import PhraseDictionary
from iruka_cnn.training.dataset import FeatureDataset
from iruka_cnn.training.datagen import generate_dataset


def test_generate_dataset_creates_metadata(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    phrases_src = Path(__file__).resolve().parents[1] / "data" / "phrases.yaml"
    (tmp_path / "data" / "phrases.yaml").write_text(phrases_src.read_text(encoding="utf-8"), encoding="utf-8")
    config = {
        "dictionary": {"phrases_path": "data/phrases.yaml"},
        "audio": {
            "sample_rate": 24000,
            "clip_seconds": 2.5,
            "min_phrase_seconds": 1.0,
            "max_phrase_seconds": 2.5,
        },
        "features": {
            "n_fft": 1024,
            "hop_length": 256,
            "n_mels": 64,
            "f_min": 300,
            "f_max": 12000,
            "top_db": 80.0,
        },
        "dataset": {
            "train_per_phrase": 2,
            "val_per_phrase": 1,
            "test_per_phrase": 1,
            "unknown_per_split": 2,
            "silence_per_split": 1,
            "overwrite": True,
            "cache_features": True,
            "cache_dtype": "float16",
        },
        "training": {
            "batch_size": 4,
            "device": "cpu",
        },
        "augmentation": {
            "mode": "feature",
        },
    }

    summary = generate_dataset(config)

    assert summary["phrases"] > 0
    assert summary["features_cached"] > 0
    assert (tmp_path / "data" / "train" / "metadata.jsonl").exists()
    assert (tmp_path / "data" / "val" / "metadata.jsonl").exists()
    assert (tmp_path / "data" / "test" / "metadata.jsonl").exists()

    first_record = json.loads((tmp_path / "data" / "train" / "metadata.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert first_record["feature_path"].endswith(".npy")
    assert (tmp_path / first_record["feature_path"]).exists()

    dictionary = PhraseDictionary.from_yaml(tmp_path / "data" / "phrases.yaml")
    dataset = FeatureDataset(data_root=tmp_path / "data", split="train", dictionary=dictionary)
    features, label = dataset[0]
    assert features.ndim == 3
    assert features.shape[0] == 1
    assert features.shape[1] == 64
    assert label.ndim == 0
