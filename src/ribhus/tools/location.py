"""Resolve the user's location for “near me” queries.

Fresh live resolve (default for get/nearby):
1. Device GPS (macOS CoreLocation) when enabled
2. IP-based city approx

Sticky home (fresh=false only): saved file → env → memory home_city → live.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx

from ribhus.tools.base import Tool


def google_maps_place_url(*, name: str, lat: float, lng: float) -> str:
    """Google Maps place link (opens the venue), not a directions route."""
    label = (name or "").strip() or f"{lat:.5f},{lng:.5f}"
    query = quote_plus(f"{label} {lat:.6f},{lng:.6f}")
    return f"https://www.google.com/maps/search/?api=1&query={query}"

LOCATION_FILENAME = "location.json"
USER_AGENT = "Ribhus/0.1 (location tool; https://github.com/ribhus)"


def location_path(ribhus_dir: Path) -> Path:
    return Path(ribhus_dir) / LOCATION_FILENAME


def load_saved(ribhus_dir: Path) -> dict[str, Any] | None:
    path = location_path(ribhus_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def save_location(ribhus_dir: Path, data: dict[str, Any]) -> Path:
    path = location_path(ribhus_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def clear_saved(ribhus_dir: Path) -> bool:
    path = location_path(ribhus_dir)
    if not path.exists():
        return False
    path.unlink(missing_ok=True)
    return True


def format_location(data: dict[str, Any]) -> str:
    label = str(data.get("label") or "").strip()
    city = str(data.get("city") or "").strip()
    region = str(data.get("region") or "").strip()
    country = str(data.get("country") or "").strip()
    lat = data.get("lat")
    lng = data.get("lng")
    source = str(data.get("source") or "unknown").strip()
    accuracy = str(data.get("accuracy") or "").strip()

    place = label or ", ".join(p for p in (city, region, country) if p) or "(unknown)"
    # Prefer city+region for search queries (avoid long Nominatim display names).
    search_place = ", ".join(
        p for p in (city or (label.split(",")[0].strip() if label else ""), region, country) if p
    ) or place

    lines = [
        "location:",
        f"  place: {place}",
        f"  search_place: {search_place}",
    ]
    if lat is not None and lng is not None:
        try:
            lines.append(f"  coords: lat={float(lat):.5f} lng={float(lng):.5f}")
        except (TypeError, ValueError):
            lines.append(f"  coords: lat={lat} lng={lng}")
    lines.append(f"  source: {source}")
    if accuracy:
        lines.append(f"  accuracy: {accuracy}")
    if search_place and search_place != "(unknown)":
        lines.append(
            "  tip: Near-me asks should call location nearby each time (fresh live "
            "lookup). Pass label= only for the city named in *this* query. "
            "Never list Zomato/Yelp directory pages as venues."
        )
    return "\n".join(lines)


# OSM tags for common “near me” kinds
_NEARBY_TAGS: dict[str, tuple[str, str]] = {
    "cafe": ("amenity", "cafe"),
    "coffee": ("amenity", "cafe"),
    "cafes": ("amenity", "cafe"),
    "restaurant": ("amenity", "restaurant"),
    "restaurants": ("amenity", "restaurant"),
    "food": ("amenity", "restaurant"),
    "bar": ("amenity", "bar"),
    "pub": ("amenity", "pub"),
    "hotel": ("tourism", "hotel"),
    "hotels": ("tourism", "hotel"),
    "atm": ("amenity", "atm"),
    "pharmacy": ("amenity", "pharmacy"),
    "hospital": ("amenity", "hospital"),
    "park": ("leisure", "park"),
    "gym": ("leisure", "fitness_centre"),
    "petrol": ("amenity", "fuel"),
    "fuel": ("amenity", "fuel"),
}

# Kinds that prefer vegetarian / vegan–friendly restaurants (family-veg asks)
_VEG_KINDS = frozenset(
    {
        "veg",
        "vegetarian",
        "vegan",
        "veg restaurant",
        "vegetarian restaurant",
        "pure veg",
        "pure-veg",
    }
)


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    r = 6_371_000.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    )
    return 2 * r * asin(sqrt(a))


def _overpass_query(*, lat: float, lng: float, kind: str, radius_m: int, limit: int) -> str:
    key = kind.strip().lower() or "cafe"
    around = f"(around:{radius_m},{lat},{lng})"
    if key in _VEG_KINDS:
        # Vegetarian / vegan–tagged restaurants + common cuisine tags
        return (
            f"[out:json][timeout:25];\n"
            f"(\n"
            f'  node["amenity"="restaurant"]["diet:vegetarian"="yes"]{around};\n'
            f'  way["amenity"="restaurant"]["diet:vegetarian"="yes"]{around};\n'
            f'  node["amenity"="restaurant"]["diet:vegan"~"yes|only"]{around};\n'
            f'  way["amenity"="restaurant"]["diet:vegan"~"yes|only"]{around};\n'
            f'  node["amenity"="restaurant"]["cuisine"~"vegetarian|vegan|indian",i]{around};\n'
            f'  way["amenity"="restaurant"]["cuisine"~"vegetarian|vegan|indian",i]{around};\n'
            f");\n"
            f"out center tags {limit * 4};"
        )
    tag_key, tag_val = _NEARBY_TAGS.get(key, ("amenity", "cafe"))
    return (
        f"[out:json][timeout:25];\n"
        f"(\n"
        f'  node["{tag_key}"="{tag_val}"]{around};\n'
        f'  way["{tag_key}"="{tag_val}"]{around};\n'
        f");\n"
        f"out center tags {limit * 3};"
    )


async def nearby_pois(
    *,
    lat: float,
    lng: float,
    kind: str = "cafe",
    radius_m: int = 2000,
    limit: int = 10,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """OpenStreetMap Overpass — real named places near lat/lng."""
    key = kind.strip().lower() or "cafe"
    radius_m = max(200, min(int(radius_m), 10_000))
    limit = max(1, min(int(limit), 20))
    query = _overpass_query(
        lat=lat, lng=lng, kind=key, radius_m=radius_m, limit=limit
    )
    own = client is None
    http = client or httpx.AsyncClient(timeout=30.0, headers={"User-Agent": USER_AGENT})
    try:
        resp = await http.post(
            "https://overpass-api.de/api/interpreter",
            content=query.encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        payload = resp.json()
        elements = payload.get("elements") if isinstance(payload, dict) else None
        if not isinstance(elements, list):
            return []
        places: list[dict[str, Any]] = []
        for el in elements:
            tags = el.get("tags") or {}
            name = str(tags.get("name") or "").strip()
            if not name:
                continue
            if "lat" in el and "lon" in el:
                plat, plng = float(el["lat"]), float(el["lon"])
            else:
                center = el.get("center") or {}
                if "lat" not in center or "lon" not in center:
                    continue
                plat, plng = float(center["lat"]), float(center["lon"])
            dist = _haversine_m(lat, lng, plat, plng)
            places.append(
                {
                    "name": name,
                    "lat": plat,
                    "lng": plng,
                    "distance_m": int(dist),
                    "cuisine": str(tags.get("cuisine") or "").strip(),
                    "address": str(
                        tags.get("addr:full")
                        or tags.get("addr:street")
                        or tags.get("addr:place")
                        or ""
                    ).strip(),
                }
            )
        places.sort(key=lambda p: p["distance_m"])
        # Dedupe by name
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for p in places:
            key_n = p["name"].casefold()
            if key_n in seen:
                continue
            seen.add(key_n)
            unique.append(p)
            if len(unique) >= limit:
                break
        return unique
    except Exception:  # noqa: BLE001
        return []
    finally:
        if own:
            await http.aclose()


def format_nearby(
    places: list[dict[str, Any]],
    *,
    kind: str,
    origin_label: str,
    radius_m: int,
) -> str:
    if not places:
        return (
            f"nearby: no named {kind} POIs within {radius_m}m of {origin_label} "
            f"on OpenStreetMap. Try web_search “best {kind} in {origin_label}” "
            "then web_extract a list article — list venue *names*, not directory sites. "
            "For each venue, include a Google Maps *place* link "
            "(maps/search/?api=1&query=…), not directions."
        )
    lines = [
        f"nearby {kind} (within {radius_m}m of {origin_label}) — real map places:",
    ]
    for i, p in enumerate(places, start=1):
        dist = p["distance_m"]
        dist_s = f"{dist}m" if dist < 1000 else f"{dist / 1000:.1f}km"
        extra = []
        if p.get("cuisine"):
            extra.append(p["cuisine"])
        if p.get("address"):
            extra.append(p["address"])
        suffix = f" ({'; '.join(extra)})" if extra else ""
        maps_url = google_maps_place_url(
            name=str(p["name"]), lat=float(p["lat"]), lng=float(p["lng"])
        )
        # Keep place link on the same line so truncated previews still include it.
        lines.append(
            f"{i}. {p['name']} — {dist_s}{suffix} "
            f"[lat={p['lat']:.5f} lng={p['lng']:.5f}] "
            f"[Open in Google Maps]({maps_url})"
        )
    lines.append(
        "Present these as venue recommendations. Keep each "
        "[Open in Google Maps](…) markdown place link in your answer "
        "(opens the restaurant — NOT directions). Do NOT replace them with "
        "Zomato/Yelp/TripAdvisor/“coffee shops near me” website listings."
    )
    return "\n".join(lines)


_PLACE_LINE_RE = re.compile(
    r"^\s*\d+\.\s+(?P<name>.+?)\s+[—\-]\s+.*?\[lat=(?P<lat>-?\d+(?:\.\d+)?)\s+"
    r"lng=(?P<lng>-?\d+(?:\.\d+)?)\]"
    r"(?:.*?\[[^\]]*Open in Google Maps[^\]]*\]\((?P<url>https?://[^)\s]+)\))?",
    re.IGNORECASE | re.MULTILINE,
)


def parse_nearby_place_links(tool_text: str) -> list[dict[str, str]]:
    """Extract venue name + Google Maps place URL from location nearby output."""
    text = tool_text or ""
    places: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in _PLACE_LINE_RE.finditer(text):
        name = (match.group("name") or "").strip()
        if not name:
            continue
        url = (match.group("url") or "").strip()
        if not url:
            try:
                lat = float(match.group("lat"))
                lng = float(match.group("lng"))
            except (TypeError, ValueError):
                continue
            url = google_maps_place_url(name=name, lat=lat, lng=lng)
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        places.append({"name": name, "url": url})
    if places:
        return places
    for m in re.finditer(
        r"\[Open in Google Maps\]\((https://(?:www\.)?google\.[^/\s]+/maps/search/\?[^)\s]+)\)",
        text,
        flags=re.I,
    ):
        url = m.group(1)
        if url not in seen:
            seen.add(url)
            places.append({"name": "Place", "url": url})
    return places


def enrich_answer_with_place_links(
    answer: str,
    *,
    messages: list[dict[str, Any]] | None = None,
    tool_texts: list[str] | None = None,
) -> str:
    """If the model omitted Maps place links, append them from nearby tool output."""
    text = (answer or "").strip()
    blobs: list[str] = list(tool_texts or [])
    for msg in messages or []:
        if msg.get("role") != "tool":
            continue
        content = msg.get("content")
        if isinstance(content, str) and content.strip():
            blobs.append(content)

    places: list[dict[str, str]] = []
    seen: set[str] = set()
    for blob in blobs:
        if "nearby" not in blob.casefold() and "lat=" not in blob:
            continue
        for place in parse_nearby_place_links(blob):
            key = place["name"].casefold()
            if key in seen:
                continue
            seen.add(key)
            places.append(place)

    if not places:
        return text

    if "maps/search" in text and all(
        place["name"].casefold() in text.casefold()
        and (place["url"] in text or "Open in Google Maps" in text)
        for place in places[:3]
    ):
        return text

    named = [p for p in places if p["name"].casefold() in text.casefold()]
    use = named if named else places
    missing = [p for p in use if p["url"] not in text]
    if not missing:
        return text

    lines = [text, "", "### Google Maps"]
    for place in missing:
        lines.append(f"- **{place['name']}** — [Open in Google Maps]({place['url']})")
    return "\n".join(lines)


def maps_places_for_task(
    *,
    prompt: str = "",
    result: str | None = None,
    events: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Build Google Maps place links for the dashboard (coords preferred, name search fallback)."""
    places: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(name: str, url: str) -> None:
        key = (name or "").casefold() or url
        if key in seen or not url:
            return
        seen.add(key)
        places.append({"name": name or "Place", "url": url})

    blobs: list[str] = []
    if result:
        blobs.append(result)
    for ev in events or []:
        data = ev.get("data") if isinstance(ev, dict) else None
        if not isinstance(data, dict):
            continue
        if str(data.get("name") or "") not in {"", "location"}:
            continue
        preview = data.get("result_preview") or data.get("result")
        if isinstance(preview, str) and preview.strip():
            blobs.append(preview)

    for blob in blobs:
        for place in parse_nearby_place_links(blob):
            _add(place["name"], place["url"])

    if places:
        return places

    # Name-only fallback only for near-me / venue prompts
    prompt_l = (prompt or "").casefold()
    if not any(
        k in prompt_l
        for k in (
            "near",
            "restaurant",
            "cafe",
            "café",
            "hotel",
            "veg",
            "around",
        )
    ):
        return places

    area = ""
    m_area = re.search(
        r"\bnear\s+(.+?)(?:\s+family|\s+veg|\s+vegetarian|\s+for\b|$)",
        prompt or "",
        flags=re.I,
    )
    if m_area:
        area = m_area.group(1).strip(" .,;:")
    names = re.findall(r"\*\*([^*]{2,80})\*\*", result or "")
    skip = {
        "google maps",
        "snapshot",
        "sources",
        "offering",
        "customers / segment",
        "notable traction",
        "funding / investors",
        "recent news",
    }
    for raw in names:
        name = raw.strip().rstrip(":")
        if not name or name.casefold() in skip or name.endswith(":"):
            continue
        if ":" in name or "/" in name:
            continue
        if len(name.split()) > 8:
            continue
        query = f"{name} {area}".strip()
        url = f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"
        _add(name, url)
    return places


