"""Maps / directions via OSRM (no API key) + deep links."""

from __future__ import annotations

from typing import Any

import httpx

from ribhus.tools.base import Tool
from ribhus.tools.location import USER_AGENT, geocode_label, google_maps_place_url

OSRM_BASE = "https://router.project-osrm.org"

_PROFILES = {
    "driving": "driving",
    "drive": "driving",
    "car": "driving",
    "walking": "walking",
    "walk": "walking",
    "foot": "walking",
    "cycling": "cycling",
    "bike": "cycling",
    "bicycle": "cycling",
}


def _profile(mode: str) -> str:
    return _PROFILES.get((mode or "driving").strip().lower(), "driving")


def maps_links(
    *,
    from_lat: float,
    from_lng: float,
    to_lat: float,
    to_lng: float,
    mode: str = "driving",
) -> dict[str, str]:
    travel = {
        "driving": "driving",
        "walking": "walking",
        "cycling": "bicycling",
    }.get(_profile(mode), "driving")
    google = (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={from_lat:.6f},{from_lng:.6f}"
        f"&destination={to_lat:.6f},{to_lng:.6f}"
        f"&travelmode={travel}"
    )
    apple = (
        "https://maps.apple.com/"
        f"?saddr={from_lat:.6f},{from_lng:.6f}"
        f"&daddr={to_lat:.6f},{to_lng:.6f}"
        f"&dirflg={'w' if travel == 'walking' else 'd' if travel == 'driving' else 'c'}"
    )
    osm = (
        "https://www.openstreetmap.org/directions"
        f"?engine=fossgis_osrm_{_profile(mode)}"
        f"&route={from_lat:.6f}%2C{from_lng:.6f}%3B{to_lat:.6f}%2C{to_lng:.6f}"
    )
    return {"google": google, "apple": apple, "osm": osm}


def _fmt_duration(seconds: float) -> str:
    s = int(round(seconds))
    if s < 60:
        return f"{s}s"
    m, sec = divmod(s, 60)
    if m < 60:
        return f"{m} min" if sec < 30 else f"{m + 1} min"
    h, m = divmod(m, 60)
    return f"{h} h {m} min" if m else f"{h} h"


def _fmt_distance(meters: float) -> str:
    if meters < 1000:
        return f"{int(round(meters))} m"
    return f"{meters / 1000:.1f} km"


async def osrm_route(
    *,
    from_lat: float,
    from_lng: float,
    to_lat: float,
    to_lng: float,
    mode: str = "driving",
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any] | None:
    profile = _profile(mode)
    url = (
        f"{OSRM_BASE}/route/v1/{profile}/"
        f"{from_lng:.6f},{from_lat:.6f};{to_lng:.6f},{to_lat:.6f}"
    )
    own = client is None
    http = client or httpx.AsyncClient(timeout=20.0, headers={"User-Agent": USER_AGENT})
    try:
        resp = await http.get(
            url,
            params={"overview": "false", "steps": "true", "alternatives": "false"},
        )
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or data.get("code") != "Ok":
            return None
        routes = data.get("routes") or []
        if not routes:
            return None
        route = routes[0]
        legs = route.get("legs") or []
        steps_out: list[str] = []
        for leg in legs:
            for step in leg.get("steps") or []:
                name = (step.get("name") or "").strip()
                man = step.get("maneuver") or {}
                itype = str(man.get("type") or "")
                modifier = str(man.get("modifier") or "")
                dist = _fmt_distance(float(step.get("distance") or 0))
                instruction = " ".join(p for p in (itype.replace("_", " "), modifier) if p)
                if name:
                    steps_out.append(f"{instruction} onto {name} ({dist})".strip())
                elif instruction:
                    steps_out.append(f"{instruction} ({dist})")
                if len(steps_out) >= 12:
                    break
            if len(steps_out) >= 12:
                break
        return {
            "distance_m": float(route.get("distance") or 0),
            "duration_s": float(route.get("duration") or 0),
            "steps": steps_out,
            "mode": profile,
        }
    except Exception:  # noqa: BLE001
        return None
    finally:
        if own:
            await http.aclose()


