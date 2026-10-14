"""统一异常体系。

所有本项目抛出的异常都继承自 BiliError，
便于在任务层统一捕获并转成「任务失败」而不是让程序崩溃。
"""

from __future__ import annotations

__all__ = [
    "BiliError",
    "ConfigError",
    "NetworkError",
    "ApiError",
    "AuthRequiredError",
    "AuthExpiredError",
    "RiskControlError",
    "ParseError",
    "UnsupportedInputError",
    "VideoUnavailableError",
    "QualityUnavailableError",
    "DownloadError",
    "ChecksumError",
    "CancelledError",
    "MuxError",
    "FFmpegNotFoundError",
    "api_error_from_code",
]


class BiliError(Exception):
    """本项目所有异常的基类。"""

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self) -> str:
        return f"{self.message}（{self.detail}）" if self.detail else self.message


# ---------------------------------------------------------------------------
# 配置 / 网络
# ---------------------------------------------------------------------------
class ConfigError(BiliError):
    """配置文件读写失败或取值非法。"""


class NetworkError(BiliError):
    """网络请求失败（超时、连接中断等），通常可重试。"""


class RiskControlError(NetworkError):
    """被 B 站风控拦截（HTTP 412 / 接口 -412）。"""


# ---------------------------------------------------------------------------
# 接口层
# ---------------------------------------------------------------------------
class ApiError(BiliError):
    """接口返回了非 0 的业务 code。"""

    def __init__(self, code: int, message: str, *, detail: str | None = None) -> None:
        super().__init__(message, detail=detail)
        self.code = code


class AuthRequiredError(ApiError):
    """需要登录才能继续。"""


class AuthExpiredError(ApiError):
    """登录态已失效，需要重新登录。"""


class VideoUnavailableError(ApiError):
    """稿件不可见：已删除 / 审核中 / 仅 UP 主可见 / 地区限制。"""


# ---------------------------------------------------------------------------
# 解析层
# ---------------------------------------------------------------------------
class ParseError(BiliError):
    """输入解析失败。"""


class UnsupportedInputError(ParseError):
    """无法识别的输入形式。"""


class QualityUnavailableError(BiliError):
    """请求的画质当前账号或该视频无法提供。"""


# ---------------------------------------------------------------------------
# 下载层
# ---------------------------------------------------------------------------
class DownloadError(BiliError):
    """下载过程失败。"""


class ChecksumError(DownloadError):
    """下载完成后大小校验不通过。"""


class CancelledError(BiliError):
    """任务被用户取消。"""


class MuxError(BiliError):
    """音视频合并失败。"""


class FFmpegNotFoundError(BiliError):
    """未找到可用的 ffmpeg。"""


# ---------------------------------------------------------------------------
# B 站业务 code -> 异常
# ---------------------------------------------------------------------------
#: 已知的接口错误码含义
API_CODE_MESSAGES: dict[int, str] = {
    -101: "账号未登录",
    -102: "账号被封停",
    -400: "请求参数错误",
    -403: "权限不足，无法访问",
    -404: "请求的资源不存在",
    -412: "请求被风控拦截，请稍后重试",
    -509: "请求过于频繁，请稍后重试",
    -799: "请求过于频繁，请稍后重试",
    62002: "稿件不可见（可能已被删除）",
    62004: "稿件审核中",
    62012: "仅 UP 主自己可见",
}


def api_error_from_code(code: int, raw_message: str = "", *, detail: str | None = None) -> BiliError:
    """按业务 code 构造最贴切的异常类型。"""
    message = API_CODE_MESSAGES.get(code) or raw_message or f"接口返回错误码 {code}"
    if code == -101:
        return AuthRequiredError(code, message, detail=detail)
    if code == -412:
        return RiskControlError(message, detail=detail)
    if code in (62002, 62004, 62012):
        return VideoUnavailableError(code, message, detail=detail)
    return ApiError(code, message, detail=detail)
