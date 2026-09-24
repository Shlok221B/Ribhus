"""Release Chromium/Playwright profile locks left by crashed or interrupted sessions."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path


def _pid_from_singleton_lock(user_data_dir: Path) -> int | None:
    """Chrome SingletonLock is often a symlink named hostname-pid."""
    lock = user_data_dir / "SingletonLock"
    # Chrome's lock is a *broken* symlink (target is not a real path) — use
    # lexists / is_symlink, not exists() which follows and returns False.
    if not (lock.is_symlink() or lock.exists()):
        return None
    try:
        raw = os.readlink(lock) if lock.is_symlink() else lock.read_text(encoding="utf-8")
    except OSError:
        return None
    raw = str(raw).strip()
    # Forms: "host-12345" or just "12345"
    for part in reversed(raw.replace("/", "-").split("-")):
        if part.isdigit():
            pid = int(part)
            if pid > 1:
                return pid
    return None


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def _kill_pid_tree(pid: int) -> int:
    """Best-effort SIGTERM then SIGKILL a process (and try children via pkill -P)."""
    if not _pid_alive(pid):
        return 0
    try:
        subprocess.run(
            ["pkill", "-TERM", "-P", str(pid)],
            check=False,
            capture_output=True,
        )
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return 0
    except PermissionError:
        return 0
    deadline = time.time() + 2.0
    while time.time() < deadline and _pid_alive(pid):
        time.sleep(0.1)
    if _pid_alive(pid):
        try:
            subprocess.run(
                ["pkill", "-KILL", "-P", str(pid)],
                check=False,
                capture_output=True,
            )
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return 1


def _unlink_singleton(user_data_dir: Path) -> None:
    for name in (
        "SingletonLock",
        "SingletonCookie",
        "SingletonSocket",
        "RunningChromeVersion",
    ):
        path = user_data_dir / name
        try:
            # Broken symlinks: exists() is False; still must unlink.
            if path.is_symlink() or path.exists():
                path.unlink(missing_ok=True)
        except OSError:
            continue


def force_release_profile(user_data_dir: Path | None) -> int:
    """Kill Chromium still holding ``user_data_dir`` and clear Singleton* locks.

    Returns number of top-level processes we signaled via SingletonLock.
    """
    if user_data_dir is None:
        return 0
    path = Path(user_data_dir)
    if not path.exists():
        return 0
    killed = 0
    pid = _pid_from_singleton_lock(path)
    if pid is not None and _pid_alive(pid):
        killed += _kill_pid_tree(pid)
    # Match chrome-for-testing / Chromium launched with this user-data-dir.
    try:
        needle = str(path.resolve())
        subprocess.run(
            ["pkill", "-TERM", "-f", needle],
            check=False,
            capture_output=True,
        )
        time.sleep(0.4)
        subprocess.run(
            ["pkill", "-KILL", "-f", needle],
            check=False,
            capture_output=True,
        )
    except Exception:  # noqa: BLE001
        pass
    time.sleep(0.2)
    _unlink_singleton(path)
    return killed


def force_release_ribhus_browsers(ribhus_dir: Path) -> int:
    """Release WhatsApp / browser / Gmail Playwright profiles under ``.ribhus``."""
    total = 0
    for name in ("whatsapp_profile", "browser_profile", "gmail_profile"):
        total += force_release_profile(ribhus_dir / name)
    return total
