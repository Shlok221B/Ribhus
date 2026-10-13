"""Tests for device GPS helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ribhus.tools.device_location import _parse_device_json, clear_device_cache, lookup_device


def test_parse_device_json_ok() -> None:
    data = _parse_device_json('{"lat":18.5204,"lng":73.8567,"accuracy_m":35.2}\n')
    assert data is not None
    assert abs(data["lat"] - 18.5204) < 1e-6
    assert data["source"] == "device"
    assert "GPS" in data["accuracy"]


def test_parse_device_json_error() -> None:
    assert _parse_device_json('{"error":"location_denied"}') is None
    assert _parse_device_json("not-json") is None


@pytest.mark.asyncio
async def test_lookup_device_prefers_macos() -> None:
    clear_device_cache()
    fake = {
        "lat": 18.52,
        "lng": 73.85,
        "label": "18.52000,73.85000",
        "city": "",
        "source": "device",
        "accuracy": "30m GPS",
    }
    with (
        patch("ribhus.tools.device_location.platform.system", return_value="Darwin"),
        patch(
            "ribhus.tools.device_location.lookup_macos_sync",
            return_value=fake,
        ),
        patch(
            "ribhus.tools.location.reverse_geocode",
            new=AsyncMock(
                return_value={
                    "label": "Koregaon Park, Pune",
                    "city": "Pune",
                    "region": "Maharashtra",
                    "country": "India",
                }
            ),
        ),
    ):
        out = await lookup_device(use_cache=False)
    assert out is not None
    assert out["source"] == "device"
    assert "Pune" in out["label"]


@pytest.mark.asyncio
async def test_resolve_live_prefers_device(tmp_path) -> None:
    from ribhus.tools.location import LocationTool

    tool = LocationTool(
        ribhus_dir=tmp_path / ".ribhus",
        ip_lookup=True,
        device_lookup=True,
    )
    fake_device = {
        "lat": 18.52,
        "lng": 73.85,
        "label": "Pune",
        "city": "Pune",
        "source": "device",
        "accuracy": "25m GPS",
    }
    with (
        patch(
            "ribhus.tools.device_location.lookup_device",
            new=AsyncMock(return_value=fake_device),
        ),
        patch(
            "ribhus.tools.location.lookup_ip",
            new=AsyncMock(return_value={"lat": 28.6, "lng": 77.2, "label": "Delhi", "source": "ip"}),
        ),
    ):
        data = await tool._resolve_live()
    assert data is not None
    assert data["source"] == "device"
    assert "Pune" in data["label"]