class MapsTool(Tool):
    name = "maps"
    description = (
        "Directions, distance, and map links. "
        "Actions: place (Google Maps link to a venue — use for restaurant lists), "
        "directions (route + steps), distance (ETA only), link (route URLs). "
        "For venue recommendations use action=place (NOT directions). "
        "from/to = place name, 'here', or lat,lng. mode = driving|walking|cycling."
    )
    risk_level = "low"

    def __init__(self, *, location_tool: Any = None) -> None:
        self.location_tool = location_tool

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["place", "directions", "distance", "link"],
                    "description": (
                        "place=venue Google Maps link (not directions); "
                        "directions=full route; distance=ETA; link=route URLs"
                    ),
                },
                "from": {
                    "type": "string",
                    "description": "Origin place, 'here', or 'lat,lng' (default here; unused for place)",
                },
                "to": {
                    "type": "string",
                    "description": "Destination / place name or 'lat,lng'",
                },
                "mode": {
                    "type": "string",
                    "enum": ["driving", "walking", "cycling"],
                    "default": "driving",
                },
            },
            "required": ["action", "to"],
        }

    async def execute(self, arguments: dict[str, Any]) -> str:
        action = str(arguments.get("action") or "directions").strip().lower()
        origin_s = str(arguments.get("from") or "here").strip() or "here"
        dest_s = str(arguments.get("to") or "").strip()
        mode = str(arguments.get("mode") or "driving").strip() or "driving"
        if not dest_s:
            return "Error: to (destination) is required"

        dest = await self._resolve_point(dest_s)
        if isinstance(dest, str):
            return dest

        if action == "place":
            url = google_maps_place_url(
                name=str(dest["label"]),
                lat=float(dest["lat"]),
                lng=float(dest["lng"]),
            )
            return (
                f"maps place:\n"
                f"  name: {dest['label']}\n"
                f"  coords: {dest['lat']:.5f},{dest['lng']:.5f}\n"
                f"  [Open in Google Maps]({url})\n"
                f"  (This opens the place — not turn-by-turn directions.)"
            )

        origin = await self._resolve_point(origin_s)
        if isinstance(origin, str):
            return origin

        links = maps_links(
            from_lat=origin["lat"],
            from_lng=origin["lng"],
            to_lat=dest["lat"],
            to_lng=dest["lng"],
            mode=mode,
        )

        if action == "link":
            return (
                f"maps link ({_profile(mode)}):\n"
                f"  from: {origin['label']}\n"
                f"  to: {dest['label']}\n"
                f"  Google: {links['google']}\n"
                f"  Apple: {links['apple']}\n"
                f"  OSM: {links['osm']}"
            )

        route = await osrm_route(
            from_lat=origin["lat"],
            from_lng=origin["lng"],
            to_lat=dest["lat"],
            to_lng=dest["lng"],
            mode=mode,
        )
        if route is None:
            return (
                f"Error: no route found ({origin['label']} → {dest['label']}). "
                f"Try opening: {links['google']}"
            )

        dist = _fmt_distance(route["distance_m"])
        dur = _fmt_duration(route["duration_s"])
        lines = [
            f"maps {_profile(mode)}:",
            f"  from: {origin['label']} [{origin['lat']:.5f},{origin['lng']:.5f}]",
            f"  to: {dest['label']} [{dest['lat']:.5f},{dest['lng']:.5f}]",
            f"  distance: {dist}",
            f"  duration: ~{dur}",
        ]
        if action == "distance":
            lines.append(f"  Google: {links['google']}")
            return "\n".join(lines)

        if route["steps"]:
            lines.append("  steps:")
            for i, step in enumerate(route["steps"], start=1):
                lines.append(f"    {i}. {step}")
        lines.append(f"  Google: {links['google']}")
        lines.append(f"  Apple: {links['apple']}")
        return "\n".join(lines)

    async def _resolve_point(self, raw: str) -> dict[str, Any] | str:
        text = raw.strip()
        low = text.casefold()
        if low in {"here", "me", "current", "my location", "near me"}:
            return await self._here()

        # lat,lng
        if "," in text:
            parts = [p.strip() for p in text.split(",", 1)]
            if len(parts) == 2:
                try:
                    lat, lng = float(parts[0]), float(parts[1])
                    if abs(lat) <= 90 and abs(lng) <= 180:
                        return {
                            "lat": lat,
                            "lng": lng,
                            "label": f"{lat:.5f},{lng:.5f}",
                        }
                except ValueError:
                    pass

        geo = await geocode_label(text)
        if geo is None:
            return f"Error: could not find place '{text}'"
        return {
            "lat": float(geo["lat"]),
            "lng": float(geo["lng"]),
            "label": str(geo.get("label") or text),
        }

    async def _here(self) -> dict[str, Any] | str:
        # Prefer location tool live resolve when wired
        if self.location_tool is not None:
            try:
                data = await self.location_tool._resolve(fresh=True)
                if data and data.get("lat") is not None and data.get("lng") is not None:
                    return {
                        "lat": float(data["lat"]),
                        "lng": float(data["lng"]),
                        "label": str(
                            data.get("label") or data.get("city") or "current location"
                        ),
                    }
            except Exception:  # noqa: BLE001
                pass
        try:
            from ribhus.tools.device_location import lookup_device
            from ribhus.tools.location import lookup_ip

            device = await lookup_device()
            if device:
                return {
                    "lat": float(device["lat"]),
                    "lng": float(device["lng"]),
                    "label": str(device.get("label") or "device location"),
                }
            ip = await lookup_ip()
            if ip:
                return {
                    "lat": float(ip["lat"]),
                    "lng": float(ip["lng"]),
                    "label": str(ip.get("label") or "IP location"),
                }
        except Exception:  # noqa: BLE001
            pass
        return (
            "Error: could not resolve 'here'. Call location get first, or pass "
            "from=<city> / from=lat,lng."
        )
