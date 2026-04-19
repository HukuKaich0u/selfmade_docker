from __future__ import annotations

from collections import defaultdict

import torch


def build_class_prototypes(embeddings: torch.Tensor, labels: list[str]) -> dict[str, list[float]]:
    grouped: dict[str, list[torch.Tensor]] = defaultdict(list)
    for embedding, label in zip(embeddings, labels, strict=True):
        grouped[label].append(embedding)
    return {
        label: torch.stack(items).mean(dim=0).cpu().tolist()
        for label, items in grouped.items()
    }
