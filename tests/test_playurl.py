"""画质与编码选择的单元测试（纯函数，不触网）。"""

from __future__ import annotations

import pytest

from bilidown.core.playurl import pick_video
from bilidown.errors import QualityUnavailableError
from bilidown.models import StreamRef


def _streams() -> list[StreamRef]:
    return [
        StreamRef(url="av01", quality_id=80, codecs="av01.0.08M.08", bandwidth=100),
        StreamRef(url="hev1", quality_id=80, codecs="hev1.1.6.L120.90", bandwidth=200),
        StreamRef(url="avc1", quality_id=80, codecs="avc1.640028", bandwidth=300),
        StreamRef(url="low-avc1", quality_id=32, codecs="avc1.64001F", bandwidth=50),
    ]


def test_prefers_requested_codec() -> None:
    streams = _streams()
    assert pick_video(streams, 80, "avc1").url == "avc1"
    assert pick_video(streams, 80, "hev1").url == "hev1"
    assert pick_video(streams, 80, "av01").url == "av01"


def test_auto_picks_highest_quality() -> None:
    assert pick_video(_streams(), 0, "avc1").quality_id == 80


def test_unavailable_quality_falls_back_to_lower() -> None:
    # 请求 1080P+ 但只有 720P 与 480P，应退到 720P
    assert pick_video(_streams(), 112, "avc1").quality_id == 80


def test_unavailable_quality_falls_back_to_lowest_when_needed() -> None:
    streams = [StreamRef(url="only", quality_id=32, codecs="avc1.64001F")]
    assert pick_video(streams, 6, "avc1").quality_id == 32


def test_unknown_codec_preference_uses_bandwidth() -> None:
    streams = [
        StreamRef(url="a", quality_id=80, codecs="unknown-codec", bandwidth=10),
        StreamRef(url="b", quality_id=80, codecs="other-codec", bandwidth=99),
    ]
    assert pick_video(streams, 80, "zzzz").url == "b"


def test_empty_raises() -> None:
    with pytest.raises(QualityUnavailableError):
        pick_video([], 80, "avc1")


def test_candidates_deduplicate() -> None:
    stream = StreamRef(url="A", backup_urls=["A", "B", "B", "C"])
    assert stream.candidates == ["A", "B", "C"]
