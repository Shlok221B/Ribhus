import type { ITaskEvent } from "@/lib/api";

export interface IMapsPlace {
  name: string;
  url: string;
}

const PLACE_LINE_RE =
  /^\s*\d+\.\s+(.+?)\s+[—–\-]\s+.*?\[lat=(-?\d+(?:\.\d+)?)\s+lng=(-?\d+(?:\.\d+)?)\]/gim;

const MD_MAPS_RE =
  /\[([^\]]*Open in Google Maps[^\]]*)\]\((https:\/\/(?:www\.)?google\.[^/\s]+\/maps\/search\/\?[^)\s]+)\)/gi;

const BARE_MAPS_RE =
  /(https:\/\/(?:www\.)?google\.[^/\s]+\/maps\/search\/\?[^\s)\]>]+)/gi;

const BOLD_NAME_RE = /\*\*([^*]{2,80})\*\*/g;

export const googleMapsPlaceUrl = (
  name: string,
  lat: number,
  lng: number,
): string => {
  const label = name.trim() || `${lat.toFixed(5)},${lng.toFixed(5)}`;
  const query = encodeURIComponent(
    `${label} ${lat.toFixed(6)},${lng.toFixed(6)}`,
  );
  return `https://www.google.com/maps/search/?api=1&query=${query}`;
};

export const googleMapsSearchUrl = (name: string, area = ""): string => {
  const query = encodeURIComponent(`${name} ${area}`.trim());
  return `https://www.google.com/maps/search/?api=1&query=${query}`;
};

const pushUnique = (places: IMapsPlace[], place: IMapsPlace) => {
  const key = place.name.toLowerCase();
  if (places.some((p) => p.name.toLowerCase() === key)) return;
  if (places.some((p) => p.url === place.url)) return;
  places.push(place);
};

export const parsePlacesFromText = (text: string): IMapsPlace[] => {
  const places: IMapsPlace[] = [];
  if (!text) return places;

  for (const match of text.matchAll(PLACE_LINE_RE)) {
    const name = (match[1] || "").trim();
    const lat = Number(match[2]);
    const lng = Number(match[3]);
    if (!name || Number.isNaN(lat) || Number.isNaN(lng)) continue;
    pushUnique(places, {
      name,
      url: googleMapsPlaceUrl(name, lat, lng),
    });
  }

  for (const match of text.matchAll(MD_MAPS_RE)) {
    const label = (match[1] || "Open in Google Maps").trim();
    const url = (match[2] || "").trim();
    if (!url) continue;
    const name =
      label.replace(/open in google maps/i, "").trim() || "Google Maps";
    pushUnique(places, {
      name: name === "Google Maps" ? "Place" : name,
      url,
    });
  }

  for (const match of text.matchAll(BARE_MAPS_RE)) {
    const url = (match[1] || "").replace(/[.,;:!?)]+$/, "");
    if (!url) continue;
    pushUnique(places, { name: "Place", url });
  }

  return places;
};

const areaFromPrompt = (prompt: string): string => {
  const m = prompt.match(
    /\bnear\s+(.+?)(?:\s+family|\s+veg|\s+vegetarian|\s+for\b|$)/i,
  );
  return (m?.[1] || "").trim().replace(/[.,;:]+$/, "");
};

/** Rebuild place pins from API maps_places, result, events, or bold names. */
export const extractMapsPlaces = (
  result: string | null | undefined,
  events: ITaskEvent[] | undefined,
  prompt = "",
  serverPlaces?: IMapsPlace[] | null,
): IMapsPlace[] => {
  const places: IMapsPlace[] = [];

  for (const place of serverPlaces || []) {
    if (place?.name && place?.url) pushUnique(places, place);
  }

  for (const place of parsePlacesFromText(result || "")) {
    pushUnique(places, place);
  }

  for (const ev of events || []) {
    if (ev.event !== "tool_end") continue;
    const name = String(ev.data?.name || "");
    if (name && name !== "location") continue;
    const preview = String(ev.data?.result_preview || ev.data?.result || "");
    if (!preview) continue;
    for (const place of parsePlacesFromText(preview)) {
      pushUnique(places, place);
    }
  }

  if (places.length > 0) return places;

  const promptL = prompt.toLowerCase();
  const venueAsk = [
    "near",
    "restaurant",
    "cafe",
    "café",
    "hotel",
    "veg",
    "around",
  ].some((k) => promptL.includes(k));
  if (!venueAsk) return places;

  const area = areaFromPrompt(prompt);
  for (const match of (result || "").matchAll(BOLD_NAME_RE)) {
    let name = (match[1] || "").trim().replace(/:+$/, "");
    if (!name) continue;
    const low = name.toLowerCase();
    if (
      low === "google maps" ||
      low === "snapshot" ||
      low === "sources" ||
      name.includes(":") ||
      name.includes("/") ||
      name.split(/\s+/).length > 8
    ) {
      continue;
    }
    pushUnique(places, { name, url: googleMapsSearchUrl(name, area) });
  }

  return places;
};
