"""Tests for the location tool."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from ribhus.tools.location import (
    LocationTool,
    clear_saved,
    format_location,
    load_saved,
    save_location,
)
from ribhus.tools.registry import default_registry


def test_save_load_clear(tmp_path: Path) -> None:
    ribhus = tmp_path / ".ribhus"
    save_location(
        ribhus,
        {
            "lat": 12.97,
            "lng": 77.64,
            "label": "Indiranagar, Bangalore",
            "source": "user",
        },
    )
    data = load_saved(ribhus)
    assert data is not None
    assert data["label"].startswith("Indiranagar")
    assert clear_saved(ribhus) is True
    assert load_saved(ribhus) is None


def test_format_location_includes_tip() -> None:
    text = format_location(
        {
            "lat": 12.9784,
            "lng": 77.6408,
            "label": "Indiranagar",
            "city": "Indiranagar",
            "source": "user",
            "accuracy": "user_set",
        }
    )
    assert "Indiranagar" in text
    assert "lat=" in text
    assert "search_place" in text
    assert "nearby" in text
    assert "fresh" in text.lower() or "this" in text.lower()


@pytest.mark.asyncio
async def test_nearby_lists_named_pois(tmp_path: Path) -> None:
    ribhus = tmp_path / ".ribhus"
    tool = LocationTool(ribhus_dir=ribhus, ip_lookup=False)
    fake_geo = {
        "lat": 12.9784,
        "lng": 77.6408,
        "label": "Indiranagar",
        "city": "Indiranagar",
        "source": "geocode",
        "accuracy": "place_name",
    }
    fake_places = [
        {
            "name": "Third Wave Coffee",
            "lat": 12.979,
            "lng": 77.641,
            "distance_m": 120,
            "cuisine": "coffee_shop",
            "address": "",
        },
        {
            "name": "Blue Tokai",
            "lat": 12.977,
            "lng": 77.639,
            "distance_m": 250,
            "cuisine": "",
            "address": "100 Feet Rd",
        },
    ]
    with (
        patch(
            "ribhus.tools.location.geocode_label",
            new=AsyncMock(return_value=fake_geo),
        ),
        patch(
            "ribhus.tools.location.nearby_pois",
            new=AsyncMock(return_value=fake_places),
        ),
    ):
        out = await tool.execute(
            {"action": "nearby", "kind": "cafe", "label": "Indiranagar"}
        )
    assert "Third Wave Coffee" in out
    assert "Blue Tokai" in out
    assert "Do NOT replace" in out
    assert "real map places" in out
    # label this turn must not stick to disk
    assert load_saved(ribhus) is None


@pytest.mark.asyncio
async def test_nearby_fresh_ignores_saved_home(tmp_path: Path) -> None:
    ribhus = tmp_path / ".ribhus"
    save_location(
        ribhus,
        {
            "lat": 18.52,
            "lng": 73.85,
            "label": "Pune",
            "city": "Pune",
            "source": "user",
        },
    )
    tool = LocationTool(ribhus_dir=ribhus, ip_lookup=True)
    fake_ip = {
        "lat": 19.07,
        "lng": 72.87,
        "label": "Mumbai, Maharashtra, India",
        "city": "Mumbai",
        "source": "ip",
        "accuracy": "city_approx",
    }
    fake_places = [
        {
            "name": "Cafe Madras",
            "lat": 19.07,
            "lng": 72.87,
            "distance_m": 100,
            "cuisine": "",
            "address": "",
        }
    ]
    with (
        patch(
            "ribhus.tools.location.lookup_ip",
            new=AsyncMock(return_value=fake_ip),
        ),
        patch(
            "ribhus.tools.device_location.lookup_device",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "ribhus.tools.location.nearby_pois",
            new=AsyncMock(return_value=fake_places),
        ),
    ):
        out = await tool.execute({"action": "nearby", "kind": "cafe"})
    assert "Mumbai" in out
    assert "Cafe Madras" in out
    assert "Pune" not in out
    # saved home unchanged
    assert load_saved(ribhus)["city"] == "Pune"


def test_format_nearby_empty() -> None:
    from ribhus.tools.location import format_nearby

    text = format_nearby([], kind="cafe", origin_label="Pune", radius_m=2000)
    assert "no named cafe" in text
    assert "Pune" in text


def test_format_nearby_includes_place_maps_link() -> None:
    from ribhus.tools.location import format_nearby

    text = format_nearby(
        [
            {
                "name": "Vaishali",
                "lat": 18.5204,
                "lng": 73.8430,
                "distance_m": 120,
                "cuisine": "south_indian",
                "address": "FC Road",
            }
        ],
        kind="restaurant",
        origin_label="FC Road, Pune",
        radius_m=2000,
    )
    assert "Vaishali" in text
    assert "[Open in Google Maps](" in text
    assert "google.com/maps/search/?api=1&query=" in text
    assert "/maps/dir/" not in text
    assert "NOT directions" in text


def test_enrich_answer_appends_missing_place_links() -> None:
    from ribhus.tools.location import enrich_answer_with_place_links, format_nearby

    tool = format_nearby(
        [
            {
                "name": "Cafe Good Luck",
                "lat": 18.523,
                "lng": 73.841,
                "distance_m": 266,
                "cuisine": "indian",
                "address": "",
            }
        ],
        kind="restaurant",
        origin_label="FC Road",
        radius_m=2000,
    )
    answer = "Try **Cafe Good Luck** near FC Road."
    out = enrich_answer_with_place_links(
        answer,
        messages=[{"role": "tool", "content": tool}],
    )
    assert "### Google Maps" in out
    assert "Cafe Good Luck" in out
    assert "[Open in Google Maps](" in out
    assert "/maps/dir/" not in out


@pytest.mark.asyncio
async def test_get_uses_saved(tmp_path: Path) -> None:
    ribhus = tmp_path / ".ribhus"
    save_location(
        ribhus,
        {"lat": 19.07, "lng": 72.87, "label": "Mumbai", "source": "user"},
    )
    tool = LocationTool(ribhus_dir=ribhus, ip_lookup=False)
    # Saved home only when fresh=false
    out = await tool.execute({"action": "get", "fresh": False})
    assert "Mumbai" in out
    assert "source: user" in out


@pytest.mark.asyncio
async def test_get_fresh_uses_live_ip(tmp_path: Path) -> None:
    ribhus = tmp_path / ".ribhus"
    save_location(
        ribhus,
        {"lat": 19.07, "lng": 72.87, "label": "Mumbai", "source": "user"},
    )
    tool = LocationTool(ribhus_dir=ribhus, ip_lookup=True)
    fake_ip = {
        "lat": 12.97,
        "lng": 77.59,
        "label": "Bengaluru, Karnataka, India",
        "city": "Bengaluru",
        "source": "ip",
        "accuracy": "city_approx",
    }
    with patch(
        "ribhus.tools.location.lookup_ip",
        new=AsyncMock(return_value=fake_ip),
    ), patch(
        "ribhus.tools.device_location.lookup_device",
        new=AsyncMock(return_value=None),
    ):
        out = await tool.execute({"action": "get"})
    assert "Bengaluru" in out
    assert "Mumbai" not in out


@pytest.mark.asyncio
async def test_get_uses_env_defaults(tmp_path: Path) -> None:
    tool = LocationTool(
        ribhus_dir=tmp_path / ".ribhus",
        default_lat=28.61,
        default_lng=77.20,
        default_label="Delhi",
        ip_lookup=False,
    )
    out = await tool.execute({"action": "get", "fresh": False})
    assert "Delhi" in out
    assert "env" in out


@pytest.mark.asyncio
async def test_set_with_coords(tmp_path: Path) -> None:
    ribhus = tmp_path / ".ribhus"
    tool = LocationTool(ribhus_dir=ribhus, ip_lookup=False)
    out = await tool.execute(
        {"action": "set", "label": "Koramangala", "lat": 12.93, "lng": 77.62}
    )
    assert "Saved" in out
    assert "Koramangala" in out
    saved = load_saved(ribhus)
    assert saved is not None
    assert saved["lat"] == 12.93


@pytest.mark.asyncio
async def test_set_geocodes_label(tmp_path: Path) -> None:
    ribhus = tmp_path / ".ribhus"
    tool = LocationTool(ribhus_dir=ribhus, ip_lookup=False)
    fake = {
        "lat": 12.97,
        "lng": 77.59,
        "label": "Bengaluru",
        "city": "Bengaluru",
        "country": "India",
        "source": "geocode",
        "accuracy": "place_name",
    }
    with patch(
        "ribhus.tools.location.geocode_label",
        new=AsyncMock(return_value=fake),
    ):
        out = await tool.execute({"action": "set", "label": "Bangalore"})
    assert "Saved" in out
    saved = load_saved(ribhus)
    assert saved is not None
    assert saved["lat"] == 12.97
    assert saved["label"] == "Bangalore"


@pytest.mark.asyncio
async def test_get_falls_back_to_ip(tmp_path: Path) -> None:
    from ribhus.tools.device_location import clear_device_cache

    clear_device_cache()
    tool = LocationTool(
        ribhus_dir=tmp_path / ".ribhus",
        ip_lookup=True,
        device_lookup=False,
    )
    fake = {
        "lat": 12.97,
        "lng": 77.59,
        "label": "Bengaluru, Karnataka, India",
        "city": "Bengaluru",
        "source": "ip",
        "accuracy": "city_approx",
    }
    with patch(
        "ribhus.tools.location.lookup_ip",
        new=AsyncMock(return_value=fake),
    ):
        out = await tool.execute({"action": "get"})
    assert "Bengaluru" in out
    assert "ip" in out


@pytest.mark.asyncio
async def test_get_unknown_without_sources(tmp_path: Path) -> None:
    from ribhus.tools.device_location import clear_device_cache

    clear_device_cache()
    tool = LocationTool(
        ribhus_dir=tmp_path / ".ribhus",
        ip_lookup=False,
        device_lookup=False,
    )
    out = await tool.execute({"action": "get"})
    assert out.startswith("Error:")


def test_default_registry_includes_location(tmp_path: Path) -> None:
    assert "location" in default_registry(tmp_path).names()


@pytest.mark.asyncio
async def test_nearby_label_overrides_ip(tmp_path: Path) -> None:
    """User-stated city must win over a wrong IP/saved guess — and not stick."""
    ribhus = tmp_path / ".ribhus"
    save_location(
        ribhus,
        {
            "lat": 28.61,
            "lng": 77.20,
            "label": "Delhi",
            "city": "Delhi",
            "source": "user",
            "accuracy": "user_set",
        },
    )
    tool = LocationTool(ribhus_dir=ribhus, ip_lookup=False)
    fake_geo = {
        "lat": 18.52,
        "lng": 73.85,
        "label": "Pune",
        "city": "Pune",
        "country": "India",
        "source": "geocode",
        "accuracy": "place_name",
    }
    fake_places = [
        {
            "name": "Cafe Goodluck",
            "lat": 18.52,
            "lng": 73.84,
            "distance_m": 400,
            "cuisine": "",
            "address": "Deccan",
        }
    ]
    with (
        patch(
            "ribhus.tools.location.geocode_label",
            new=AsyncMock(return_value=fake_geo),
        ),
        patch(
            "ribhus.tools.location.nearby_pois",
            new=AsyncMock(return_value=fake_places),
        ),
    ):
        out = await tool.execute(
            {"action": "nearby", "kind": "cafe", "label": "Pune"}
        )
    assert "Cafe Goodluck" in out
    assert "Pune" in out
    assert "Delhi" not in out
    # Must not overwrite saved home — next fresh ask re-detects live
    assert load_saved(ribhus)["city"] == "Delhi"


def test_normalize_place_capture_trims_junk() -> None:
    from ribhus.memory.extract import normalize_place_capture, extract_prefs_from_text

    assert normalize_place_capture("Pune and prefer") == "Pune"
    assert normalize_place_capture("Different Areas That") is None
    prefs = extract_prefs_from_text(
        "I live in Pune and prefer Hinglish. Budget under ₹8000."
    )
    assert any(p.key == "home_city" and "Pune" in p.content for p in prefs)
    bad = extract_prefs_from_text("I'm in different areas that look nice")
    assert not any(p.key == "home_city" for p in bad)


@pytest.mark.asyncio
async def test_get_from_memory_home_city(tmp_path: Path) -> None:
    class FakeRec:
        content = "Home city: Pune"
        disabled = False

    class FakeStore:
        def get_by_key(self, kind: str, key: str) -> Any:
            assert kind == "semantic"
            assert key == "home_city"
            return FakeRec()

    class FakeMemory:
        store = FakeStore()
        enabled = True

    tool = LocationTool(
        ribhus_dir=tmp_path / ".ribhus",
        memory=FakeMemory(),
        ip_lookup=False,
    )
    with patch(
        "ribhus.tools.location.geocode_label",
        new=AsyncMock(return_value=None),
    ):
        out = await tool.execute({"action": "get", "fresh": False})
    assert "Pune" in out
    assert "memory_home_city" in out
