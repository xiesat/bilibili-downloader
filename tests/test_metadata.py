"""稿件事元数据与合集展开的单元测试（使用 fixture，不触网）。

说明：直播环境下 seasons_archives_list 对未登录请求返回 -352，
因此合集拉取路径以接口文档给出的响应结构构造 fixture 来验证解析逻辑；
而合集展开（复用 view 响应里的 ugc_season）是实测可用的路径。
"""

from __future__ import annotations

from typing import Any

import pytest

from bilidown.core.metadata import (
    expand_ref,
    fetch_collection_entries,
    fetch_season_entries,
    fetch_video_info,
)
from bilidown.core.parser import parse_one

#: BV 号固定为 12 个字符（BV + 10 位），fixture 必须符合该格式，
#: 否则会被解析器截断成另一个号。
MAIN_BVID = "BV1MAIN00001"
EPISODE_BVID = "BV1EP0000002"


def _view(bvid: str, cid: int, title: str, pages: list[dict[str, Any]] | None = None,
          season: dict[str, Any] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "bvid": bvid,
        "aid": abs(hash(bvid)) % 100000,
        "title": title,
        "pic": "https://example.invalid/cover.jpg",
        "duration": 120,
        "owner": {"name": "测试UP主"},
        "pages": pages or [{"cid": cid, "page": 1, "part": title, "duration": 120}],
    }
    if season is not None:
        data["ugc_season"] = season
    return {"code": 0, "data": data}


SEASON = {
    "id": 9001,
    "mid": 555,
    "title": "测试合集",
    "sections": [
        {
            "episodes": [
                {"bvid": MAIN_BVID, "aid": 100, "cid": 111, "title": "第一集",
                 "arc": {"pic": "a.jpg", "duration": 120}},
                {"bvid": EPISODE_BVID, "aid": 101, "cid": 222, "title": "第二集",
                 "arc": {"pic": "b.jpg", "duration": 130}},
            ]
        }
    ],
}

MULTI_PART = [
    {"cid": 501, "page": 1, "part": "正片", "duration": 300},
    {"cid": 502, "page": 2, "part": "花絮", "duration": 60},
]

VIEWS: dict[str, dict[str, Any]] = {
    MAIN_BVID: _view(MAIN_BVID, 111, "合集第一集", season=SEASON),
    EPISODE_BVID: _view(EPISODE_BVID, 222, "合集第二集"),
    "BV1MULTI0001": _view("BV1MULTI0001", 501, "多P视频", pages=MULTI_PART),
    "BV1PLAIN0001": _view("BV1PLAIN0001", 601, "单P视频"),
}

ARCHIVES = {
    "code": 0,
    "data": {
        "meta": {"name": "合集名称", "mid": 555, "season_id": 9001, "total": 2},
        "archives": [
            {"aid": 100, "bvid": MAIN_BVID, "title": "第一集", "pic": "a.jpg", "duration": 120},
            {"aid": 101, "bvid": EPISODE_BVID, "title": "第二集", "pic": "b.jpg", "duration": 130},
        ],
        "page": {"num": 1, "size": 30, "total": 2},
    },
}


class FakeClient:
    """只实现元数据层用到的方法，避免测试触网。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get_json(self, url: str, *, params: dict[str, Any] | None = None,
                       headers: dict[str, str] | None = None,
                       raise_on_code: bool = True) -> dict[str, Any]:
        params = dict(params or {})
        self.calls.append((url, params))
        if url.endswith("/view"):
            bvid = str(params.get("bvid") or "")
            if bvid in VIEWS:
                return VIEWS[bvid]
        if "seasons_archives_list" in url:
            return ARCHIVES
        raise AssertionError(f"未预设的请求：{url} {params}")

    async def wbi_sign(self, params: dict[str, Any]) -> dict[str, Any]:
        return dict(params)


def test_fetch_video_info_parses_pages_and_season() -> None:
    client = FakeClient()
    info = await_run(fetch_video_info(client, bvid=MAIN_BVID))
    assert info.bvid == MAIN_BVID
    assert info.title == "合集第一集"
    assert info.owner == "测试UP主"
    assert len(info.pages) == 1
    assert info.pages[0].cid == 111
    assert info.season_title == "测试合集"
    assert info.season_index == 1


def test_fetch_video_info_multi_part() -> None:
    client = FakeClient()
    info = await_run(fetch_video_info(client, bvid="BV1MULTI0001"))
    assert info.is_multi_part
    assert [page.page for page in info.pages] == [1, 2]
    assert [page.part for page in info.pages] == ["正片", "花絮"]


def test_fetch_season_entries() -> None:
    client = FakeClient()
    title, entries = await_run(fetch_season_entries(client, MAIN_BVID))
    assert title == "测试合集"
    assert [entry.bvid for entry in entries] == [MAIN_BVID, EPISODE_BVID]
    assert [entry.cid for entry in entries] == [111, 222]
    assert entries[0].video.season_index == 1
    assert entries[1].video.season_index == 2


def test_expand_ref_multi_part_returns_every_page() -> None:
    client = FakeClient()
    entries = await_run(expand_ref(client, parse_one("BV1MULTI0001")))
    assert len(entries) == 2
    assert [entry.cid for entry in entries] == [501, 502]


def test_expand_ref_single_page_selection() -> None:
    client = FakeClient()
    entries = await_run(expand_ref(client, parse_one("BV1MULTI0001?p=2")))
    assert len(entries) == 1
    assert entries[0].cid == 502


def test_expand_ref_includes_season_when_requested() -> None:
    client = FakeClient()
    entries = await_run(expand_ref(client, parse_one(MAIN_BVID), include_season=True))
    assert [entry.bvid for entry in entries] == [MAIN_BVID, EPISODE_BVID]


def test_expand_ref_without_season_keeps_single_video() -> None:
    client = FakeClient()
    entries = await_run(expand_ref(client, parse_one(MAIN_BVID)))
    assert [entry.bvid for entry in entries] == [MAIN_BVID]


def test_fetch_collection_entries_backfills_cid() -> None:
    client = FakeClient()
    title, entries = await_run(fetch_collection_entries(client, mid=555, sid=9001))
    assert title == "合集名称"
    assert [entry.bvid for entry in entries] == [MAIN_BVID, EPISODE_BVID]
    # 合集接口不含 cid，必须回查 view 补全，否则拿不到播放地址
    assert [entry.cid for entry in entries] == [111, 222]
    assert any("seasons_archives_list" in url for url, _ in client.calls)


def test_expand_ref_collection_kind() -> None:
    client = FakeClient()
    ref = parse_one("https://space.bilibili.com/555/channel/collectiondetail?sid=9001")
    entries = await_run(expand_ref(client, ref))
    assert len(entries) == 2
    assert entries[0].video.season_title == "合集名称"


def test_missing_video_raises() -> None:
    client = FakeClient()
    with pytest.raises(AssertionError):
        await_run(fetch_video_info(client, bvid="BV1NOTEXIST0"))


# ---------------------------------------------------------------------------
# 测试辅助：在没有事件循环的情况下驱动协程
# ---------------------------------------------------------------------------
def await_run(coro: Any) -> Any:
    import asyncio

    return asyncio.run(coro)
