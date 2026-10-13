import { useEffect, useState, type FormEvent } from "react";
import { api, type IConfigSafe } from "@/lib/api";
import { Button, Card, Field, PageHeader } from "@/components/ui";

const ConfigPage = () => {
  const [cfg, setCfg] = useState<IConfigSafe | null>(null);
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [autoApprove, setAutoApprove] = useState(false);
  const [approveAt, setApproveAt] = useState("high");
  const [memoryEnabled, setMemoryEnabled] = useState(true);
  const [mcpEnabled, setMcpEnabled] = useState(true);
  const [whatsappEnabled, setWhatsappEnabled] = useState(true);
  const [emailEnabled, setEmailEnabled] = useState(true);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    void api
      .getConfig()
      .then((data) => {
        setCfg(data);
        setModel(data.model);
        setBaseUrl(data.base_url);
        setAutoApprove(data.auto_approve);
        setApproveAt(data.approve_at);
        setMemoryEnabled(data.memory_enabled);
        setMcpEnabled(data.mcp_enabled);
        setWhatsappEnabled(data.whatsapp_enabled);
        setEmailEnabled(data.email_enabled);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load config");
      });
  }, []);

  const handleSave = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    setError(null);
    try {
      const updated = await api.patchConfig({
        model,
        base_url: baseUrl,
        auto_approve: autoApprove,
        approve_at: approveAt,
        memory_enabled: memoryEnabled,
        mcp_enabled: mcpEnabled,
        whatsapp_enabled: whatsappEnabled,
        email_enabled: emailEnabled,
      });
      setCfg(updated);
      setMessage("Saved. Restart the dashboard process to apply env changes fully.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  };

  if (!cfg && !error) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-6">
      <PageHeader
        title="Config"
        description="Model and feature flags. Writes .env — restart the dashboard to apply fully."
      />

      {cfg ? (
        <Card className="space-y-1 p-5 text-sm text-muted-foreground">
          <div>API key: {cfg.api_key_masked}</div>
          <div className="truncate">Workspace: {cfg.workspace}</div>
        </Card>
      ) : null}

      <form onSubmit={(e) => void handleSave(e)} className="space-y-4">
        <label className="block space-y-1.5 text-sm">
          <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Model
          </span>
          <Field value={model} onChange={(e) => setModel(e.target.value)} />
        </label>
        <label className="block space-y-1.5 text-sm">
          <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Base URL
          </span>
          <Field value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        </label>
        <label className="block space-y-1.5 text-sm">
          <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            Approve at
          </span>
          <select
            value={approveAt}
            onChange={(e) => setApproveAt(e.target.value)}
            className="w-full rounded-xl border border-input/70 bg-background/70 px-3.5 py-2.5 text-sm focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {["low", "medium", "high", "critical"].map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </label>

        <Card className="space-y-3 p-5">
          {(
            [
              ["Auto-approve (non-send)", autoApprove, setAutoApprove],
              ["Memory", memoryEnabled, setMemoryEnabled],
              ["MCP", mcpEnabled, setMcpEnabled],
              ["WhatsApp", whatsappEnabled, setWhatsappEnabled],
              ["Email", emailEnabled, setEmailEnabled],
            ] as const
          ).map(([label, value, setter]) => (
            <label
              key={label}
              className="flex items-center justify-between gap-3 text-sm text-foreground"
            >
              {label}
              <input
                type="checkbox"
                checked={value}
                onChange={(e) => setter(e.target.checked)}
                className="h-4 w-4 accent-primary"
              />
            </label>
          ))}
        </Card>

        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </Button>
      </form>

      {message ? <p className="text-sm text-success">{message}</p> : null}
      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
};

export default ConfigPage;
