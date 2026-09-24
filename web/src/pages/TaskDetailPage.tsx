import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { api, type ITask } from "@/lib/api";
import { cn } from "@/lib/utils";

const TaskDetailPage = () => {
  const { id } = useParams<{ id: string }>();
  const [task, setTask] = useState<ITask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editText, setEditText] = useState("");
  const [acting, setActing] = useState(false);

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
    return <p className="font-mono text-sm text-muted-foreground">Loading…</p>;
  }

  const pending = task.pending_approval;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <div>
        <Link
          to="/tasks"
          className="font-mono text-[11px] uppercase tracking-wider text-muted-foreground hover:text-info"
        >
          ← Tasks
        </Link>
        <h2 className="mt-2 text-lg text-foreground">{task.prompt}</h2>
        <p
          className={cn(
            "mt-1 font-mono text-xs uppercase",
            task.status === "completed" && "text-success",
            task.status === "failed" && "text-destructive",
            task.status === "awaiting_approval" && "text-warning",
            (task.status === "running" || task.status === "queued") &&
              "text-muted-foreground",
          )}
        >
          {task.status.replace("_", " ")}
        </p>
        {task.skills && task.skills.length > 0 ? (
          <p className="mt-1 text-xs text-muted-foreground">
            Skills: {task.skills.join(", ")}
          </p>
        ) : null}
      </div>

      {pending ? (
        <div className="rounded border border-warning/40 bg-card p-4">
          <p className="font-mono text-xs uppercase tracking-wider text-warning">
            Approval required
          </p>
          <p className="mt-2 text-sm">
            <span className="font-mono text-muted-foreground">{pending.tool}</span>
            <span className="mx-2 text-muted-foreground">·</span>
            <span className="text-warning">{pending.risk}</span>
          </p>
          <pre className="mt-3 max-h-48 overflow-auto rounded border border-border bg-background p-3 text-xs text-muted-foreground">
            {JSON.stringify(pending.arguments, null, 2)}
          </pre>
          {(pending.tool === "whatsapp_send" ||
            pending.tool === "email_send") && (
            <textarea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              rows={4}
              className="mt-3 w-full rounded border border-input bg-background px-3 py-2 text-sm"
              placeholder="Edit message body…"
            />
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={acting}
              onClick={() => void resolve("approve")}
              className="rounded bg-primary px-3 py-1.5 font-mono text-xs uppercase text-primary-foreground disabled:opacity-40"
            >
              Approve
            </button>
            <button
              type="button"
              disabled={acting}
              onClick={() => void resolve("edit")}
              className="rounded border border-border px-3 py-1.5 font-mono text-xs uppercase text-foreground disabled:opacity-40"
            >
              Edit &amp; approve
            </button>
            <button
              type="button"
              disabled={acting}
              onClick={() => void resolve("deny")}
              className="rounded border border-destructive/50 px-3 py-1.5 font-mono text-xs uppercase text-destructive disabled:opacity-40"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : null}

      {task.result ? (
        <section className="rounded border border-border bg-card p-4">
          <h3 className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
            Result
          </h3>
          <div className="mt-2 whitespace-pre-wrap text-sm leading-relaxed">
            {task.result}
          </div>
        </section>
      ) : null}

      {task.error ? (
        <p className="text-sm text-destructive" role="alert">
          {task.error}
        </p>
      ) : null}

      <section className="rounded border border-border bg-card p-4">
        <h3 className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          Events
        </h3>
        <ul className="mt-3 max-h-80 space-y-2 overflow-y-auto font-mono text-[11px] text-muted-foreground">
          {task.events.length === 0 ? (
            <li>— none yet —</li>
          ) : (
            task.events.map((ev, i) => (
              <li key={`${ev.ts}-${i}`} className="border-b border-border/40 pb-2">
                <span className="text-info">{ev.event}</span>{" "}
                <span className="opacity-60">
                  {new Date(ev.ts).toLocaleTimeString()}
                </span>
                {ev.data && Object.keys(ev.data).length > 0 ? (
                  <pre className="mt-1 overflow-x-auto whitespace-pre-wrap text-[10px] opacity-70">
                    {JSON.stringify(ev.data, null, 0).slice(0, 400)}
                  </pre>
                ) : null}
              </li>
            ))
          )}
        </ul>
      </section>
    </div>
  );
};

export default TaskDetailPage;
