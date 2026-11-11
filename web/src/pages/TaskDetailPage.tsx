import { useCallback, useEffect, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useParams } from "react-router";
import { ArrowLeft, ArrowRight, ChevronDown } from "lucide-react";
import { api, type ITask, type ITaskTurn } from "@/lib/api";
import { extractMapsPlaces } from "@/lib/mapsPlaces";
import { ResearchMessageBody } from "@/components/JobResults";
import { MapsPlaces } from "@/components/MapsPlaces";
import { ResearchStatus } from "@/components/ResearchStatus";
import { Badge, Button, Card, TextArea, statusTone } from "@/components/ui";
import { researchProgressFromTask } from "@/lib/researchStatus";
import { cn } from "@/lib/utils";

const BUSY = new Set(["queued", "running", "awaiting_approval"]);

const threadTurns = (task: ITask): ITaskTurn[] => {
  const turns: ITaskTurn[] =
    task.turns && task.turns.length > 0
      ? task.turns.map((turn) => ({ role: turn.role, content: turn.content }))
      : [{ role: "user", content: task.prompt }];
  const running = BUSY.has(task.status);
  const result = task.result?.trim() ?? "";
  const already = turns.some(
    (turn) => turn.role === "assistant" && turn.content === result,
  );
  if (result && !already && !running) {
    turns.push({ role: "assistant", content: result });
  }
  return turns;
};