async def geocode_label(label: str, *, client: httpx.AsyncClient | None = None) -> dict[str, Any] | None:
    """OpenStreetMap Nominatim — free, no API key. Label → lat/lng."""
    q = label.strip()
    if not q:
        return None
    own = client is None
    http = client or httpx.AsyncClient(timeout=15.0, headers={"User-Agent": USER_AGENT})
    try:
        resp = await http.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": q, "format": "json", "limit": 1},
        )
        resp.raise_for_status()
        rows = resp.json()
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0]
        lat = float(row["lat"])
        lng = float(row["lon"])
        display = str(row.get("display_name") or q)
        return {
            "lat": lat,
            "lng": lng,
            "label": display.split(",")[0].strip() or q,
            "city": display.split(",")[0].strip() or q,
            "country": display.split(",")[-1].strip() if "," in display else "",
            "source": "geocode",
            "accuracy": "place_name",
        }
    except Exception:  # noqa: BLE001
        return None
    finally:
        if own:
            await http.aclose()


async def reverse_geocode(
    lat: float,
    lng: float,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any] | None:
    """Nominatim reverse — lat/lng → city/area label."""
    own = client is None
    http = client or httpx.AsyncClient(timeout=12.0, headers={"User-Agent": USER_AGENT})
    try:
        resp = await http.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": f"{lat:.6f}",
                "lon": f"{lng:.6f}",
                "format": "json",
                "zoom": 14,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return None
        addr = data.get("address") or {}
        city = str(
            addr.get("city")
            or addr.get("town")
            or addr.get("village")
            or addr.get("suburb")
            or addr.get("county")
            or ""
        ).strip()
        region = str(addr.get("state") or "").strip()
        country = str(addr.get("country") or "").strip()
        neighbourhood = str(
            addr.get("neighbourhood") or addr.get("suburb") or addr.get("road") or ""
        ).strip()
        label_parts = [p for p in (neighbourhood or city, city if neighbourhood else None, region) if p]
        # dedupe consecutive
        cleaned: list[str] = []
        for p in label_parts:
            if not cleaned or cleaned[-1].casefold() != p.casefold():
                cleaned.append(p)
        label = ", ".join(cleaned) or str(data.get("display_name") or "").split(",")[0]
        return {
            "label": label or f"{lat:.5f},{lng:.5f}",
            "city": city or (cleaned[0] if cleaned else ""),
            "region": region,
            "country": country,
        }
    except Exception:  # noqa: BLE001
        return None
    finally:
        if own:
            await http.aclose()


