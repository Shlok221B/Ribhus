import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, type ITask } from "@/lib/api";
import { cn } from "@/lib/utils";

const statusClass = (status: ITask["status"]) => {
  switch (status) {
    case "completed":
      return "text-success";
    case "failed":
    case "cancelled":
      return "text-destructive";
    case "awaiting_approval":
      return "text-warning";
    default:
      return "text-muted-foreground";
  }
};

const TasksPage = () => {
  const [tasks, setTasks] = useState<ITask[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const rows = await api.listTasks();
        if (!cancelled) {
          setTasks(rows);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load tasks");
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 4000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  if (loading) {
    return <p className="font-mono text-sm text-muted-foreground">Loading tasks…</p>;
  }

  if (error) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {error}
      </p>
    );
  }

  if (tasks.length === 0) {
    return (
      <div className="rounded border border-border bg-card p-6 text-sm text-muted-foreground">
        No tasks yet. Start one from{" "}
        <Link to="/" className="text-info underline">
          Home
        </Link>
        .
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded border border-border">
      <table className="w-full min-w-[640px] text-left text-sm">
        <thead className="border-b border-border bg-card font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          <tr>
            <th className="px-4 py-3 font-medium">Status</th>
            <th className="px-4 py-3 font-medium">Prompt</th>
            <th className="px-4 py-3 font-medium">Updated</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <tr
              key={task.id}
              className="border-b border-border/60 hover:bg-accent/60"
            >
              <td className="px-4 py-3 align-top">
                <span
                  className={cn(
                    "font-mono text-[11px] uppercase",
                    statusClass(task.status),
                  )}
                >
                  {task.status.replace("_", " ")}
                </span>
              </td>
              <td className="px-4 py-3">
                <Link
                  to={`/tasks/${task.id}`}
                  className="line-clamp-2 text-foreground hover:text-info"
                >
                  {task.prompt}
                </Link>
              </td>
              <td className="px-4 py-3 align-top font-mono text-[11px] text-muted-foreground">
                {new Date(task.updated_at).toLocaleString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default TasksPage;
