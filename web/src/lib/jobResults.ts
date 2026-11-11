export interface IJobVerification {
  job_page_accessible?: boolean;
  application_link_found?: boolean;
  application_page_accessible?: boolean;
  active_status_confirmed?: boolean;
}

export interface IJobOpening {
  company?: string | null;
  role?: string | null;
  location?: string | null;
  experience?: string | null;
  salary?: string | null;
  skills?: string[];
  job_url?: string | null;
  application_url?: string | null;
  date_posted?: string | null;
  status?: string;
  verification?: IJobVerification;
  host?: string;
  relevance_score?: number;
}

export interface IJobResultsPayload {
  type: "ribhus_jobs";
  objective?: string;
  ask?: {
    role?: string | null;
    location?: string | null;
    experience?: string | null;
  };
  summary?: {
    listings?: number;
    with_apply?: number;
    apply_accessible?: number;
    active_confirmed?: number;
    iterations?: number;
    urls_investigated?: number;
    incomplete?: boolean;
  };
  openings: IJobOpening[];
}

const FENCE_RE = /```ribhus-jobs\s*([\s\S]*?)```/i;

export const extractJobResults = (
  markdown: string | null | undefined,
): { payload: IJobResultsPayload | null; rest: string } => {
  if (!markdown) return { payload: null, rest: "" };
  const match = FENCE_RE.exec(markdown);
  if (!match) return { payload: null, rest: markdown };
  let payload: IJobResultsPayload | null = null;
  try {
    const parsed = JSON.parse(match[1] ?? "") as IJobResultsPayload;
    if (parsed?.type === "ribhus_jobs" && Array.isArray(parsed.openings)) {
      payload = parsed;
    }
  } catch {
    payload = null;
  }
  const rest = markdown.replace(FENCE_RE, "").trim();
  return { payload, rest };
};

export const faviconUrl = (host?: string | null): string | null => {
  if (!host) return null;
  const clean = host.replace(/^www\./, "");
  if (!clean) return null;
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(clean)}&sz=64`;
};

export const statusLabel = (opening: IJobOpening): { text: string; tone: "ok" | "warn" | "muted" } => {
  const v = opening.verification;
  if (opening.status === "active_confirmed" || v?.active_status_confirmed) {
    return { text: "Active confirmed", tone: "ok" };
  }
  if (
    opening.status === "application_accessible" ||
    v?.application_page_accessible
  ) {
    return { text: "Apply page OK", tone: "ok" };
  }
  if (opening.status === "application_url_found" || v?.application_link_found) {
    return { text: "Apply link found", tone: "warn" };
  }
  if (opening.status === "accessible" || v?.job_page_accessible) {
    return { text: "Listing opened", tone: "warn" };
  }
  if (opening.status === "closed") {
    return { text: "Closed", tone: "muted" };
  }
  return { text: opening.status?.replaceAll("_", " ") || "Unverified", tone: "muted" };
};
