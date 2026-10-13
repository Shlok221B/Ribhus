import { useEffect, useState } from "react";
import { Link } from "react-router";
import { api, type ITask } from "@/lib/api";
import { Badge, Card, PageHeader, statusTone } from "@/components/ui";

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
    return <p className="text-sm text-muted-foreground">Loading tasks…</p>;
  }

  if (error) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {error}
      </p>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <PageHeader
        title="Tasks"
        description="Every run from the dashboard. Open one to see results and approvals."
      />

      {tasks.length === 0 ? (
        <Card className="p-8 text-sm text-muted-foreground">
          No tasks yet. Start one from{" "}
          <Link to="/" className="text-info underline-offset-4 hover:underline">
            Home
          </Link>
          .
        </Card>
      ) : (
        <ul className="space-y-3">
          {tasks.map((task) => (
            <li key={task.id}>
              <Link
                to={`/tasks/${task.id}`}
                className="block rounded-2xl border border-border/80 bg-card/80 p-4 transition-colors hover:border-ring/40 hover:bg-card md:p-5"
              >
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={statusTone(task.status)}>
                    {task.status.replaceAll("_", " ")}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {new Date(task.updated_at).toLocaleString()}
                  </span>
                </div>
                <p className="mt-2 line-clamp-2 text-sm leading-relaxed text-foreground md:text-base">
                  {task.prompt}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default TasksPage;
