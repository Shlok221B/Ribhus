import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { api } from "@/lib/api";
import { Button, Card, Field, TextArea } from "@/components/ui";
import { cn } from "@/lib/utils";

const COLORS = [
  { id: "copper", label: "Copper" },
  { id: "blue", label: "Blue" },
  { id: "gold", label: "Gold" },
  { id: "verdigris", label: "Verdigris" },
  { id: "rose", label: "Rose" },
  { id: "info", label: "Sky" },
] as const;

const COLOR_DOT: Record<string, string> = {
  copper: "bg-[color:var(--palette-copper)]",
  blue: "bg-[color:var(--palette-blue)]",
  gold: "bg-[color:var(--palette-gold)]",
  verdigris: "bg-[color:var(--palette-verdigris)]",
  rose: "bg-[color:var(--palette-rose)]",
  info: "bg-[color:var(--palette-blue)]",
};

const NewBotPage = () => {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [job, setJob] = useState("");
  const [label, setLabel] = useState("");
  const [color, setColor] = useState("copper");
  const [primary, setPrimary] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!name.trim() || busy) return;
    setBusy(true);
    setError(null);
    try {
      const bot = await api.createBot({
        name: name.trim(),
        job: job.trim(),
        label: label.trim(),
        color,
        make_primary: primary,
      });
      void navigate(`/bots/${bot.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create bot");
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto w-full max-w-xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold tracking-tight md:text-2xl">
          New bot
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Give it a clear job — ownership, sources, and approval boundaries.
        </p>
      </div>

      <Card className="p-5 md:p-6">
        <form className="space-y-4" onSubmit={(e) => void handleSubmit(e)}>
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">
              Name
            </span>
            <Field
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Researcher"
              required
              maxLength={80}
            />
          </label>
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">
              Label
            </span>
            <Field
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="Company research"
              maxLength={120}
            />
          </label>
          <label className="block space-y-1.5">
            <span className="text-xs font-medium text-muted-foreground">
              Job
            </span>
            <TextArea
              value={job}
              onChange={(e) => setJob(e.target.value)}
              rows={5}
              placeholder="Own Indian company research. Cite sources. Never email anyone without approval."
            />
          </label>
          <fieldset>
            <legend className="text-xs font-medium text-muted-foreground">
              Color
            </legend>
            <div className="mt-2 flex flex-wrap gap-2">
              {COLORS.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  onClick={() => setColor(c.id)}
                  className={cn(
                    "flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs transition-colors",
                    color === c.id
                      ? "border-primary bg-primary/10 text-foreground"
                      : "border-border text-muted-foreground hover:bg-accent",
                  )}
                  aria-pressed={color === c.id}
                >
                  <span
                    className={cn("h-2.5 w-2.5 rounded-full", COLOR_DOT[c.id])}
                  />
                  {c.label}
                </button>
              ))}
            </div>
          </fieldset>
          <label className="flex items-center gap-2 text-sm text-foreground">
            <input
              type="checkbox"
              checked={primary}
              onChange={(e) => setPrimary(e.target.checked)}
              className="rounded border-border"
            />
            Make primary bot
          </label>
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
            <Button type="submit" disabled={busy || !name.trim()}>
              {busy ? "Creating…" : "Create bot"}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
};

export default NewBotPage;
