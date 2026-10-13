import { useEffect, useState, type FormEvent } from "react";
import { api, type IMemoryRecord } from "@/lib/api";
import { Badge, Button, Card, Field, PageHeader, TextArea } from "@/components/ui";

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
      <PageHeader
        title="Memory"
        description="Preferences and facts Ribhus keeps across sessions."
      />

      <form onSubmit={handleSearch} className="flex flex-col gap-2 sm:flex-row">
        <Field
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search memories…"
          className="flex-1"
        />
        <Button type="submit" variant="secondary" className="w-full sm:w-auto">
          Search
        </Button>
      </form>

      <form onSubmit={(e) => void handleAdd(e)}>
        <Card className="space-y-3 p-5">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Add preference
          </p>
          <Field
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="Key (optional, e.g. language)"
          />
          <TextArea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Prefer Hinglish replies"
            rows={2}
          />
          <Button type="submit" disabled={busy || !content.trim()}>
            Save
          </Button>
        </Card>
      </form>

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <ul className="space-y-3">
        {rows.length === 0 ? (
          <li className="text-sm text-muted-foreground">No memories yet.</li>
        ) : (
          rows.map((row) => (
            <li key={row.id}>
              <Card className="flex flex-col gap-3 p-5 sm:flex-row sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap gap-2">
                    <Badge>{row.kind}</Badge>
                    {row.key ? <Badge tone="info">{row.key}</Badge> : null}
                    {row.disabled ? <Badge tone="warning">disabled</Badge> : null}
                  </div>
                  <p className="mt-2 text-sm leading-relaxed">{row.content}</p>
                </div>
                <Button
                  variant="danger"
                  disabled={busy}
                  onClick={() => void handleForget(row.key || row.id)}
                  className="shrink-0 self-start"
                >
                  Forget
                </Button>
              </Card>
            </li>
          ))
        )}
      </ul>
    </div>
  );
};

export default MemoryPage;
