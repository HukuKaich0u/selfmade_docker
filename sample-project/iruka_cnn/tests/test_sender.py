from pathlib import Path

import numpy as np

from iruka_cnn.common.labels import PhraseDictionary
from iruka_cnn.sender.generator import DolphinWhistleGenerator


def test_sender_generates_variations_within_duration_range() -> None:
    dictionary = PhraseDictionary.from_yaml(Path("data/phrases.yaml"))
    phrase = dictionary.get_by_text("了解しました")
    generator = DolphinWhistleGenerator(sample_rate=24000)

    signal_a = generator.generate(phrase, seed=1)
    signal_b = generator.generate(phrase, seed=2)

    assert signal_a.waveform.dtype == np.float32
    assert 1.0 <= signal_a.duration_seconds <= 2.5
    assert 1.0 <= signal_b.duration_seconds <= 2.5
    assert signal_a.waveform.size > 0
    same_shape = signal_a.waveform.shape == signal_b.waveform.shape
    assert signal_a.waveform.shape != signal_b.waveform.shape or not np.allclose(signal_a.waveform, signal_b.waveform)
    assert same_shape or signal_a.waveform.shape[0] != signal_b.waveform.shape[0]
