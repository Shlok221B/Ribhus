import { Search } from "lucide-react";
import type { IResearchProgress } from "@/lib/researchStatus";
import { TypingDots } from "@/components/ui";
import { cn } from "@/lib/utils";

interface IResearchStatusProps {
  progress: IResearchProgress;
  /** Live one-line pulse (includes elapsed). */
  line?: string | null;
  /** Elapsed clock e.g. `1m 49s`. */
  elapsed?: string | null;
  className?: string;
}

const STEPS = [
  { id: "plan", label: "Plan" },
  { id: "search", label: "Search" },
  { id: "inspect", label: "Inspect" },
  { id: "evaluate", label: "Evaluate" },
  { id: "synthesize", label: "Write" },
] as const;

const stepIndex = (phase: string): number => {
  if (phase === "plan") return 0;
  if (phase.includes("search") || phase === "iterate") return 1;
  if (phase.includes("inspect")) return 2;
  if (phase === "evaluate") return 3;
  if (phase === "synthesize" || phase === "budget") return 4;
  if (phase === "queued") return -1;
  return 1;
};

export const ResearchStatus = ({
  progress,
  line,
  elapsed,
  className,
}: IResearchStatusProps) => {
  const active = Math.max(0, stepIndex(progress.phase));
  const showSteps = Boolean(progress.researchLike);
  const headline = line?.trim() || progress.label;

  return (
    <div
      className={cn(
        "animate-bubble-bot w-full max-w-md self-start rounded-[1.4rem] rounded-bl-lg border border-border/60 bg-card px-4 py-3",
        className,
      )}
      role="status"
      aria-live="polite"
    >
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/15 text-primary">
          <Search className="h-4 w-4" aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <TypingDots />
            {elapsed ? (
              <span className="rounded-md bg-background/80 px-1.5 py-0.5 font-mono text-[11px] tabular-nums text-muted-foreground">
                {elapsed}
              </span>
            ) : null}
          </div>
          <p
            key={headline}
            className="mt-1.5 animate-fade-in text-sm font-medium leading-snug text-shimmer"
          >
            {headline}
          </p>
          {!line && progress.detail ? (
            <p className="mt-1 truncate text-xs text-muted-foreground">
              {progress.detail}
            </p>
          ) : null}
          {showSteps ? (
            <ol
              className="mt-3 flex flex-wrap gap-1.5"
              aria-label="Research stages"
            >
              {STEPS.map((step, index) => {
                const done = index < active;
                const current = index === active;
                return (
                  <li
                    key={step.id}
                    className={cn(
                      "rounded-full px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide",
                      done && "bg-primary/20 text-primary",
                      current && "bg-primary text-primary-foreground",
                      !done &&
                        !current &&
                        "bg-background/70 text-muted-foreground",
                    )}
                  >
                    {step.label}
                  </li>
                );
              })}
            </ol>
          ) : null}
        </div>
      </div>
    </div>
  );
};
