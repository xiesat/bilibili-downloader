"""播放地址协商：画质选择、编码优选、CDN 回退与渐进式降级。

关键实测结论（决定了本模块的实现方式）：

1. 未登录时 accept_quality 虽然列出 1080P+ / 1080P 等，
   但实际只会下发 480P 的视频流，因此可用画质必须以 dash.video 的
   实际 id 集合为准，不能相信 accept_quality。
2. 同一画质会同时返回 av01 / hev1 / avc1 三份编码，
   直接取第一个可能拿到 AV1 或 HEVC，导致部分播放器无法播放，
   因此必须按编码优先级挑选。
3. baseUrl 常常指向 PCDN 节点（例如 edge.mountaintoys.cn），
   该节点可能 403，必须保留 backupUrl 作为回退。
4. fnval=0 时 B 站返回已合流的单个 MP4，无需 ffmpeg，
   但画质通常止步 720P —— 这是无 ffmpeg 时的自动降级路径。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..constants import (
    API_PLAYER,
    CODEC_PREFERENCE,
    LOGIN_QUALITIES,
    VIP_QUALITIES,
    quality_name,
)
from ..errors import ApiError, NetworkError, QualityUnavailableError
from ..models import DownloadMode, MediaPlan, StreamRef
from .client import BiliClient

__all__ = ["QualityOption", "fetch_playinfo", "pick_video", "build_plan", "quality_options"]

log = logging.getLogger(__name__)

PLAYURL_WBI = f"{API_PLAYER}/wbi/playurl"
PLAYURL_PLAIN = f"{API_PLAYER}/playurl"

#: DASH + 4K + HDR + 杜比 + 8K 等功能位组合
FNVAL_DASH = 4048

#: 请求最高画质，由服务端按账号权限下调
REQUEST_QN = 127


@dataclass(slots=True)
class QualityOption:
    """一个可选画质项，供界面展示与置灰。"""

    qn: int
    name: str
    available: bool
    requires_login: bool
    requires_vip: bool

    @property
    def note(self) -> str:
        """不可用时的原因说明。"""
        if self.available:
            return ""
        if self.requires_vip:
            return "需大会员"
        if self.requires_login:
            return "需登录"
        return "不可用"


async def fetch_playinfo(
    client: BiliClient,
    *,
    bvid: str,
    cid: int,
    dash: bool = True,
) -> dict[str, Any]:
    """请求播放地址数据。

    dash 为真时走 fnval=4048 拿音视频分离流，
    为假时请求渐进式单文件。
    """
    params: dict[str, Any] = {
        "bvid": bvid,
        "cid": cid,
        "qn": REQUEST_QN,
        "fnver": 0,
        "fnval": FNVAL_DASH if dash else 0,
        "fourk": 1,
    }

    try:
        signed = await client.wbi_sign(dict(params))
        payload = await client.get_json(PLAYURL_WBI, params=signed)
    except (ApiError, NetworkError) as exc:
        # WBI 通道偶发失败时退回普通接口，两者返回结构一致
        log.debug("WBI playurl 失败（%s），回退普通接口", exc)
        payload = await client.get_json(PLAYURL_PLAIN, params=params)

    return payload.get("data") or {}


def _to_stream(node: dict[str, Any]) -> StreamRef:
    """把接口返回的一条流描述转成 StreamRef。"""
    quality_id = int(node.get("id") or 0)
    backup = node.get("backupUrl") or node.get("backup_url") or []
    return StreamRef(
        url=str(node.get("baseUrl") or node.get("base_url") or ""),
        backup_urls=[str(item) for item in backup if item],
        quality_id=quality_id,
        quality_name=quality_name(quality_id),
        codecs=str(node.get("codecs") or ""),
        bandwidth=int(node.get("bandwidth") or 0),
        width=int(node.get("width") or 0),
        height=int(node.get("height") or 0),
        mime_type=str(node.get("mimeType") or node.get("mime_type") or ""),
    )


def pick_video(streams: list[StreamRef], target_qn: int = 0, codec: str = "avc1") -> StreamRef:
    """在候选视频流中挑出目标画质与首选编码的一条。

    target_qn 为 0 表示自动选择实际可得的最高画质；
    目标画质拿不到时，退到不高于它的最高画质，并在上层给出提示。
    """
    if not streams:
        raise QualityUnavailableError("该稿件没有可用的视频流")

    by_quality: dict[int, list[StreamRef]] = {}
    for stream in streams:
        by_quality.setdefault(stream.quality_id, []).append(stream)

    if target_qn and target_qn in by_quality:
        chosen = target_qn
    elif target_qn:
        lower = [qn for qn in by_quality if qn <= target_qn]
        chosen = max(lower) if lower else min(by_quality)
    else:
        chosen = max(by_quality)

    candidates = by_quality[chosen]

    # 编码优先级：用户首选排最前，其余按默认顺序补齐
    order = [codec] + [item for item in CODEC_PREFERENCE if item != codec]
    for wanted in order:
        for stream in candidates:
            if stream.codecs.lower().startswith(wanted):
                return stream

    # 都不匹配时退到码率最高的一条
    return max(candidates, key=lambda item: item.bandwidth)


def _pick_audio(streams: list[StreamRef]) -> StreamRef | None:
    """音频挑码率最高的一条。"""
    if not streams:
        return None
    return max(streams, key=lambda item: (item.bandwidth, item.quality_id))


def _size_hint(node: dict[str, Any]) -> int:
    return int(node.get("size") or 0)


async def build_plan(
    client: BiliClient,
    *,
    bvid: str,
    cid: int,
    quality: int = 0,
    codec: str = "avc1",
    mode: DownloadMode = DownloadMode.AUTO,
    ffmpeg_available: bool = False,
) -> MediaPlan:
    """为一个分 P 生成完整的下载方案。"""
    use_dash = mode is DownloadMode.DASH or (mode is DownloadMode.AUTO and ffmpeg_available)

    if use_dash:
        data = await fetch_playinfo(client, bvid=bvid, cid=cid, dash=True)
        dash = data.get("dash") or {}
        video_streams = [_to_stream(node) for node in (dash.get("video") or []) if isinstance(node, dict)]
        audio_streams = [_to_stream(node) for node in (dash.get("audio") or []) if isinstance(node, dict)]

        if video_streams:
            video = pick_video(video_streams, quality, codec)
            audio = _pick_audio(audio_streams)
            note = ""
            if quality and video.quality_id != quality:
                note = f"请求的画质 {quality_name(quality)} 当前不可用，已自动使用 {video.quality_name}"
            return MediaPlan(
                mode=DownloadMode.DASH,
                quality_id=video.quality_id,
                quality_name=video.quality_name,
                video=video,
                audio=audio,
                requires_mux=audio is not None,
                note=note,
            )
        log.warning("DASH 流不可用，降级为渐进式：%s cid=%s", bvid, cid)

    # 渐进式：B 站已合流，无需 ffmpeg
    data = await fetch_playinfo(client, bvid=bvid, cid=cid, dash=False)
    durl = data.get("durl") or []
    if not durl:
        raise QualityUnavailableError("该稿件没有可下载的媒体流")

    first = durl[0] if isinstance(durl[0], dict) else {}
    quality_id = int(data.get("quality") or 0)
    progressive = StreamRef(
        url=str(first.get("url") or ""),
        backup_urls=[str(item) for item in (first.get("backup_url") or first.get("backupUrl") or []) if item],
        quality_id=quality_id,
        quality_name=quality_name(quality_id),
        mime_type=str(data.get("format") or ""),
        size_hint=_size_hint(first),
    )

    if not progressive.url:
        raise QualityUnavailableError("渐进式播放地址为空")

    note = ""
    if mode is DownloadMode.AUTO and not ffmpeg_available:
        note = "未检测到 ffmpeg，已自动降级为渐进式单文件模式（免合并）"

    return MediaPlan(
        mode=DownloadMode.PROGRESSIVE,
        quality_id=progressive.quality_id,
        quality_name=progressive.quality_name,
        progressive=progressive,
        requires_mux=False,
        note=note,
    )


async def quality_options(client: BiliClient, *, bvid: str, cid: int) -> list[QualityOption]:
    """列出该稿件各画质的可用情况。

    可用性以 dash.video 实际返回的 id 为准；
    未登录拿不到的高画质会被标记为需登录 / 需大会员，供界面置灰。
    """
    data = await fetch_playinfo(client, bvid=bvid, cid=cid, dash=True)
    dash = data.get("dash") or {}
    available_ids = {
        int(node.get("id") or 0)
        for node in (dash.get("video") or [])
        if isinstance(node, dict) and node.get("id")
    }

    declared = [int(item) for item in (data.get("accept_quality") or []) if item]
    if not declared:
        declared = sorted(available_ids, reverse=True)

    options: list[QualityOption] = []
    for qn in sorted(set(declared) | available_ids, reverse=True):
        options.append(
            QualityOption(
                qn=qn,
                name=quality_name(qn),
                available=qn in available_ids,
                requires_login=qn in LOGIN_QUALITIES,
                requires_vip=qn in VIP_QUALITIES,
            )
        )
    return options
