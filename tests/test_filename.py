"""文件名处理的单元测试。"""

from __future__ import annotations

from pathlib import Path

from bilidown.util.filename import format_duration, human_size, human_speed, sanitize, unique_path


def test_illegal_characters_replaced() -> None:
    assert sanitize('a<b>c:d"e/f\\g|h?i*j') == "a_b_c_d_e_f_g_h_i_j"


def test_trailing_dots_and_spaces_stripped() -> None:
    assert sanitize("  标题...   ") == "标题"


def test_reserved_device_names() -> None:
    assert sanitize("CON") == "_CON"
    assert sanitize("nul") == "_nul"


def test_empty_falls_back() -> None:
    assert sanitize("") == "untitled"
    assert sanitize("   ") == "untitled"


def test_long_name_truncated_with_hash() -> None:
    result = sanitize("x" * 500)
    assert len(result) <= 120
    assert "_" in result


def test_long_names_do_not_collide() -> None:
    a = sanitize("y" * 300 + "A")
    b = sanitize("y" * 300 + "B")
    assert a != b


def test_unique_path_avoids_existing(tmp_path: Path) -> None:
    first = unique_path(tmp_path, "video", ".mp4")
    assert first.name == "video.mp4"
    first.write_bytes(b"x")
    second = unique_path(tmp_path, "video", ".mp4")
    assert second.name == "video (1).mp4"


def test_human_size() -> None:
    assert human_size(0) == "—"
    assert human_size(51973319) == "49.6 MB"


def test_human_speed() -> None:
    assert human_speed(0) == "—"
    assert human_speed(1024).endswith("/s")


def test_format_duration() -> None:
    assert format_duration(212) == "3:32"
    assert format_duration(3725) == "1:02:05"