const TaskDetailPage = () => {
  const { id } = useParams<{ id: string }>();
  const [task, setTask] = useState<ITask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [acting, setActing] = useState(false);
  const [eventsOpen, setEventsOpen] = useState(false);
  const [followUp, setFollowUp] = useState("");
  const [sending, setSending] = useState(false);
  const [followError, setFollowError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const row = await api.getTask(id);
      setTask(row);
      setError(null);
      if (row.pending_approval) {
        const args = row.pending_approval.arguments;
        const draft =
          (typeof args.message === "string" && args.message) ||
          (typeof args.body === "string" && args.body) ||
          "";
        setEditText(draft);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load task");
    }
  }, [id]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 1500);
    return () => window.clearInterval(timer);
  }, [load]);

  const handleFollowUp = async (event?: FormEvent) => {
    event?.preventDefault();
    const text = followUp.trim();
    if (!id || !text || sending || (task && BUSY.has(task.status))) return;
    setSending(true);
    setFollowError(null);
    try {
      const updated = await api.followUp(id, text);
      setTask(updated);
      setFollowUp("");
    } catch (err) {
      setFollowError(err instanceof Error ? err.message : "Could not send follow-up");
    } finally {
      setSending(false);
    }
  };

  const handleFollowUpKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void handleFollowUp();
    }
  };

  const resolve = async (decision: "approve" | "deny" | "edit") => {
    if (!id || acting) return;
    setActing(true);
    try {
      const updated = await api.resolveApproval(id, {
        decision,
        edited_text: decision === "edit" ? editText : undefined,
      });
      setTask(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approval failed");
    } finally {
      setActing(false);
    }
  };

  if (error && !task) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {error}
      </p>
    );
  }

  if (!task) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  const pending = task.pending_approval;
  const busy = BUSY.has(task.status);
  const researchProgress = researchProgressFromTask(task);
  const turns = threadTurns(task).filter(
    (turn, index) => !(index === 0 && turn.role === "user"),
  );
  const mapsPlaces = extractMapsPlaces(
    task.result,
    task.events,
    task.prompt,
    task.maps_places,
  );

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <div>
        <Link
          to="/tasks"
          className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-info"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          Tasks
        </Link>
        <h2 className="mt-3 text-xl font-semibold leading-snug tracking-tight text-foreground md:text-2xl">
          {task.prompt}
        </h2>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Badge tone={statusTone(task.status)}>
            {researchProgress && researchProgress.phase !== "working"
              ? researchProgress.label
              : task.status.replaceAll("_", " ")}
          </Badge>
          {task.skills && task.skills.length > 0 ? (
            <span className="text-xs text-muted-foreground">
              Skills: {task.skills.join(", ")}
            </span>
          ) : null}
        </div>
      </div>

      {mapsPlaces.length > 0 ? (
        <Card className="p-4 md:p-5">
          <MapsPlaces places={mapsPlaces} />
        </Card>
      ) : null}

      {pending ? (
        <Card className="border-warning/35 p-5">
          <p className="text-xs font-medium uppercase tracking-wider text-warning">
            Approval required
          </p>
          <p className="mt-2 text-sm">
            <span className="text-muted-foreground">{pending.tool}</span>
            <span className="mx-2 text-muted-foreground">·</span>
            <span className="text-warning">{pending.risk}</span>
          </p>
          <pre className="mt-3 max-h-48 overflow-auto rounded-xl border border-border bg-background/70 p-3 text-xs text-muted-foreground">
            {JSON.stringify(pending.arguments, null, 2)}
          </pre>
          {(pending.tool === "whatsapp_send" ||
            pending.tool === "email_send") && (
            <TextArea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              rows={4}
              className="mt-3"
              placeholder="Edit message body…"
            />
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button disabled={acting} onClick={() => void resolve("approve")}>
              Approve
            </Button>
            <Button
              variant="secondary"
              disabled={acting}
              onClick={() => void resolve("edit")}
            >
              Edit &amp; approve
            </Button>
            <Button
              variant="danger"
              disabled={acting}
              onClick={() => void resolve("deny")}
            >
              Cancel
            </Button>
          </div>
        </Card>
      ) : null}

      {turns.map((turn, index) =>
        turn.role === "assistant" ? (
          <Card key={`turn-${index}`} className="p-5 md:p-6">
            <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              Result
            </h3>
            <ResearchMessageBody className="mt-4" markdown={turn.content} />
          </Card>
        ) : (
          <Card key={`turn-${index}`} className="p-5 md:p-6">
            <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
              You
            </h3>
            <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
              {turn.content}
            </p>
          </Card>
        ),
      )}

      {busy && !pending && researchProgress ? (
        <ResearchStatus progress={researchProgress} />
      ) : null}

      {task.error ? (
        <p className="text-sm text-destructive" role="alert">
          {task.error}
        </p>
      ) : null}

      <form
        onSubmit={(event) => void handleFollowUp(event)}
        className="space-y-3 rounded-2xl border border-border/70 bg-card/80 p-4 md:p-5"
      >
        <TextArea
          value={followUp}
          onChange={(event) => setFollowUp(event.target.value)}
          onKeyDown={handleFollowUpKeyDown}
          rows={3}
          placeholder={busy ? "Wait for this run to finish…" : "Ask a follow-up…"}
          disabled={busy || sending}
          aria-label="Follow-up message"
        />
        {followError ? (
          <p className="text-sm text-destructive" role="alert">
            {followError}
          </p>
        ) : null}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">⌘ / Ctrl + Enter to send</p>
          <Button
            type="submit"
            disabled={busy || sending || !followUp.trim()}
            className="w-full sm:w-auto"
          >
            {sending ? "Sending…" : "Send"}
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </form>

      <Card className="overflow-hidden">
        <button
          type="button"
          onClick={() => setEventsOpen((open) => !open)}
          className="flex w-full items-center justify-between gap-3 px-5 py-4 text-left transition-colors hover:bg-accent/40"
          aria-expanded={eventsOpen}
        >
          <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Events
            <span className="ml-2 normal-case tracking-normal text-muted-foreground/70">
              ({task.events.length})
            </span>
          </span>
          <ChevronDown
            className={cn(
              "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
              eventsOpen && "rotate-180",
            )}
            aria-hidden
          />
        </button>
        {eventsOpen ? (
          <ul className="max-h-80 space-y-2 overflow-y-auto border-t border-border/50 px-5 py-3 text-xs text-muted-foreground">
            {task.events.length === 0 ? (
              <li>None yet — the agent is working.</li>
            ) : (
              task.events.map((ev, i) => (
                <li
                  key={`${ev.ts}-${i}`}
                  className="border-b border-border/40 pb-2 last:border-0"
                >
                  <span className="text-info">{ev.event}</span>{" "}
                  <span className="opacity-60">
                    {new Date(ev.ts).toLocaleTimeString()}
                  </span>
                  {ev.data && Object.keys(ev.data).length > 0 ? (
                    <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-[11px] opacity-70">
                      {JSON.stringify(ev.data, null, 0).slice(0, 400)}
                    </pre>
                  ) : null}
                </li>
              ))
            )}
          </ul>
        ) : null}
      </Card>
    </div>
  );
};

export default TaskDetailPage;
