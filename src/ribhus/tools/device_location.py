"""Device GPS / system location (macOS CoreLocation) — preferred over IP."""

from __future__ import annotations

import asyncio
import json
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

# Soft cache so nearby + maps in the same turn don't re-prompt TCC.
_CACHE: dict[str, Any] | None = None
_CACHE_AT: float = 0.0
_CACHE_TTL_S = 45.0

_SWIFT_HELPER = Path(__file__).with_name("macos_location.swift")


def _parse_device_json(raw: str) -> dict[str, Any] | None:
    line = (raw or "").strip().splitlines()
    if not line:
        return None
    try:
        data = json.loads(line[-1])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("error"):
        return None
    try:
        lat = float(data["lat"])
        lng = float(data["lng"])
    except (KeyError, TypeError, ValueError):
        return None
    accuracy = data.get("accuracy_m")
    try:
        acc_s = f"{float(accuracy):.0f}m GPS" if accuracy is not None else "device GPS"
    except (TypeError, ValueError):
        acc_s = "device GPS"
    return {
        "lat": lat,
        "lng": lng,
        "label": f"{lat:.5f},{lng:.5f}",
        "city": "",
        "source": "device",
        "accuracy": acc_s,
    }


def lookup_macos_sync(*, timeout: float = 14.0) -> dict[str, Any] | None:
    """Blocking macOS CoreLocation via Swift helper. None if unavailable."""
    if platform.system() != "Darwin":
        return None
    if not _SWIFT_HELPER.is_file():
        return None
    swift = shutil.which("swift")
    if not swift:
        return None
    try:
        proc = subprocess.run(
            [swift, str(_SWIFT_HELPER)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return _parse_device_json(proc.stdout or "")


async def lookup_device(*, use_cache: bool = True) -> dict[str, Any] | None:
    """Best-effort precise device location. macOS first; else None (caller uses IP)."""
    global _CACHE, _CACHE_AT
    now = time.monotonic()
    if use_cache and _CACHE is not None and (now - _CACHE_AT) < _CACHE_TTL_S:
        return dict(_CACHE)

    data: dict[str, Any] | None = None
    if platform.system() == "Darwin":
        data = await asyncio.to_thread(lookup_macos_sync)

    if data is None:
        return None

    # Enrich with reverse-geocoded place name when possible.
    try:
        from ribhus.tools.location import reverse_geocode

        place = await reverse_geocode(float(data["lat"]), float(data["lng"]))
        if place:
            data = {**data, **place, "source": "device", "accuracy": data.get("accuracy")}
    except Exception:  # noqa: BLE001
        pass

    _CACHE = dict(data)
    _CACHE_AT = time.monotonic()
    return data


def clear_device_cache() -> None:
    global _CACHE, _CACHE_AT
    _CACHE = None
    _CACHE_AT = 0.0
