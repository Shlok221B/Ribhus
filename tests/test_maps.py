"""Tests for maps / directions tool."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from ribhus.tools.location import google_maps_place_url
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
    assert "/maps/dir/" in links["google"]


def test_google_maps_place_url_is_search_not_directions() -> None:
    url = google_maps_place_url(name="Vaishali", lat=18.5204, lng=73.8430)
    assert "google.com/maps/search/?api=1&query=" in url
    assert "/maps/dir/" not in url
    assert "Vaishali" in url or "Vaishali" in url.replace("+", " ")


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


@pytest.mark.asyncio
async def test_place_action_returns_search_link_not_directions() -> None:
    tool = MapsTool(location_tool=None)
    fake = {
        "lat": 18.5204,
        "lng": 73.8430,
        "label": "Vaishali",
        "city": "Vaishali",
        "source": "geocode",
    }
    with patch("ribhus.tools.maps.geocode_label", new=AsyncMock(return_value=fake)):
        out = await tool.execute({"action": "place", "to": "Vaishali FC Road"})
    assert "maps place:" in out
    assert "[Open in Google Maps](" in out
    assert "maps/search/?api=1&query=" in out
    assert "/maps/dir/" not in out
    assert "not turn-by-turn" in out.casefold() or "not turn-by-turn" in out.lower()
