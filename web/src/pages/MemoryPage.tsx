import { useEffect, useState, type FormEvent } from "react";
import { api, type IMemoryRecord } from "@/lib/api";

const MemoryPage = () => {
  const [rows, setRows] = useState<IMemoryRecord[]>([]);
  const [q, setQ] = useState("");
  const [content, setContent] = useState("");
  const [key, setKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = async (query?: string) => {
    try {
      setRows(await api.listMemory(query));
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load memory");
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const handleSearch = (event: FormEvent) => {
    event.preventDefault();
    void load(q.trim() || undefined);
  };

  const handleAdd = async (event: FormEvent) => {
    event.preventDefault();
    if (!content.trim() || busy) return;
    setBusy(true);
    try {
      await api.addMemory(content.trim(), key.trim() || undefined);
      setContent("");
      setKey("");
      await load(q.trim() || undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Add failed");
    } finally {
      setBusy(false);
    }
  };

  const handleForget = async (target: string) => {
    if (busy) return;
    setBusy(true);
    try {
      await api.forgetMemory(target);
      await load(q.trim() || undefined);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Forget failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <form onSubmit={handleSearch} className="flex flex-col gap-2 sm:flex-row">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search memories…"
          className="flex-1 rounded border border-input bg-card px-3 py-2 text-sm"
        />
        <button
          type="submit"
          className="rounded border border-border px-4 py-2 font-mono text-xs uppercase text-foreground"
        >
          Search
        </button>
      </form>

      <form
        onSubmit={(e) => void handleAdd(e)}
        className="space-y-2 rounded border border-border bg-card p-4"
      >
        <p className="font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          Add preference
        </p>
        <input
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="Key (optional, e.g. language)"
          className="w-full rounded border border-input bg-background px-3 py-2 text-sm"
        />
        <textarea
          value={content}
          onChange={(e) => setContent(e.target.value)}
          placeholder="Prefer Hinglish replies"
          rows={2}
          className="w-full rounded border border-input bg-background px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={busy || !content.trim()}
          className="rounded bg-primary px-3 py-1.5 font-mono text-xs uppercase text-primary-foreground disabled:opacity-40"
        >
          Save
        </button>
      </form>

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <ul className="space-y-2">
        {rows.length === 0 ? (
          <li className="text-sm text-muted-foreground">No memories yet.</li>
        ) : (
          rows.map((row) => (
            <li
              key={row.id}
              className="flex flex-col gap-2 rounded border border-border bg-card p-4 sm:flex-row sm:justify-between"
            >
              <div>
                <div className="font-mono text-[10px] uppercase text-muted-foreground">
                  {row.kind}
                  {row.key ? ` · ${row.key}` : ""}
                  {row.disabled ? " · disabled" : ""}
                </div>
                <p className="mt-1 text-sm">{row.content}</p>
              </div>
              <button
                type="button"
                disabled={busy}
                onClick={() => void handleForget(row.key || row.id)}
                className="shrink-0 self-start rounded border border-destructive/40 px-3 py-1.5 font-mono text-[10px] uppercase text-destructive"
              >
                Forget
              </button>
            </li>
          ))
        )}
      </ul>
    </div>
  );
};

export default MemoryPage;
