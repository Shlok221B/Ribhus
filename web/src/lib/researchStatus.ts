import { useEffect, useMemo, useState } from "react";
import type { ITask, ITaskEvent } from "@/lib/api";

export interface IResearchProgress {
  active: boolean;
  phase: string;
  label: string;
  detail?: string;
  iteration?: number;
  score?: number;
  /** ISO timestamp when this run segment started. */
  startedAt?: string;
  /** True when this looks like deep-research (show stage chips). */
  researchLike?: boolean;
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
  whatsapp_send: "Preparing WhatsApp send",
  whatsapp_reply: "Reading WhatsApp chat",
  email_send: "Preparing email",
  clarify: "Asking a quick question",
  shell: "Running a shell command",
  python: "Running Python",
  read_file: "Reading a file",
  write_file: "Writing a file",
  edit_file: "Editing a file",
  todo: "Updating checklist",
  message_bot: "Handing off to another bot",
  location: "Checking location",
  maps: "Looking up maps places",
};

const HEARTBEATS = [
  "Still working — not stuck",
  "Model is thinking…",
  "Next tool step coming up…",
  "Run is active — hang tight",
  "Gathering more context…",
] as const;

const BUSY = new Set(["queued", "running", "awaiting_approval"]);

const eventType = (ev: ITaskEvent): string =>
  String(ev.event_type || ev.event || "");

const eventData = (ev: ITaskEvent): Record<string, unknown> => {
  if (ev.payload && typeof ev.payload === "object") return ev.payload;
  if (ev.data && typeof ev.data === "object") return ev.data;
  return {};
};

const toolFromData = (data: Record<string, unknown>): string =>
  String(data.tool || data.name || "").trim();

const argSnippet = (data: Record<string, unknown>): string | undefined => {
  const args = data.arguments;
  if (!args || typeof args !== "object") return undefined;
  const row = args as Record<string, unknown>;
  for (const key of ["query", "url", "path", "to", "contact", "message", "prompt"]) {
    const value = row[key];
    if (typeof value === "string" && value.trim()) {
      const text = value.trim().replace(/\s+/g, " ");
      return text.length > 56 ? `${text.slice(0, 55)}…` : text;
    }
  }
  return undefined;
};

const humanToolLabel = (tool: string): string => {
  if (!tool) return "Running a tool";
  if (TOOL_LABELS[tool]) return TOOL_LABELS[tool];
  if (tool.includes("__")) {
    const short = tool.split("__").pop() || tool;
    return `MCP · ${short.replaceAll("_", " ")}`;
  }
  return `Running ${tool.replaceAll("_", " ")}`;
};

/** Format milliseconds as `12s`, `1m 49s`, or `1h 2m 3s`. */
export const formatElapsed = (ms: number): string => {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
};

export const parseIsoMs = (iso: string | null | undefined): number | null => {
  if (!iso) return null;
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? ms : null;
};

/** Start of the current (or last) run: latest turn.started, else created_at. */
export const runStartedAt = (task: ITask): string => {
  const events = task.events || [];
  for (let i = events.length - 1; i >= 0; i -= 1) {
    if (eventType(events[i]!) === "turn.started") {
      return events[i]!.ts || task.created_at;
    }
  }
  return task.created_at;
};

/** End timestamp when finished; null while busy. */
export const runEndedAt = (task: ITask): string | null => {
  if (BUSY.has(task.status)) return null;
  const events = task.events || [];
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const type = eventType(events[i]!);
    if (
      type === "turn.completed" ||
      type === "turn.failed" ||
      type === "turn.cancelled"
    ) {
      return events[i]!.ts || task.updated_at;
    }
  }
  return task.updated_at;
};

export const elapsedMsForTask = (
  task: ITask,
  nowMs: number = Date.now(),
): number => {
  const start = parseIsoMs(runStartedAt(task)) ?? nowMs;
  const endIso = runEndedAt(task);
  const end = endIso ? (parseIsoMs(endIso) ?? nowMs) : nowMs;
  return Math.max(0, end - start);
};

