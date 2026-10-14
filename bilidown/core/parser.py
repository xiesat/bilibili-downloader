"""输入解析：BV 号、av 号、完整链接、b23.tv 短链、合集链接与多行批量。

设计目标是把用户粘贴进来的各种形式统一归一化，
让上层只需要处理 ParsedRef，而不必关心原始文本长什么样。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

__all__ = ["InputKind", "ParsedRef", "parse_one", "parse_lines", "extract_bvid"]

#: BV 号固定为 BV + 10 位 base58 字符
_BV_RE = re.compile(r"BV[0-9A-Za-z]{10}")

#: av 号
_AV_RE = re.compile(r"\bav(\d+)", re.IGNORECASE)

#: b23.tv 短链
_SHORT_RE = re.compile(r"(?:https?://)?b23\.tv/[0-9A-Za-z]+", re.IGNORECASE)

#: 合集 / 系列：space.bilibili.com/<mid>/channel/collectiondetail?sid=<sid>
_COLLECTION_RE = re.compile(
    r"space\.bilibili\.com/(\d+)/channel/(?:collectiondetail|seriesdetail)[^\s]*?[?&]sid=(\d+)",
    re.IGNORECASE,
)

#: 分 P 参数
_PAGE_RE = re.compile(r"[?&]p=(\d+)")

#: 批量输入的分隔符（含中文标点）
_SPLIT_RE = re.compile(r"[\s,，、;；|]+")


class InputKind(StrEnum):
    """输入的类别。"""

    VIDEO = "video"
    """直接给出了 BV 号或 av 号。"""

    SHORTLINK = "shortlink"
    """b23.tv 短链，需要先跟随跳转。"""

    COLLECTION = "collection"
    """UP 主的合集或系列。"""

    UNKNOWN = "unknown"
    """无法识别。"""


@dataclass(slots=True)
class ParsedRef:
    """一条已归一化的输入引用。"""

    raw: str
    kind: InputKind = InputKind.UNKNOWN
    bvid: str = ""
    aid: int = 0
    page: int = 0
    mid: int = 0
    sid: int = 0
    url: str = ""
    error: str = ""

    @property
    def is_valid(self) -> bool:
        """是否成功识别。"""
        return self.kind is not InputKind.UNKNOWN

    @property
    def dedupe_key(self) -> tuple[object, ...]:
        """用于批量输入去重的键。"""
        return (self.kind.value, self.bvid, self.aid, self.mid, self.sid, self.page)

    @property
    def display(self) -> str:
        """界面上展示用的简短标识。"""
        if self.kind is InputKind.VIDEO:
            base = self.bvid or f"av{self.aid}"
            return f"{base} P{self.page}" if self.page else base
        if self.kind is InputKind.COLLECTION:
            return f"合集 sid={self.sid}"
        if self.kind is InputKind.SHORTLINK:
            return self.url
        return self.raw[:40]

    def as_params(self) -> dict[str, object]:
        """转成 view 接口需要的参数。"""
        if self.bvid:
            return {"bvid": self.bvid}
        if self.aid:
            return {"aid": self.aid}
        raise ValueError("该引用既没有 bvid 也没有 aid")


def extract_bvid(text: str) -> str:
    """从任意文本中提取第一个 BV 号。"""
    match = _BV_RE.search(text or "")
    return match.group(0) if match else ""


def parse_one(token: str) -> ParsedRef:
    """解析单个输入片段。"""
    raw = (token or "").strip()
    if not raw:
        return ParsedRef(raw=raw, error="空输入")

    ref = ParsedRef(raw=raw)

    collection = _COLLECTION_RE.search(raw)
    if collection:
        ref.kind = InputKind.COLLECTION
        ref.mid = int(collection.group(1))
        ref.sid = int(collection.group(2))
        return ref

    if _SHORT_RE.search(raw):
        ref.kind = InputKind.SHORTLINK
        ref.url = raw if raw.lower().startswith("http") else f"https://{raw}"
        return ref

    bv = _BV_RE.search(raw)
    if bv:
        ref.kind = InputKind.VIDEO
        ref.bvid = bv.group(0)
        page = _PAGE_RE.search(raw)
        ref.page = int(page.group(1)) if page else 0
        return ref

    av = _AV_RE.search(raw)
    if av:
        ref.kind = InputKind.VIDEO
        ref.aid = int(av.group(1))
        page = _PAGE_RE.search(raw)
        ref.page = int(page.group(1)) if page else 0
        return ref

    ref.error = "无法识别，请输入 BV 号 / av 号 / 视频链接"
    return ref


def parse_lines(text: str) -> tuple[list[ParsedRef], list[ParsedRef]]:
    """解析批量输入。

    支持用换行、空格、逗号、顿号、分号混合分隔，
    自动去重，并区分成功与失败项。

    返回一个二元组：前一项是有效引用列表，后一项是无效引用列表。
    """
    valid: list[ParsedRef] = []
    invalid: list[ParsedRef] = []
    seen: set[tuple[object, ...]] = set()

    for token in _SPLIT_RE.split(text or ""):
        if not token.strip():
            continue
        ref = parse_one(token)
        if not ref.is_valid:
            invalid.append(ref)
            continue
        if ref.dedupe_key in seen:
            continue
        seen.add(ref.dedupe_key)
        valid.append(ref)

    return valid, invalid
