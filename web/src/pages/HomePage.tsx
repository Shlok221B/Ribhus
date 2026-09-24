import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { ArrowRight } from "lucide-react";
import { api } from "@/lib/api";

const EXAMPLES = [
  "Research this Indian company: Zoho",
  "Find me a hotel in Goa under ₹8,000 for Friday and Saturday.",
  "What's happening with my football team?",
];

const HomePage = () => {
  const navigate = useNavigate();
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const text = prompt.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    try {
      const task = await api.createTask(text);
      void navigate(`/tasks/${task.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start task");
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-8 pt-8 md:pt-16">
      <div>
        <p className="font-mono text-xs uppercase tracking-[0.25em] text-primary">
          What should I do?
        </p>
        <h2 className="mt-3 text-2xl font-medium tracking-tight text-foreground md:text-3xl">
          Give Ribhus a task.
        </h2>
        <p className="mt-2 text-sm text-muted-foreground md:text-base">
          Research companies, draft WhatsApp or email replies, travel shortlists —
          with approvals for anything consequential.
        </p>
      </div>

      <form onSubmit={(e) => void handleSubmit(e)} className="space-y-3">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={4}
          placeholder="Describe the task…"
          className="w-full resize-y rounded border border-input bg-card px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground/60 focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          disabled={busy}
        />
        {error ? (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={busy || !prompt.trim()}
          className="inline-flex items-center gap-2 rounded bg-primary px-4 py-2 font-mono text-xs uppercase tracking-wide text-primary-foreground disabled:opacity-40"
        >
          {busy ? "Starting…" : "Run"}
          <ArrowRight className="h-3.5 w-3.5" />
        </button>
      </form>

      <div>
        <p className="mb-2 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">
          Examples
        </p>
        <ul className="space-y-2">
          {EXAMPLES.map((example) => (
            <li key={example}>
              <button
                type="button"
                className="w-full rounded border border-border bg-card px-3 py-2 text-left text-sm text-muted-foreground hover:border-ring hover:text-foreground"
                onClick={() => setPrompt(example)}
              >
                {example}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
};

export default HomePage;
