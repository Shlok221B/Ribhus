import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { ArrowLeft, ChevronDown } from "lucide-react";
import { api, type ITask } from "@/lib/api";
import { extractMapsPlaces } from "@/lib/mapsPlaces";
import { MarkdownBody } from "@/components/Markdown";
import { MapsPlaces } from "@/components/MapsPlaces";
import { Badge, Button, Card, TextArea, statusTone } from "@/components/ui";
import { cn } from "@/lib/utils";

const TaskDetailPage = () => {
  const { id } = useParams<{ id: string }>();
  const [task, setTask] = useState<ITask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [acting, setActing] = useState(false);
  const [eventsOpen, setEventsOpen] = useState(false);

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
            {task.status.replaceAll("_", " ")}
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

      {task.result ? (
        <Card className="p-5 md:p-6">
          <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Result
          </h3>
          <MarkdownBody className="mt-4">{task.result}</MarkdownBody>
        </Card>
      ) : null}

      {task.error ? (
        <p className="text-sm text-destructive" role="alert">
          {task.error}
        </p>
      ) : null}

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
