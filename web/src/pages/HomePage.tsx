import { useState, type FormEvent, type KeyboardEvent } from "react";
import { useNavigate } from "react-router";
import { ArrowRight, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { Button, TextArea } from "@/components/ui";

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

  const handleSubmit = async (event?: FormEvent) => {
    event?.preventDefault();
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

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void handleSubmit();
    }
  };

  return (
    <div className="relative -m-4 min-h-full overflow-hidden md:-m-8">
      <img
        src="/ribhus-2.png"
        alt=""
        aria-hidden
        className="pointer-events-none absolute inset-0 h-full w-full object-cover opacity-[0.08]"
      />
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-b from-background/20 via-background/55 to-background" />

      <div className="relative mx-auto flex w-full max-w-2xl flex-col gap-10 px-4 py-10 md:px-6 md:pt-20">
        <div className="space-y-4">
          <p className="inline-flex items-center gap-2 rounded-full border border-primary/25 bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
            <Sparkles className="h-3.5 w-3.5" />
            What should I do?
          </p>
          <h2 className="text-3xl font-semibold tracking-tight text-foreground md:text-5xl">
            Give Ribhus a task.
          </h2>
          <p className="max-w-xl text-sm leading-relaxed text-muted-foreground md:text-base">
            Research companies, draft WhatsApp or email replies, travel
            shortlists — with approvals for anything consequential.
          </p>
        </div>

        <form
          onSubmit={(e) => void handleSubmit(e)}
          className="glow-generate space-y-4 rounded-2xl border border-border/70 bg-card/80 p-4 backdrop-blur-md md:p-5"
        >
          <TextArea
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={5}
            placeholder="Describe the task…"
            disabled={busy}
            className="min-h-32 border-transparent bg-transparent px-1 py-1 text-base focus-visible:ring-0"
          />
          {error ? (
            <p className="text-sm text-destructive" role="alert">
              {error}
            </p>
          ) : null}
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <p className="text-xs text-muted-foreground">
              ⌘ / Ctrl + Enter to run
            </p>
            <Button
              type="submit"
              disabled={busy || !prompt.trim()}
              className="w-full sm:w-auto"
            >
              {busy ? "Starting…" : "Run task"}
              <ArrowRight className="h-4 w-4" />
            </Button>
          </div>
        </form>

        <div>
          <p className="mb-3 text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Try one
          </p>
          <ul className="flex flex-col gap-2">
            {EXAMPLES.map((example) => (
              <li key={example}>
                <button
                  type="button"
                  className="w-full rounded-xl border border-border/70 bg-card/60 px-4 py-3 text-left text-sm text-muted-foreground transition-colors hover:border-ring/50 hover:bg-card hover:text-foreground"
                  onClick={() => setPrompt(example)}
                >
                  {example}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
};

export default HomePage;