/** Derive a human status from the latest task events. */
export const researchProgressFromTask = (
  task: ITask | null | undefined,
): IResearchProgress | null => {
  if (!task) return null;
  const busy = BUSY.has(task.status);
  const startedAt = runStartedAt(task);

  if (!busy) return null;

  if (task.status === "queued") {
    return {
      active: true,
      phase: "queued",
      label: "Queued…",
      startedAt,
    };
  }
  if (task.status === "awaiting_approval") {
    const tool = task.pending_approval?.tool;
    return {
      active: true,
      phase: "approval",
      label: tool ? `Waiting for approval · ${tool}` : "Waiting for approval",
      detail: tool === "clarify" ? "Answer the quick question to continue" : undefined,
      startedAt,
    };
  }

  const events = [...(task.events || [])];
  for (let i = events.length - 1; i >= 0; i -= 1) {
    const ev = events[i]!;
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
        } else if (typeof data.summary === "string" && data.summary.trim()) {
          detail = data.summary.trim().slice(0, 80);
        } else if (typeof data.display === "string" && data.display.trim()) {
          detail = data.display.trim().slice(0, 80);
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
          startedAt,
          researchLike: true,
        };
      }

      const iteration =
        typeof data.iteration === "number" ? data.iteration : undefined;
      if (typeof data.summary === "string" && data.summary.trim()) {
        return {
          active: true,
          phase: "plan",
          label: "Planning next steps",
          detail: data.summary.trim().slice(0, 80),
          iteration,
          startedAt,
        };
      }
      if (typeof data.display === "string" && data.display.trim()) {
        return {
          active: true,
          phase: "plan",
          label: "Planning next steps",
          detail: data.display.trim().slice(0, 80),
          iteration,
          startedAt,
        };
      }
      return {
        active: true,
        phase: "thinking",
        label:
          iteration != null ? `Thinking · step ${iteration}` : "Thinking…",
        startedAt,
      };
    }

    if (type === "tool.started" || type === "tool_start") {
      const tool = toolFromData(data);
      const label = humanToolLabel(tool);
      let detail = argSnippet(data);
      if (!detail && Array.isArray(data.queries) && data.queries.length > 0) {
        detail = String(data.queries[0]);
      } else if (!detail && typeof data.urls === "number") {
        detail = `${data.urls} pages`;
      } else if (!detail && typeof data.iteration === "number") {
        detail = `Pass ${data.iteration}`;
      }
      return {
        active: true,
        phase: tool || "tool",
        label,
        detail,
        iteration:
          typeof data.iteration === "number" ? data.iteration : undefined,
        startedAt,
        researchLike: tool.startsWith("research_") || Boolean(data.research),
      };
    }

    if (type === "tool.finished" || type === "tool_end") {
      const tool = toolFromData(data);
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
        return {
          active: true,
          phase: tool,
          label,
          detail,
          startedAt,
          researchLike: true,
        };
      }
      if (tool) {
        const ok = data.ok !== false;
        return {
          active: true,
          phase: tool,
          label: ok
            ? `${humanToolLabel(tool)} · done`
            : `${humanToolLabel(tool)} · retrying`,
          detail: argSnippet(data),
          startedAt,
          researchLike: false,
        };
      }
    }

    if (type === "turn.started") {
      const bot = String(data.bot_name || "").trim();
      return {
        active: true,
        phase: "working",
        label: bot ? `${bot} started` : "Run started",
        startedAt,
      };
    }
  }

  if (
    task.skills?.includes("job-search") ||
    task.skills?.includes("company-research")
  ) {
    return {
      active: true,
      phase: "research",
      label: "Deep research in progress",
      detail: task.skills.join(", "),
      startedAt,
      researchLike: true,
    };
  }

  return {
    active: true,
    phase: "working",
    label: "Working…",
    startedAt,
  };
};

export const pulseStatusLine = (
  progress: IResearchProgress,
  pulseTick: number,
  elapsed: string,
): string => {
  const base = progress.detail
    ? `${progress.label} — ${progress.detail}`
    : progress.label;
  // Even ticks: event-based line; odd ticks: heartbeat so the line visibly refreshes.
  if (pulseTick % 2 === 0) {
    return `${base} · ${elapsed}`;
  }
  const beat = HEARTBEATS[pulseTick % HEARTBEATS.length] ?? HEARTBEATS[0];
  return `${beat} · ${elapsed}`;
};

export interface IRunActivity {
  busy: boolean;
  elapsed: string;
  elapsedMs: number;
  progress: IResearchProgress | null;
  line: string | null;
}

/** Live elapsed + 5s-refreshing one-line status while a task is busy. */
export const useRunActivity = (task: ITask | null | undefined): IRunActivity => {
  const busy = Boolean(task && BUSY.has(task.status));
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [pulseTick, setPulseTick] = useState(0);

  useEffect(() => {
    if (!task) return;
    // Tick every second while busy; one catch-up when finished so elapsed freezes correctly.
    if (!busy) {
      setNowMs(Date.now());
      return;
    }
    setNowMs(Date.now());
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [task?.id, busy, task?.status, task?.updated_at]);

  useEffect(() => {
    if (!busy) {
      setPulseTick(0);
      return;
    }
    setPulseTick(0);
    const timer = window.setInterval(() => {
      setPulseTick((n) => n + 1);
    }, 5000);
    return () => window.clearInterval(timer);
  }, [busy, task?.id]);

  const progress = useMemo(
    () => researchProgressFromTask(task),
    // Recompute when events / status change (pulseTick only affects line).
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional deps
    [task?.id, task?.status, task?.events, task?.pending_approval, task?.skills],
  );

  const elapsedMs = task ? elapsedMsForTask(task, nowMs) : 0;
  const elapsed = formatElapsed(elapsedMs);

  const line =
    busy && progress ? pulseStatusLine(progress, pulseTick, elapsed) : null;

  return { busy, elapsed, elapsedMs, progress, line };
};
