import torch

from iruka_cnn.training.augment import FeatureAugmentor


def test_feature_augmentor_preserves_batch_shape_and_silence() -> None:
    augmentor = FeatureAugmentor(
        {
            "feature_gain_db": 1.0,
            "feature_noise_std": 0.02,
            "feature_time_shift_frames": 4,
            "feature_time_mask_max_frames": 6,
            "feature_freq_mask_max_bins": 4,
            "feature_mel_shift_max_bins": 1,
        }
    )
    features = torch.randn(3, 1, 64, 120)
    labels = torch.tensor([0, 1, 2], dtype=torch.long)
    silence_index = 1

    augmented = augmentor(features, labels=labels, silence_index=silence_index)

    assert augmented.shape == features.shape
    assert torch.allclose(augmented[1], features[1])
