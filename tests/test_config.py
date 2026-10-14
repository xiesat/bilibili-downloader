"""配置读写的单元测试。"""

from __future__ import annotations

from pathlib import Path

from bilidown.config import AppConfig, load_config, save_config


def test_defaults_are_valid() -> None:
    config = AppConfig().normalize()
    assert config.mode == "auto"
    assert config.codec_preference == "avc1"
    assert config.download_dir


def test_normalize_clamps_out_of_range() -> None:
    config = AppConfig(max_concurrent_videos=99, chunks_per_video=-5, max_retries=99)
    config.mode = "bogus"
    config.request_timeout = 9999
    config.normalize()
    assert config.max_concurrent_videos == 10
    assert config.chunks_per_video == 1
    assert config.max_retries == 10
    assert config.request_timeout == 300.0
    assert config.mode == "auto"


def test_cookie_is_not_persisted() -> None:
    config = AppConfig(cookie="SESSDATA=secret")
    payload = config.to_dict()
    assert "cookie" not in payload


def test_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    config = AppConfig(download_dir=str(tmp_path / "dl"), chunks_per_video=6)
    config.normalize()
    save_config(config, target)
    loaded = load_config(target)
    assert loaded.download_dir == config.download_dir
    assert loaded.chunks_per_video == 6


def test_corrupt_file_falls_back(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text("{ not json", encoding="utf-8")
    loaded = load_config(target)
    assert loaded.mode == "auto"


def test_unknown_fields_ignored(tmp_path: Path) -> None:
    target = tmp_path / "config.json"
    target.write_text('{"mode": "dash", "legacy_option": 1}', encoding="utf-8")
    loaded = load_config(target)
    assert loaded.mode == "dash"
