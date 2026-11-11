import { Building2, ExternalLink, MapPin, Briefcase } from "lucide-react";
import {
  extractJobResults,
  faviconUrl,
  statusLabel,
  type IJobOpening,
  type IJobResultsPayload,
} from "@/lib/jobResults";
import { MarkdownBody } from "@/components/Markdown";
import { cn } from "@/lib/utils";

interface IJobResultsProps {
  markdown: string;
  className?: string;
}

const LinkPreview = ({
  href,
  label,
  variant = "secondary",
}: {
  href: string;
  label: string;
  variant?: "primary" | "secondary";
}) => {
  let host = "";
  try {
    host = new URL(href).hostname.replace(/^www\./, "");
  } catch {
    host = href;
  }
  const icon = faviconUrl(host);
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={cn(
        "group flex min-w-0 flex-1 items-center gap-2.5 rounded-xl border px-3 py-2 transition-colors",
        variant === "primary"
          ? "border-primary/40 bg-primary/10 hover:bg-primary/20"
          : "border-border/70 bg-background/60 hover:bg-accent/60",
      )}
    >
      {icon ? (
        <img
          src={icon}
          alt=""
          width={18}
          height={18}
          className="h-[18px] w-[18px] shrink-0 rounded-sm"
          loading="lazy"
        />
      ) : (
        <ExternalLink className="h-4 w-4 shrink-0 text-muted-foreground" />
      )}
      <span className="min-w-0 flex-1">
        <span
          className={cn(
            "block truncate text-xs font-semibold",
            variant === "primary" ? "text-primary" : "text-foreground",
          )}
        >
          {label}
        </span>
        <span className="block truncate text-[11px] text-muted-foreground">
          {host}
        </span>
      </span>
      <ExternalLink
        className="h-3.5 w-3.5 shrink-0 text-muted-foreground opacity-70 group-hover:opacity-100"
        aria-hidden
      />
    </a>
  );
};

const OpeningCard = ({ opening, index }: { opening: IJobOpening; index: number }) => {
  const status = statusLabel(opening);
  const apply = opening.application_url || opening.job_url;
  const listing =
    opening.job_url && opening.job_url !== opening.application_url
      ? opening.job_url
      : null;
  const company = opening.company?.trim() || "Company unknown";
  const role = opening.role?.trim() || "Role unknown";
  const host = opening.host || (() => {
    try {
      return apply ? new URL(apply).hostname.replace(/^www\./, "") : "";
    } catch {
      return "";
    }
  })();
  const icon = faviconUrl(host);

  return (
    <article className="animate-fade-in rounded-2xl border border-border/70 bg-background/50 p-3.5 sm:p-4">
      <div className="flex items-start gap-3">
        <span className="flex h-10 w-10 shrink-0 items-center justify-center overflow-hidden rounded-xl border border-border bg-card">
          {icon ? (
            <img src={icon} alt="" className="h-6 w-6" loading="lazy" />
          ) : (
            <Building2 className="h-5 w-5 text-muted-foreground" />
          )}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                #{index + 1} · {company}
              </p>
              <h3 className="mt-0.5 text-sm font-semibold leading-snug text-foreground sm:text-[15px]">
                {role}
              </h3>
            </div>
            <span
              className={cn(
                "shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
                status.tone === "ok" && "bg-emerald-500/15 text-emerald-400",
                status.tone === "warn" && "bg-amber-500/15 text-amber-400",
                status.tone === "muted" && "bg-muted text-muted-foreground",
              )}
            >
              {status.text}
            </span>
          </div>

          <ul className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {opening.location ? (
              <li className="inline-flex items-center gap-1">
                <MapPin className="h-3 w-3" aria-hidden />
                {opening.location}
              </li>
            ) : null}
            {opening.experience ? (
              <li className="inline-flex items-center gap-1">
                <Briefcase className="h-3 w-3" aria-hidden />
                {opening.experience}
              </li>
            ) : null}
            {opening.date_posted ? <li>Posted {opening.date_posted}</li> : null}
          </ul>

          {opening.skills && opening.skills.length > 0 ? (
            <ul className="mt-2 flex flex-wrap gap-1.5">
              {opening.skills.slice(0, 6).map((skill) => (
                <li
                  key={skill}
                  className="rounded-md bg-card px-1.5 py-0.5 text-[11px] text-foreground/80"
                >
                  {skill}
                </li>
              ))}
            </ul>
          ) : null}

          {opening.salary ? (
            <p className="mt-2 text-xs text-foreground/80">{opening.salary}</p>
          ) : null}

          <div className="mt-3 flex flex-col gap-2 sm:flex-row">
            {apply ? (
              <LinkPreview href={apply} label="Apply" variant="primary" />
            ) : null}
            {listing ? (
              <LinkPreview href={listing} label="Listing" variant="secondary" />
            ) : null}
          </div>
        </div>
      </div>
    </article>
  );
};

