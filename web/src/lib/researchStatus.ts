import type { ITask, ITaskEvent } from "@/lib/api";

export interface IResearchProgress {
  active: boolean;
  phase: string;
  label: string;
  detail?: string;
  iteration?: number;
  score?: number;
}

const PHASE_LABELS: Record<string, string> = {
  plan: "Planning research",
  iterate: "Running research pass",
  evaluate: "Evaluating findings",
  synthesize: "Writing results",
  budget: "Wrapping up (budget)",
};

const TOOL_LABELS: Record<string, string> = {
  research_search: "Searching the web",
  research_inspect: "Opening listing pages",
  research_extract: "Extracting structured data",
  research_verify: "Verifying listings",
  web_search: "Searching the web",
  web_extract: "Reading pages",
  browser: "Browsing pages",
};

const eventType = (ev: ITaskEvent): string =>
  String(ev.event_type || ev.event || "");

const eventData = (ev: ITaskEvent): Record<string, unknown> => {
  if (ev.payload && typeof ev.payload === "object") return ev.payload;
  if (ev.data && typeof ev.data === "object") return ev.data;
  return {};
};

/** Derive a human research status from the latest task events. */
export const researchProgressFromTask = (
  task: ITask | null | undefined,
): IResearchProgress | null => {
  if (!task) return null;
  const busy = ["queued", "running", "awaiting_approval"].includes(task.status);
  if (!busy) return null;

  if (task.status === "queued") {
    return { active: true, phase: "queued", label: "Queued…" };
  }
  if (task.status === "awaiting_approval") {
    return {
      active: true,
      phase: "approval",
      label: "Waiting for approval",
    };
  }

  const events = [...(task.events || [])];
  // Prefer newest research-related events
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const ev = events[i];
    const type = eventType(ev);
    const data = eventData(ev);

    if (type === "thinking" || type === "plan") {
      const phase = String(data.phase || (type === "plan" ? "plan" : ""));
      if (data.research || phase) {
        const iteration =
          typeof data.iteration === "number" ? data.iteration : undefined;
        const score =
          typeof data.score === "number" ? data.score : undefined;
        const missing = Array.isArray(data.missing)
          ? data.missing.filter((m): m is string => typeof m === "string")
          : [];
        const strategies = Array.isArray(data.strategies)
          ? data.strategies.filter((m): m is string => typeof m === "string")
          : [];
        let detail: string | undefined;
        if (phase === "evaluate" && missing.length > 0) {
          detail = `Missing: ${missing.slice(0, 2).join("; ")}`;
        } else if (phase === "plan" && strategies.length > 0) {
          detail = strategies[0];
        } else if (typeof data.leads === "number") {
          detail = `${data.leads} leads`;
        } else if (typeof data.urls === "number") {
          detail = `${data.urls} URLs`;
        } else if (typeof data.pages === "number") {
          detail = `${data.pages} pages`;
        }
        const base =
          PHASE_LABELS[phase] ||
          (data.research ? "Deep research" : "Working");
        const label =
          iteration != null && phase === "iterate"
            ? `${base} · pass ${iteration}`
            : iteration != null && phase === "evaluate"
              ? `${base} · pass ${iteration}${score != null ? ` (${score}%)` : ""}`
              : base;
        return {
          active: true,
          phase: phase || "research",
          label,
          detail,
          iteration,
          score,
        };
      }
    }

    if (type === "tool.started" || type === "tool_start") {
      const tool = String(data.tool || "");
      if (tool.startsWith("research_") || data.research) {
        const label = TOOL_LABELS[tool] || `Running ${tool}`;
        let detail: string | undefined;
        if (Array.isArray(data.queries) && data.queries.length > 0) {
          detail = String(data.queries[0]);
        } else if (typeof data.urls === "number") {
          detail = `${data.urls} pages`;
        } else if (typeof data.iteration === "number") {
          detail = `Pass ${data.iteration}`;
        }
        return {
          active: true,
          phase: tool || "tool",
          label,
          detail,
          iteration:
            typeof data.iteration === "number" ? data.iteration : undefined,
        };
      }
    }

    if (type === "tool.finished" || type === "tool_end") {
      const tool = String(data.tool || "");
      if (tool.startsWith("research_")) {
        const label =
          tool === "research_search"
            ? "Search pass complete"
            : tool === "research_inspect"
              ? "Page inspection complete"
              : "Step complete";
        let detail: string | undefined;
        if (typeof data.leads === "number") detail = `${data.leads} new leads`;
        if (typeof data.pages === "number") detail = `${data.pages} pages read`;
        if (typeof data.records === "number") detail = `${data.records} records`;
        const levels =
          data.levels && typeof data.levels === "object"
            ? (data.levels as Record<string, unknown>)
            : null;
        if (levels) {
          const l1 = Number(levels.l1 || 0);
          const l2 = Number(levels.l2 || 0);
          const l3 = Number(levels.l3 || 0);
          detail = `L1 ${l1} · L2 ${l2} · L3 ${l3}`;
        }
        const verification =
          data.verification && typeof data.verification === "object"
            ? (data.verification as Record<string, unknown>)
            : null;
        if (verification) {
          detail = `active ${Number(verification.active_confirmed || 0)} · apply ${Number(verification.apply_page || 0)}`;
        }
        return { active: true, phase: tool, label, detail };
      }
    }
  }

  // Skills hint
  if (task.skills?.includes("job-search") || task.skills?.includes("company-research")) {
    return {
      active: true,
      phase: "research",
      label: "Deep research in progress",
      detail: task.skills.join(", "),
    };
  }

  return { active: true, phase: "working", label: "Working…" };
};
