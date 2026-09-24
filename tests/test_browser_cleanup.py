"""Tests for Chromium profile lock release."""

from __future__ import annotations

from pathlib import Path

from ribhus.channels.browser_cleanup import (
    _pid_from_singleton_lock,
    force_release_profile,
)


def test_pid_from_singleton_lock_symlink(tmp_path: Path) -> None:
    lock = tmp_path / "SingletonLock"
    lock.symlink_to("Shloks-MacBook-Air.local-86472")
    assert _pid_from_singleton_lock(tmp_path) == 86472


def test_force_release_clears_singleton_files(tmp_path: Path) -> None:
    (tmp_path / "SingletonLock").symlink_to("host-1")  # pid 1 skipped / not our chrome
    (tmp_path / "SingletonCookie").write_text("x", encoding="utf-8")
    (tmp_path / "RunningChromeVersion").symlink_to("1.0")
    force_release_profile(tmp_path)
    assert not (tmp_path / "SingletonLock").exists()
    assert not (tmp_path / "SingletonCookie").exists()
    assert not (tmp_path / "RunningChromeVersion").exists()
