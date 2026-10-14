"""输入解析的单元测试。"""

from __future__ import annotations

from bilidown.core.parser import InputKind, parse_lines, parse_one


def test_bv_number() -> None:
    ref = parse_one("BV1GJ411x7h7")
    assert ref.kind is InputKind.VIDEO
    assert ref.bvid == "BV1GJ411x7h7"
    assert ref.page == 0


def test_url_with_page_param() -> None:
    ref = parse_one("https://www.bilibili.com/video/BV1GJ411x7h7/?p=3")
    assert ref.kind is InputKind.VIDEO
    assert ref.bvid == "BV1GJ411x7h7"
    assert ref.page == 3


def test_av_number() -> None:
    ref = parse_one("av170001")
    assert ref.kind is InputKind.VIDEO
    assert ref.aid == 170001


def test_short_link() -> None:
    ref = parse_one("https://b23.tv/abcdefg")
    assert ref.kind is InputKind.SHORTLINK
    assert ref.url.startswith("https://")


def test_collection_link() -> None:
    ref = parse_one("https://space.bilibili.com/123456/channel/collectiondetail?sid=789")
    assert ref.kind is InputKind.COLLECTION
    assert (ref.mid, ref.sid) == (123456, 789)


def test_series_link() -> None:
    ref = parse_one("https://space.bilibili.com/42/channel/seriesdetail?sid=7")
    assert ref.kind is InputKind.COLLECTION
    assert (ref.mid, ref.sid) == (42, 7)


def test_unknown_input() -> None:
    ref = parse_one("这不是一个链接")
    assert ref.kind is InputKind.UNKNOWN
    assert ref.error


def test_batch_split_dedupe_and_invalid() -> None:
    text = (
        "BV1GJ411x7h7\n"
        "https://www.bilibili.com/video/BV1GJ411x7h7?p=2\n"
        "BV1GJ411x7h7, av170001、BV1phpC6nEjG\n"
        "垃圾内容\n"
    )
    valid, invalid = parse_lines(text)
    keys = {(item.bvid, item.aid) for item in valid}
    assert ("BV1GJ411x7h7", 0) in keys
    assert ("", 170001) in keys
    assert ("BV1phpC6nEjG", 0) in keys
    # 完全重复的 BV 号只保留一条
    assert len([item for item in valid if item.bvid == "BV1GJ411x7h7"]) == 2
    assert len(invalid) == 1


def test_dedupe_key_ignores_duplicate_lines() -> None:
    valid, _ = parse_lines("BV1GJ411x7h7\nBV1GJ411x7h7\nBV1GJ411x7h7")
    assert len(valid) == 1
