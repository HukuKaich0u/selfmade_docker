from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_recall_fscore_support,
)

from iruka_cnn.common.io import ensure_parent
from iruka_cnn.common.labels import SILENCE_LABEL, UNKNOWN_LABEL


def apply_thresholds(
    top1_labels: Iterable[str],
    top1_scores: Iterable[float],
    top2_scores: Iterable[float],
    confidence_threshold: float,
    margin_threshold: float,
) -> list[str]:
    resolved: list[str] = []
    for label, score1, score2 in zip(top1_labels, top1_scores, top2_scores, strict=True):
        if label in (UNKNOWN_LABEL, SILENCE_LABEL):
            resolved.append(label)
            continue
        margin = score1 - score2
        if score1 < confidence_threshold or margin < margin_threshold:
            resolved.append(UNKNOWN_LABEL)
        else:
            resolved.append(label)
    return resolved


def summarize_metrics(y_true: list[str], y_pred: list[str], labels: list[str]) -> dict:
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=labels,
        zero_division=0,
    )
    return {
        "accuracy": float(accuracy_score(y_true, y_pred)),
        "macro_f1": float(f1_score(y_true, y_pred, average="macro", labels=labels, zero_division=0)),
        "unknown_false_accept_rate": _unknown_false_accept_rate(y_true, y_pred),
        "per_class": [
            {
                "label": label,
                "precision": float(p),
                "recall": float(r),
                "f1": float(f),
                "support": int(s),
            }
            for label, p, r, f, s in zip(labels, precision, recall, f1, support, strict=True)
        ],
        "classification_report": classification_report(
            y_true,
            y_pred,
            labels=labels,
            zero_division=0,
            output_dict=True,
        ),
    }


def render_confusion_matrix(
    y_true: list[str],
    y_pred: list[str],
    labels: list[str],
    output_path: str | Path,
    title: str,
) -> Path:
    import matplotlib.pyplot as plt

    matrix = confusion_matrix(y_true, y_pred, labels=labels)
    output = ensure_parent(output_path)
    fig, ax = plt.subplots(figsize=(12, 10))
    tick_labels = [f"C{idx:02d}" for idx, _ in enumerate(labels)]
    image = ax.imshow(matrix, interpolation="nearest", cmap="Blues")
    ax.figure.colorbar(image, ax=ax)
    ax.set(
        xticks=np.arange(len(labels)),
        yticks=np.arange(len(labels)),
        xticklabels=tick_labels,
        yticklabels=tick_labels,
        ylabel="True label",
        xlabel="Predicted label",
        title=title,
    )
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor")
    threshold = matrix.max() / 2.0 if matrix.size else 0.0
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(
                j,
                i,
                int(matrix[i, j]),
                ha="center",
                va="center",
                color="white" if matrix[i, j] > threshold else "black",
            )
    fig.tight_layout()
    fig.savefig(output, dpi=180)
    plt.close(fig)
    return output


def optimize_thresholds(
    y_true: list[str],
    top1_labels: list[str],
    top1_scores: list[float],
    top2_scores: list[float],
    labels: list[str],
) -> dict[str, float]:
    best = {
        "confidence_threshold": 0.72,
        "margin_threshold": 0.12,
        "macro_f1": -1.0,
    }
    for confidence_threshold in np.linspace(0.50, 0.92, 15):
        for margin_threshold in np.linspace(0.02, 0.22, 11):
            y_pred = apply_thresholds(
                top1_labels,
                top1_scores,
                top2_scores,
                float(confidence_threshold),
                float(margin_threshold),
            )
            score = f1_score(y_true, y_pred, average="macro", labels=labels, zero_division=0)
            if float(score) > float(best["macro_f1"]):
                best = {
                    "confidence_threshold": float(confidence_threshold),
                    "margin_threshold": float(margin_threshold),
                    "macro_f1": float(score),
                }
    return best


def _unknown_false_accept_rate(y_true: list[str], y_pred: list[str]) -> float:
    unknown_indices = [idx for idx, label in enumerate(y_true) if label == UNKNOWN_LABEL]
    if not unknown_indices:
        return 0.0
    false_accepts = sum(1 for idx in unknown_indices if y_pred[idx] != UNKNOWN_LABEL)
    return false_accepts / len(unknown_indices)