async def lookup_ip(*, client: httpx.AsyncClient | None = None) -> dict[str, Any] | None:
    """Approximate city from public IP (ipapi.co). Not precise GPS."""
    own = client is None
    http = client or httpx.AsyncClient(timeout=12.0, headers={"User-Agent": USER_AGENT})
    try:
        resp = await http.get("https://ipapi.co/json/")
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or data.get("error"):
            return None
        lat = data.get("latitude")
        lng = data.get("longitude")
        if lat is None or lng is None:
            return None
        city = str(data.get("city") or "").strip()
        region = str(data.get("region") or "").strip()
        country = str(data.get("country_name") or data.get("country") or "").strip()
        label = ", ".join(p for p in (city, region, country) if p) or "approximate IP location"
        return {
            "lat": float(lat),
            "lng": float(lng),
            "label": label,
            "city": city,
            "region": region,
            "country": country,
            "source": "ip",
            "accuracy": "city_approx (IP — not GPS)",
        }
    except Exception:  # noqa: BLE001
        return None
    finally:
        if own:
            await http.aclose()


def _home_city_from_memory(memory: Any) -> str | None:
    if memory is None:
        return None
    try:
        from ribhus.memory.extract import is_plausible_place

        rec = memory.store.get_by_key("semantic", "home_city")
        if rec is None or getattr(rec, "disabled", False):
            return None
        content = str(getattr(rec, "content", "") or "")
        # "Home city: Bangalore" → Bangalore
        if ":" in content:
            content = content.split(":", 1)[1]
        place = content.strip()
        if not place or not is_plausible_place(place):
            return None
        return place
    except Exception:  # noqa: BLE001
        return None


