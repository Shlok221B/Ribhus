"""Tests for maps / directions tool."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ribhus.tools.maps import MapsTool, _fmt_distance, _fmt_duration, maps_links
from ribhus.tools.registry import default_registry


def test_maps_links_contain_coords() -> None:
    links = maps_links(
        from_lat=18.52,
        from_lng=73.85,
        to_lat=18.53,
        to_lng=73.86,
        mode="driving",
    )
    assert "18.520000" in links["google"]
    assert "maps.apple.com" in links["apple"]
    assert "openstreetmap.org" in links["osm"]


def test_fmt_helpers() -> None:
    assert _fmt_distance(250) == "250 m"
    assert "km" in _fmt_distance(2500)
    assert "min" in _fmt_duration(320)


def test_default_registry_includes_maps(tmp_path: Path) -> None:
    assert "maps" in default_registry(tmp_path).names()


@pytest.mark.asyncio
async def test_directions_formats_route(tmp_path: Path) -> None:
    tool = MapsTool(location_tool=None)
    fake_from = {
        "lat": 18.52,
        "lng": 73.85,
        "label": "Pune",
        "city": "Pune",
        "source": "geocode",
    }
    fake_to = {
        "lat": 18.56,
        "lng": 73.78,
        "label": "Hinjewadi",
        "city": "Hinjewadi",
        "source": "geocode",
    }
    fake_route = {
        "distance_m": 12500.0,
        "duration_s": 1800.0,
        "steps": ["turn right onto Baner Road (200 m)", "continue (1.2 km)"],
        "mode": "driving",
    }

    async def fake_geocode(label: str, **kwargs):  # noqa: ANN003
        if "Hinjewadi" in label or "hinjewadi" in label.casefold():
            return fake_to
        return fake_from

    with (
        patch("ribhus.tools.maps.geocode_label", new=fake_geocode),
        patch(
            "ribhus.tools.maps.osrm_route",
            new=AsyncMock(return_value=fake_route),
        ),
    ):
        out = await tool.execute(
            {
                "action": "directions",
                "from": "Pune",
                "to": "Hinjewadi",
                "mode": "driving",
            }
        )
    assert "Hinjewadi" in out
    assert "12.5 km" in out or "distance" in out
    assert "Baner Road" in out
    assert "Google:" in out


@pytest.mark.asyncio
async def test_here_uses_device(tmp_path: Path) -> None:
    tool = MapsTool(location_tool=None)
    fake_device = {
        "lat": 18.52,
        "lng": 73.85,
        "label": "Koregaon Park",
        "source": "device",
    }
    fake_to = {
        "lat": 18.53,
        "lng": 73.86,
        "label": "Cafe Goodluck",
        "source": "geocode",
    }
    with (
        patch(
            "ribhus.tools.device_location.lookup_device",
            new=AsyncMock(return_value=fake_device),
        ),
        patch(
            "ribhus.tools.maps.geocode_label",
            new=AsyncMock(return_value=fake_to),
        ),
        patch(
            "ribhus.tools.maps.osrm_route",
            new=AsyncMock(
                return_value={
                    "distance_m": 800.0,
                    "duration_s": 600.0,
                    "steps": [],
                    "mode": "walking",
                }
            ),
        ),
    ):
        out = await tool.execute(
            {
                "action": "distance",
                "from": "here",
                "to": "Cafe Goodluck",
                "mode": "walking",
            }
        )
    assert "Koregaon Park" in out or "18.52" in out
    assert "Cafe Goodluck" in out
