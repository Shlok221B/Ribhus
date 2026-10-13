import { ExternalLink, MapPin } from "lucide-react";
import type { IMapsPlace } from "@/lib/mapsPlaces";

interface IMapsPlacesProps {
  places: IMapsPlace[];
}

export const MapsPlaces = ({ places }: IMapsPlacesProps) => {
  if (!places?.length) return null;

  return (
    <section
      className="rounded-xl border border-primary/40 bg-primary/10 p-4"
      data-testid="maps-places"
    >
      <h4 className="flex items-center gap-2 text-sm font-semibold text-primary">
        <MapPin className="h-4 w-4" aria-hidden />
        Open on Google Maps
      </h4>
      <p className="mt-1 text-xs text-muted-foreground">
        Place links (not directions)
      </p>
      <ul className="mt-3 flex flex-col gap-2.5">
        {places.map((place) => (
          <li
            key={`${place.name}-${place.url}`}
            className="flex flex-col gap-2 rounded-lg border border-border/60 bg-card/80 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between"
          >
            <span className="text-sm font-medium text-foreground">
              {place.name}
            </span>
            <a
              href={place.url}
              target="_blank"
              rel="noreferrer"
              aria-label={`Open ${place.name} in Google Maps`}
              className="inline-flex w-fit items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground transition-opacity hover:opacity-90"
            >
              <MapPin className="h-3.5 w-3.5 shrink-0" aria-hidden />
              Google Maps
              <ExternalLink className="h-3 w-3 shrink-0 opacity-80" aria-hidden />
            </a>
          </li>
        ))}
      </ul>
    </section>
  );
};