class LocationTool(Tool):
    name = "location"
    description = (
        "Live user location and nearby places (includes Google Maps place links). "
        "Fresh resolve prefers device GPS (macOS), then IP city. "
        "For “near me” / restaurants / cafes: action=nearby each time. "
        "If the user named a city/area this turn, pass label=<place> (this query only). "
        "kind=restaurant or kind=veg for vegetarian. "
        "action=set only when they ask to remember home. "
        "Prefer nearby over web_search; use maps place for a pin, "
        "maps directions only when asked how to get there."
    )
    risk_level = "low"

    def __init__(
        self,
        *,
        ribhus_dir: Path,
        memory: Any = None,
        default_lat: float | None = None,
        default_lng: float | None = None,
        default_label: str = "",
        ip_lookup: bool = True,
        device_lookup: bool = True,
    ) -> None:
        self.ribhus_dir = Path(ribhus_dir)
        self.memory = memory
        self.default_lat = default_lat
        self.default_lng = default_lng
        self.default_label = (default_label or "").strip()
        self.ip_lookup = ip_lookup
        self.device_lookup = device_lookup

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "set", "clear", "nearby"],
                    "description": (
                        "get=live location; nearby=POIs around live/label place; "
                        "set=remember home (only if user asks); clear=forget home"
                    ),
                },
                "label": {
                    "type": "string",
                    "description": (
                        "City/area for this query only (nearby/get). "
                        "Does not stick for later asks unless action=set."
                    ),
                },
                "lat": {
                    "type": "number",
                    "description": "Latitude (for set)",
                },
                "lng": {
                    "type": "number",
                    "description": "Longitude (for set)",
                },
                "kind": {
                    "type": "string",
                    "description": (
                        "For nearby: cafe, restaurant, veg/vegetarian, hotel, "
                        "bar, pharmacy, atm, park, gym, petrol (default cafe)"
                    ),
                    "default": "cafe",
                },
                "radius_m": {
                    "type": "integer",
                    "description": "Search radius in meters for nearby (default 2000, max 10000)",
                    "default": 2000,
                },
                "limit": {
                    "type": "integer",
                    "description": "Max nearby results (default 8, max 20)",
                    "default": 8,
                },
                "fresh": {
                    "type": "boolean",
                    "description": (
                        "If true (default for get/nearby): ignore saved home and "
                        "re-detect via live IP (or label this turn). "
                        "Set false only to use a previously set home base."
                    ),
                    "default": True,
                },
            },
            "required": ["action"],
        }

    def _fresh_flag(self, arguments: dict[str, Any], *, default: bool = True) -> bool:
        raw = arguments.get("fresh")
        if raw is None or raw == "":
            return default
        if isinstance(raw, bool):
            return raw
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    async def execute(self, arguments: dict[str, Any]) -> str:
        action = str(arguments.get("action") or "get").strip().lower()
        if action == "get":
            return await self._get(arguments)
        if action == "set":
            return await self._set(arguments)
        if action == "clear":
            cleared = clear_saved(self.ribhus_dir)
            return "location: cleared saved location." if cleared else "location: nothing saved."
        if action == "nearby":
            return await self._nearby(arguments)
        return "Error: action must be get, set, clear, or nearby"

    async def _resolve_live(self) -> dict[str, Any] | None:
        """Device GPS first, then network IP — never return a sticky city."""
        if self.device_lookup:
            try:
                from ribhus.tools.device_location import lookup_device

                device = await lookup_device()
                if device is not None:
                    return device
            except Exception:  # noqa: BLE001
                pass
        if not self.ip_lookup:
            return None
        return await lookup_ip()

    async def _resolve(self, *, fresh: bool = True) -> dict[str, Any] | None:
        """Resolve coordinates.

        fresh=True (default for near-me): live IP only — location can change
        every query. fresh=False: saved home → env → memory → IP.
        """
        if fresh:
            return await self._resolve_live()

        saved = load_saved(self.ribhus_dir)
        if saved and saved.get("lat") is not None and saved.get("lng") is not None:
            source = str(saved.get("source") or "")
            if source != "ip":
                return saved

        if self.default_lat is not None and self.default_lng is not None:
            return {
                "lat": self.default_lat,
                "lng": self.default_lng,
                "label": self.default_label
                or f"{self.default_lat:.4f},{self.default_lng:.4f}",
                "city": self.default_label.split(",")[0].strip() if self.default_label else "",
                "source": "env",
                "accuracy": "configured",
            }

        if self.default_label:
            geo = await geocode_label(self.default_label)
            if geo:
                geo["source"] = "env_geocode"
                return geo

        home = _home_city_from_memory(self.memory)
        if home:
            geo = await geocode_label(home)
            if geo:
                geo["source"] = "memory_home_city"
                geo["accuracy"] = "city (from memory home_city)"
                return geo
            return {
                "label": home,
                "city": home,
                "source": "memory_home_city",
                "accuracy": "city_label_only",
            }

        return await self._resolve_live()

    async def _place_this_turn(self, label: str) -> dict[str, Any] | str:
        """Geocode a user-stated place for this query only (no disk/memory write)."""
        geo = await geocode_label(label)
        if not geo:
            return (
                f"Error: could not geocode '{label}'. "
                "Try a clearer city/area name (e.g. Pune, Baner Pune)."
            )
        geo["label"] = label
        geo["city"] = label.split(",")[0].strip()
        geo["source"] = "query_label"
        geo["accuracy"] = "this_query_only"
        return geo

    async def _get(self, arguments: dict[str, Any]) -> str:
        fresh = self._fresh_flag(arguments, default=True)
        override = str(arguments.get("label") or "").strip()
        if override:
            data = await self._place_this_turn(override)
            if isinstance(data, str):
                return data
            return format_location(data) + "\n  note: this_query_only (not saved)"

        data = await self._resolve(fresh=fresh)
        if data is None:
            return (
                "Error: could not detect live location. Ask which city/area they "
                "are in now, then call location nearby with label=<city> "
                "(do not reuse an old city)."
            )
        text = format_location(data)
        if data.get("source") == "device":
            text += (
                "\n  note: device GPS for this query (precise). "
                "Use `maps` for directions from here."
            )
        elif data.get("source") == "ip":
            text += (
                "\n  note: live IP lookup (city-level). Enable Location Services "
                "for Ribhus/Terminal for device GPS, or pass label=<city>."
            )
        elif fresh:
            text += "\n  note: fresh resolve for this query"
        return text

    async def _nearby(self, arguments: dict[str, Any]) -> str:
        kind = str(arguments.get("kind") or "cafe").strip() or "cafe"
        fresh = self._fresh_flag(arguments, default=True)
        try:
            radius_m = int(arguments.get("radius_m") or 2000)
        except (TypeError, ValueError):
            radius_m = 2000
        try:
            limit = int(arguments.get("limit") or 8)
        except (TypeError, ValueError):
            limit = 8

        override = str(arguments.get("label") or "").strip()
        data: dict[str, Any] | None = None
        if override:
            placed = await self._place_this_turn(override)
            if isinstance(placed, str):
                return placed
            data = placed
        else:
            data = await self._resolve(fresh=fresh)

        if data is None:
            return (
                "Error: live location unknown. Ask which city/area they are in "
                "*right now*, then call location nearby label=<city> "
                "(every near-me ask should re-detect — do not reuse a prior city)."
            )

        lat, lng = data.get("lat"), data.get("lng")
        if lat is None or lng is None:
            label = str(data.get("label") or data.get("city") or "").strip()
            if label:
                geo = await geocode_label(label)
                if geo:
                    lat, lng = geo["lat"], geo["lng"]
                    data = {**data, **geo}
        if lat is None or lng is None:
            place = data.get("label") or data.get("city") or "your area"
            return (
                f"Error: no coordinates for {place}. "
                f"Call nearby with a clearer label, or web_search "
                f"“best {kind} in {place}” + web_extract for named venues."
            )

        origin = (
            str(data.get("label") or data.get("city") or "").strip()
            or f"{float(lat):.4f},{float(lng):.4f}"
        )
        places = await nearby_pois(
            lat=float(lat),
            lng=float(lng),
            kind=kind,
            radius_m=radius_m,
            limit=limit,
        )
        note = (
            f"\norigin_source: {data.get('source')} "
            f"(fresh={fresh}; not reused from a previous query)"
        )
        if data.get("source") == "ip":
            note += (
                "\nIf this city is wrong, re-call nearby with label=<correct city> "
                "or allow Location Services for device GPS."
            )
        return (
            format_nearby(places, kind=kind, origin_label=origin, radius_m=radius_m)
            + note
        )

    async def _set(self, arguments: dict[str, Any]) -> str:
        label = str(arguments.get("label") or "").strip()
        lat_raw = arguments.get("lat")
        lng_raw = arguments.get("lng")
        lat: float | None
        lng: float | None
        try:
            lat = float(lat_raw) if lat_raw is not None and lat_raw != "" else None
            lng = float(lng_raw) if lng_raw is not None and lng_raw != "" else None
        except (TypeError, ValueError):
            return "Error: lat/lng must be numbers"

        if lat is None and lng is None and not label:
            return "Error: set requires label and/or lat+lng"

        if (lat is None) ^ (lng is None):
            return "Error: provide both lat and lng together"

        data: dict[str, Any] = {"source": "user", "accuracy": "user_set"}
        if lat is not None and lng is not None:
            data["lat"] = lat
            data["lng"] = lng
        if label:
            data["label"] = label
            data["city"] = label.split(",")[0].strip()

        if lat is None and label:
            geo = await geocode_label(label)
            if geo:
                data.update(geo)
                data["source"] = "user_geocode"
                data["label"] = label  # keep user's shorter label
                data["accuracy"] = "geocoded_place"

        if data.get("lat") is None and not data.get("label"):
            return "Error: could not resolve that place"

        save_location(self.ribhus_dir, data)

        # Mirror into memory home_city when we have a city-ish label
        if self.memory is not None and data.get("label"):
            try:
                if getattr(self.memory, "enabled", False):
                    from ribhus.memory.extract import is_plausible_place

                    city = str(data.get("city") or data["label"]).split(",")[0].strip()
                    if city and is_plausible_place(city):
                        self.memory.remember_fact(f"Home city: {city}", key="home_city")
            except Exception:  # noqa: BLE001
                pass

        return (
            "Saved as home base (only used when fresh=false). "
            "Near-me queries still re-detect live by default. "
            + format_location(data)
        )