const JobResultsBoard = ({ payload }: { payload: IJobResultsPayload }) => {
  const summary = payload.summary;
  const ask = payload.ask;

  return (
    <div className="space-y-4">
      <header className="rounded-2xl border border-border/70 bg-gradient-to-br from-primary/10 via-card to-card p-4">
        <p className="text-[11px] font-semibold uppercase tracking-[0.14em] text-primary">
          Deep research · Jobs
        </p>
        <h2 className="mt-1 text-lg font-semibold tracking-tight text-foreground">
          {ask?.role || "Job openings"}
          {ask?.location ? (
            <span className="font-normal text-muted-foreground">
              {" "}
              · {ask.location}
            </span>
          ) : null}
        </h2>
        {ask?.experience ? (
          <p className="mt-1 text-sm text-muted-foreground">
            Experience: {ask.experience}
          </p>
        ) : null}
        {summary ? (
          <dl className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            <div className="rounded-xl bg-background/50 px-2.5 py-2">
              <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Listings
              </dt>
              <dd className="text-sm font-semibold">{summary.listings ?? 0}</dd>
            </div>
            <div className="rounded-xl bg-background/50 px-2.5 py-2">
              <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Apply links
              </dt>
              <dd className="text-sm font-semibold">{summary.with_apply ?? 0}</dd>
            </div>
            <div className="rounded-xl bg-background/50 px-2.5 py-2">
              <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Apply pages OK
              </dt>
              <dd className="text-sm font-semibold">
                {summary.apply_accessible ?? 0}
              </dd>
            </div>
            <div className="rounded-xl bg-background/50 px-2.5 py-2">
              <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Pages checked
              </dt>
              <dd className="text-sm font-semibold">
                {summary.urls_investigated ?? 0}
              </dd>
            </div>
            <div className="rounded-xl bg-background/50 px-2.5 py-2">
              <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Iterations
              </dt>
              <dd className="text-sm font-semibold">
                {summary.iterations ?? 0}
              </dd>
            </div>
            <div className="rounded-xl bg-background/50 px-2.5 py-2">
              <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">
                Score
              </dt>
              <dd className="text-sm font-semibold">
                {summary.completion_score != null
                  ? `${summary.completion_score}`
                  : "—"}
              </dd>
            </div>
          </dl>
        ) : null}
        {summary?.stop_reason || summary?.quality_met != null ? (
          <p className="mt-2 text-xs text-muted-foreground">
            {summary.quality_met
              ? "Quality bar met"
              : "Quality bar not fully met"}
            {summary.stop_reason ? ` · stopped: ${summary.stop_reason}` : ""}
            {summary.execution_time_seconds != null
              ? ` · ${summary.execution_time_seconds.toFixed(1)}s`
              : ""}
            {summary.duplicate_rate != null
              ? ` · dup ${(summary.duplicate_rate * 100).toFixed(0)}%`
              : ""}
          </p>
        ) : null}
        {summary?.incomplete ? (
          <p className="mt-2 text-xs text-amber-400">
            Research ended before full completion — treat unverified rows carefully.
          </p>
        ) : null}
      </header>

      <div className="space-y-3">
        {payload.openings.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No verified openings survived filtering.
          </p>
        ) : (
          payload.openings.map((opening, index) => (
            <OpeningCard
              key={`${opening.application_url || opening.job_url || opening.role}-${index}`}
              opening={opening}
              index={index}
            />
          ))
        )}
      </div>
    </div>
  );
};

/** Renders structured job research when present; otherwise normal markdown. */
export const ResearchMessageBody = ({
  markdown,
  className,
}: IJobResultsProps) => {
  const { payload, rest } = extractJobResults(markdown);
  if (!payload) {
    return <MarkdownBody className={className}>{markdown}</MarkdownBody>;
  }
  // Prefer the card board; keep gaps/next from markdown if useful
  const gapsMatch = rest.match(/## Gaps[\s\S]*?(?=## Next|$)/i);
  const nextMatch = rest.match(/## Next[\s\S]*$/i);
  const extra = [gapsMatch?.[0], nextMatch?.[0]].filter(Boolean).join("\n\n");

  return (
    <div className={cn("space-y-4", className)}>
      <JobResultsBoard payload={payload} />
      {extra ? <MarkdownBody>{extra}</MarkdownBody> : null}
    </div>
  );
};
