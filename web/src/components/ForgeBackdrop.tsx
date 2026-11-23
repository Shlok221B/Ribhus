import { cn } from "@/lib/utils";

interface IForgeBackdropProps {
  /** Which Ribhus plate to use. */
  plate?: "craftsmen" | "line";
  /** Base image opacity (0–1). Chat stays quieter than Home. */
  opacity?: number;
  /** Extra vignette strength for busy surfaces. */
  dense?: boolean;
  className?: string;
}

const PLATE_SRC = {
  craftsmen: "/ribhus-2.png",
  line: "/ribhus-1.png",
} as const;

/**
 * Low-opacity Ribhus forge art + ember wash.
 * Pointer-events none; sits behind page content.
 */
export const ForgeBackdrop = ({
  plate = "craftsmen",
  opacity = 0.07,
  dense = false,
  className,
}: IForgeBackdropProps) => (
  <div
    className={cn(
      "pointer-events-none absolute inset-0 overflow-hidden",
      className,
    )}
    aria-hidden
  >
    <img
      src={PLATE_SRC[plate]}
      alt=""
      className="absolute inset-0 h-full w-full object-cover object-[center_30%]"
      style={{ opacity }}
      loading="lazy"
      decoding="async"
    />
    {/* Ember glow — copper/gold from the forge palette */}
    <div
      className={cn(
        "absolute inset-0 bg-[radial-gradient(ellipse_at_20%_0%,color-mix(in_srgb,var(--palette-copper)_22%,transparent),transparent_55%),radial-gradient(ellipse_at_90%_80%,color-mix(in_srgb,var(--palette-gold)_14%,transparent),transparent_50%)]",
        dense ? "opacity-90" : "opacity-70",
      )}
    />
    {/* Readability veil */}
    <div
      className={cn(
        "absolute inset-0 bg-gradient-to-b from-background/35 via-background/55 to-background/85",
        dense && "via-background/65 to-background/92",
      )}
    />
  </div>
);

export default ForgeBackdrop;
