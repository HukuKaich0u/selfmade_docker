import torch

from iruka_cnn.receiver.features import LogMelExtractor
from iruka_cnn.receiver.model import SpectrogramCNN


def test_feature_extractor_and_model_output_shapes() -> None:
    extractor = LogMelExtractor(
        sample_rate=24000,
        n_fft=1024,
        hop_length=256,
        n_mels=64,
        f_min=300,
        f_max=12000,
        top_db=80.0,
    )
    waveform = torch.randn(1, 24000 * 2)
    features = extractor(waveform)

    assert features.ndim == 4
    assert features.shape[1] == 1
    assert features.shape[2] == 64

    model = SpectrogramCNN(num_classes=26, embedding_dim=128)
    logits, embedding = model(features)

    assert logits.shape == (1, 26)
    assert embedding.shape == (1, 128)
