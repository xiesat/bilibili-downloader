"""全局常量：接口地址、画质表、默认请求头。"""

from __future__ import annotations

__all__ = [
    "DEFAULT_USER_AGENT",
    "REFERER",
    "API_WEB",
    "API_PLAYER",
    "API_PASSPORT",
    "QUALITY_NAMES",
    "VIP_QUALITIES",
    "LOGIN_QUALITIES",
    "CODEC_PREFERENCE",
    "AUDIO_QUALITY_NAMES",
    "quality_name",
]

#: 默认 UA（伪装成常见桌面浏览器）
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

#: B 站 CDN 会校验 Referer，缺失直接 403
REFERER = "https://www.bilibili.com/"

API_WEB = "https://api.bilibili.com/x/web-interface"
API_PLAYER = "https://api.bilibili.com/x/player"
API_PASSPORT = "https://passport.bilibili.com/x/passport-login/web"

#: 画质 id(qn) -> 中文名称
QUALITY_NAMES: dict[int, str] = {
    127: "8K 超高清",
    126: "杜比视界",
    125: "HDR 真彩",
    120: "4K 超清",
    116: "1080P60 高帧率",
    112: "1080P+ 高码率",
    100: "智能修复",
    80: "1080P 高清",
    74: "720P60 高帧率",
    64: "720P 高清",
    32: "480P 清晰",
    16: "360P 流畅",
    6: "240P 极速",
}

#: 需要大会员的画质
VIP_QUALITIES: frozenset[int] = frozenset({112, 116, 120, 125, 126, 127})

#: 需要登录才能拿到的画质
LOGIN_QUALITIES: frozenset[int] = frozenset({100, 80, 74, 64})

#: 编码优先级：H.264 兼容性最好，避免部分播放器打不开 HEVC / AV1
CODEC_PREFERENCE: tuple[str, ...] = ("avc1", "hev1", "hvc1", "av01")

#: 音频流 id -> 名称
AUDIO_QUALITY_NAMES: dict[int, str] = {
    30216: "64K",
    30232: "132K",
    30280: "192K",
    30250: "杜比全景声",
    30251: "Hi-Res 无损",
}


def quality_name(qn: int) -> str:
    """把画质 id 转成可读名称。"""
    return QUALITY_NAMES.get(qn, f"qn{qn}")
