from __future__ import annotations

import torch
import torch.nn.functional as F


class ConvBlock(torch.nn.Module):
    def __init__(self, in_channels: int, out_channels: int) -> None:
        super().__init__()
        self.block = torch.nn.Sequential(
            torch.nn.Conv2d(in_channels, out_channels, kernel_size=3, padding=1),
            torch.nn.BatchNorm2d(out_channels),
            torch.nn.ReLU(inplace=True),
            torch.nn.MaxPool2d(kernel_size=2),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.block(x)


class SpectrogramCNN(torch.nn.Module):
    def __init__(self, num_classes: int, embedding_dim: int = 128) -> None:
        super().__init__()
        channels = [1, 32, 64, 128, 128]
        blocks = [ConvBlock(channels[idx], channels[idx + 1]) for idx in range(len(channels) - 1)]
        self.backbone = torch.nn.Sequential(*blocks)
        self.pool = torch.nn.AdaptiveAvgPool2d((1, 1))
        self.embedding = torch.nn.Linear(128, embedding_dim)
        self.classifier = torch.nn.Linear(embedding_dim, num_classes)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        features = self.backbone(x)
        pooled = self.pool(features).flatten(1)
        embedding = self.embedding(pooled)
        normalized_embedding = F.normalize(embedding, dim=-1)
        logits = self.classifier(normalized_embedding)
        return logits, normalized_embedding
