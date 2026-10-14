"""稿件元数据：视频详情、分 P 列表、合集展开。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..constants import API_WEB
from ..errors import ParseError, QualityUnavailableError, VideoUnavailableError
from ..models import PageInfo, VideoInfo
from .client import BiliClient
from .parser import InputKind, ParsedRef, extract_bvid

__all__ = [
    "MediaEntry",
    "fetch_video_info",
    "resolve_short_link",
    "fetch_season_entries",
    "fetch_collection_entries",
    "expand_ref",
]

log = logging.getLogger(__name__)

VIEW = f"{API_WEB}/view"
SEASON_ARCHIVES = "https://api.bilibili.com/x/polymer/web-space/seasons_archives_list"


@dataclass(slots=True)
class MediaEntry:
    """一个待下载条目：稿件 + 具体分 P。"""

    video: VideoInfo
    page: PageInfo

    @property
    def bvid(self) -> str:
        return self.video.bvid

    @property
    def cid(self) -> int:
        return self.page.cid

    @property
    def display_title(self) -> str:
        """界面展示用标题，多 P 时带上分 P 信息。"""
        if self.video.is_multi_part:
            return f"{self.video.title} - P{self.page.page} {self.page.part}"
        return self.video.title


def _as_dict(value: Any) -> dict[str, Any]:
    """接口字段类型不稳定，统一收敛成字典。"""
    return value if isinstance(value, dict) else {}


async def fetch_video_info(client: BiliClient, *, bvid: str = "", aid: int = 0) -> VideoInfo:
    """按 BV 号或 av 号获取稿件详情（含全部分 P 与合集信息）。"""
    params: dict[str, object] = {"bvid": bvid} if bvid else {"aid": aid}
    payload = await client.get_json(VIEW, params=params)
    data = _as_dict(payload.get("data"))
    if not data:
        raise VideoUnavailableError(0, "稿件信息为空")

    raw_pages = data.get("pages") or []
    pages = [
        PageInfo(
            cid=int(item.get("cid") or 0),
            page=int(item.get("page") or index + 1),
            part=str(item.get("part") or ""),
            duration=int(item.get("duration") or 0),
        )
        for index, item in enumerate(raw_pages)
        if isinstance(item, dict)
    ]

    # 单 P 稿件在部分接口版本下没有 pages，用顶层 cid 兜底
    if not pages and data.get("cid"):
        pages = [
            PageInfo(
                cid=int(data["cid"]),
                page=1,
                part=str(data.get("title") or ""),
                duration=int(data.get("duration") or 0),
            )
        ]

    if not pages:
        raise VideoUnavailableError(0, "该稿件没有可下载的分 P")

    owner = _as_dict(data.get("owner"))
    season = _as_dict(data.get("ugc_season"))
    season_title = str(season.get("title") or "")
    season_index = 0
    if season_title:
        current = str(data.get("bvid") or bvid)
        for section in season.get("sections") or []:
            for index, episode in enumerate(_as_dict(section).get("episodes") or [], start=1):
                if str(_as_dict(episode).get("bvid") or "") == current:
                    season_index = index
                    break

    return VideoInfo(
        bvid=str(data.get("bvid") or bvid),
        aid=int(data.get("aid") or aid or 0),
        title=str(data.get("title") or ""),
        owner=str(owner.get("name") or ""),
        cover=str(data.get("pic") or ""),
        duration=int(data.get("duration") or 0),
        pages=pages,
        season_title=season_title,
        season_index=season_index,
    )


async def resolve_short_link(client: BiliClient, url: str) -> str:
    """跟随 b23.tv 短链跳转，返回最终地址。"""
    response = await client.request("GET", url)
    final = str(response.url)
    if "bilibili.com" not in final:
        raise ParseError("短链跳转到了非 B 站地址", detail=final)
    return final


async def fetch_season_entries(client: BiliClient, bvid: str) -> tuple[str, list[MediaEntry]]:
    """若稿件属于合集，返回合集标题与合集内全部条目。

    复用一次 view 响应即可拿到所有分集，不产生额外请求。
    """
    payload = await client.get_json(VIEW, params={"bvid": bvid})
    data = _as_dict(payload.get("data"))
    season = _as_dict(data.get("ugc_season"))
    if not season:
        return "", []

    title = str(season.get("title") or "")
    owner = str(_as_dict(data.get("owner")).get("name") or "")
    entries: list[MediaEntry] = []

    for section in season.get("sections") or []:
        for index, episode in enumerate(_as_dict(section).get("episodes") or [], start=1):
            item = _as_dict(episode)
            ep_bvid = str(item.get("bvid") or "")
            ep_cid = int(item.get("cid") or 0)
            if not ep_bvid or not ep_cid:
                continue
            arc = _as_dict(item.get("arc"))
            page = PageInfo(cid=ep_cid, page=1, part=str(item.get("title") or ""))
            entries.append(
                MediaEntry(
                    video=VideoInfo(
                        bvid=ep_bvid,
                        aid=int(item.get("aid") or 0),
                        title=str(item.get("title") or ""),
                        owner=owner,
                        cover=str(arc.get("pic") or ""),
                        duration=int(arc.get("duration") or 0),
                        pages=[page],
                        season_title=title,
                        season_index=index,
                    ),
                    page=page,
                )
            )

    return title, entries


async def fetch_collection_entries(
    client: BiliClient,
    *,
    mid: int,
    sid: int,
    page_size: int = 30,
    max_pages: int = 40,
) -> tuple[str, list[MediaEntry]]:
    """拉取 UP 主合集或系列的全部稿件。该接口需要 WBI 签名。"""
    entries: list[MediaEntry] = []
    title = ""
    page_num = 1

    while page_num <= max_pages:
        params = await client.wbi_sign(
            {
                "mid": mid,
                "season_id": sid,
                "sort_reverse": "false",
                "page_num": page_num,
                "page_size": page_size,
            }
        )
        payload = await client.get_json(SEASON_ARCHIVES, params=params)
        data = _as_dict(payload.get("data"))
        title = title or str(_as_dict(data.get("meta")).get("name") or "")
        archives = data.get("archives") or []
        if not archives:
            break

        for item in archives:
            archive = _as_dict(item)
            bvid = str(archive.get("bvid") or "")
            if not bvid:
                continue
            page = PageInfo(cid=0, page=1, part=str(archive.get("title") or ""))
            entries.append(
                MediaEntry(
                    video=VideoInfo(
                        bvid=bvid,
                        aid=int(archive.get("aid") or 0),
                        title=str(archive.get("title") or ""),
                        cover=str(archive.get("pic") or ""),
                        duration=int(archive.get("duration") or 0),
                        pages=[page],
                        season_title=title,
                    ),
                    page=page,
                )
            )

        if len(archives) < page_size:
            break
        page_num += 1

    if not entries:
        raise QualityUnavailableError(0, "合集为空或无法访问")

    # 合集接口不返回 cid，需要逐个补全才能拿到播放地址
    for entry in entries:
        if entry.page.cid:
            continue
        info = await fetch_video_info(client, bvid=entry.video.bvid)
        entry.video = info
        entry.page = info.pages[0]

    return title or f"合集 {sid}", entries


async def expand_ref(
    client: BiliClient,
    ref: ParsedRef,
    *,
    include_season: bool = False,
    notify: Callable[[str], None] | None = None,
) -> list[MediaEntry]:
    """把一个输入引用展开成待下载条目列表。"""

    def _say(message: str) -> None:
        if notify is not None:
            notify(message)

    if ref.kind is InputKind.COLLECTION:
        _say(f"正在拉取合集 sid={ref.sid}")
        _, entries = await fetch_collection_entries(client, mid=ref.mid, sid=ref.sid)
        return entries

    bvid = ref.bvid
    aid = ref.aid
    if ref.kind is InputKind.SHORTLINK:
        final = await resolve_short_link(client, ref.url)
        bvid = extract_bvid(final)
        if not bvid:
            raise ParseError("短链未指向有效的视频", detail=final)
        _say(f"短链已解析为 {bvid}")

    info = await fetch_video_info(client, bvid=bvid, aid=aid)
    _say(f"已获取《{info.title}》")

    if include_season and info.season_title:
        _, entries = await fetch_season_entries(client, info.bvid)
        if entries:
            _say(f"已展开合集《{info.season_title}》，共 {len(entries)} 个视频")
            return entries

    targets = info.pages
    if ref.page:
        targets = [page for page in info.pages if page.page == ref.page] or [info.pages[0]]

    if len(targets) > 1:
        _say(f"《{info.title}》共 {len(targets)} 个分 P")

    return [MediaEntry(video=info, page=page) for page in targets]
