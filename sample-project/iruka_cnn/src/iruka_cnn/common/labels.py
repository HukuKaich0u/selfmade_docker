from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from iruka_cnn.common.config import load_yaml


UNKNOWN_LABEL = "unknown"
SILENCE_LABEL = "silence"


@dataclass(frozen=True)
class Phrase:
    key: str
    text: str


class PhraseDictionary:
    def __init__(self, version: str, phrases: list[Phrase]) -> None:
        self.version = version
        self.phrases = phrases
        self._text_to_phrase = {phrase.text: phrase for phrase in phrases}
        self._key_to_phrase = {phrase.key: phrase for phrase in phrases}

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PhraseDictionary":
        payload = load_yaml(path)
        phrases = [Phrase(key=item["key"], text=item["text"]) for item in payload["phrases"]]
        return cls(version=str(payload.get("version", "unknown")), phrases=phrases)

    def texts(self) -> list[str]:
        return [phrase.text for phrase in self.phrases]

    def labels(self) -> list[str]:
        return self.texts() + [UNKNOWN_LABEL, SILENCE_LABEL]

    def get_by_text(self, text: str) -> Phrase:
        return self._text_to_phrase[text]

    def get_by_key(self, key: str) -> Phrase:
        return self._key_to_phrase[key]

    def to_label_vocab(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "labels": self.labels(),
            "phrases": [{"key": phrase.key, "text": phrase.text} for phrase in self.phrases],
        }


class LabelEncoder:
    def __init__(self, labels: list[str]) -> None:
        self.labels = labels
        self.to_index = {label: idx for idx, label in enumerate(labels)}

    def encode(self, label: str) -> int:
        return self.to_index[label]

    def decode(self, index: int) -> str:
        return self.labels[index]

    @property
    def num_classes(self) -> int:
        return len(self.labels)


def load_label_encoder_from_dictionary(path: str | Path) -> LabelEncoder:
    dictionary = PhraseDictionary.from_yaml(path)
    return LabelEncoder(dictionary.labels())
