import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { api, type IBot } from "@/lib/api";
import { Button, Card, Field } from "@/components/ui";
import { cn } from "@/lib/utils";

const COLOR_DOT: Record<string, string> = {
  copper: "bg-[color:var(--palette-copper)]",
  blue: "bg-[color:var(--palette-blue)]",
  gold: "bg-[color:var(--palette-gold)]",
  verdigris: "bg-[color:var(--palette-verdigris)]",
  rose: "bg-[color:var(--palette-rose)]",
  info: "bg-[color:var(--palette-blue)]",
};

const NewGroupPage = () => {
  const navigate = useNavigate();
  const [bots, setBots] = useState<IBot[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [title, setTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api
      .listBots()
      .then(setBots)
      .catch(() => setBots([]));
  }, []);

  const toggle = (id: string) => {
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id);
      if (prev.length >= 6) return prev;
      return [...prev, id];
    });
  };

  const handleSubmit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (selected.length < 2 || busy) return;
    setBusy(true);
    setError(null);
    try {
      const chat = await api.createGroup(selected, title.trim() || undefined);
      void navigate(`/chats/${chat.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create group");
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight md:text-2xl">
          New group chat
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Add 2–6 bots for a shared outcome. Use @mentions to assign work.
        </p>
      </div>

      <Card className="p-5 md:p-6">
        <form className="space-y-4" onSubmit={(e) => void handleSubmit(e)}>
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">
              Title (optional)
            </span>
            <Field
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Website launch"
              maxLength={200}
            />
          </label>
          <fieldset>
            <legend className="text-xs font-medium text-muted-foreground">
              Members ({selected.length}/6)
            </legend>
            <ul className="mt-2 space-y-1">
              {bots.map((bot) => {
                const on = selected.includes(bot.id);
                return (
                  <li key={bot.id}>
                    <button
                      type="button"
                      onClick={() => toggle(bot.id)}
                      className={cn(
                        "flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left text-sm transition-colors",
                        on
                          ? "border-primary/40 bg-primary/10"
                          : "border-border hover:bg-accent",
                      )}
                      aria-pressed={on}
                    >
                      <span
                        className={cn(
                          "h-2.5 w-2.5 shrink-0 rounded-full",
                          COLOR_DOT[bot.color] ?? COLOR_DOT.copper,
                        )}
                      />
                      <span className="min-w-0 flex-1 truncate font-medium">
                        {bot.name}
                      </span>
                      {bot.label ? (
                        <span className="truncate text-xs text-muted-foreground">
                          {bot.label}
                        </span>
                      ) : null}
                    </button>
                  </li>
                );
              })}
            </ul>
          </fieldset>
          {error ? (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          ) : null}
          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <Button
              type="button"
              variant="secondary"
              onClick={() => void navigate(-1)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={busy || selected.length < 2}>
              {busy ? "Creating…" : "Create group"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
};

export default NewGroupPage;
