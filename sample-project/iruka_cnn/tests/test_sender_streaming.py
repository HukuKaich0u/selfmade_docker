from pathlib import Path

import pytest

from iruka_cnn.common.labels import PhraseDictionary
from iruka_cnn.common.utils import stable_seed
from iruka_cnn.sender.generator import DolphinWhistleGenerator
from iruka_cnn.sender.streaming import DolphinPhraseStreamer


def _build_streamer(segment_gap_ms: int = 300) -> tuple[PhraseDictionary, DolphinPhraseStreamer]:
    dictionary = PhraseDictionary.from_yaml(Path("data/phrases.yaml"))
    generator = DolphinWhistleGenerator(sample_rate=24000)
    return dictionary, DolphinPhraseStreamer(dictionary, generator, segment_gap_ms=segment_gap_ms)


def test_streamer_extracts_registered_phrases_and_drops_unregistered_text() -> None:
    _, streamer = _build_streamer()

    result = streamer.synthesize_text(
        "こんにちは、了解しました。元気ですか？停止してください",
        seed=11,
    )

    assert result.emitted_texts == ["了解しました", "停止してください"]
    assert result.dropped_fragments == ["こんにちは", "元気ですか"]


def test_streamer_inserts_gap_between_phrase_events() -> None:
    dictionary, streamer = _build_streamer(segment_gap_ms=300)
    ack = dictionary.get_by_text("了解しました")
    stop = dictionary.get_by_text("停止してください")
    result = streamer.synthesize_phrase_events(
        ["了解しました", "未登録フレーズ", "停止してください"],
        seed=7,
    )

    signal_ack = streamer.generator.generate(ack, seed=stable_seed(f"stream:7:{ack.key}:0"))
    signal_stop = streamer.generator.generate(stop, seed=stable_seed(f"stream:7:{stop.key}:1"))
    expected_samples = signal_ack.waveform.shape[0] + int(0.3 * streamer.generator.sample_rate) + signal_stop.waveform.shape[0]

    assert result.emitted_texts == ["了解しました", "停止してください"]
    assert result.dropped_fragments == ["未登録フレーズ"]
    assert result.waveform.shape[0] == expected_samples


def test_streamer_iter_audio_chunks_reports_monotonic_offsets() -> None:
    _, streamer = _build_streamer(segment_gap_ms=300)
    result = streamer.synthesize_phrase_events(["了解しました", "停止してください"], seed=5)

    chunks = list(streamer.iter_audio_chunks(result.waveform, chunk_ms=20))

    assert chunks
    assert chunks[0].start_ms == 0.0
    assert chunks[-1].end_ms == pytest.approx(result.waveform.shape[0] * 1000.0 / result.sample_rate, abs=1e-6)
    for left, right in zip(chunks[:-1], chunks[1:], strict=True):
        assert left.end_ms == pytest.approx(right.start_ms, abs=1e-6)
