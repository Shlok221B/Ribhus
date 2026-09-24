import { useEffect, useState, type FormEvent } from "react";
import { api, type IConfigSafe } from "@/lib/api";

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
    return <p className="font-mono text-sm text-muted-foreground">Loading…</p>;
  }

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-6">
      {cfg ? (
        <div className="rounded border border-border bg-card p-4 font-mono text-xs text-muted-foreground">
          <div>API key: {cfg.api_key_masked}</div>
          <div className="mt-1">Workspace: {cfg.workspace}</div>
        </div>
      ) : null}

      <form onSubmit={(e) => void handleSave(e)} className="space-y-4">
        <label className="block space-y-1 text-sm">
          <span className="font-mono text-[10px] uppercase text-muted-foreground">
            Model
          </span>
          <input
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-full rounded border border-input bg-card px-3 py-2"
          />
        </label>
        <label className="block space-y-1 text-sm">
          <span className="font-mono text-[10px] uppercase text-muted-foreground">
            Base URL
          </span>
          <input
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            className="w-full rounded border border-input bg-card px-3 py-2"
          />
        </label>
        <label className="block space-y-1 text-sm">
          <span className="font-mono text-[10px] uppercase text-muted-foreground">
            Approve at
          </span>
          <select
            value={approveAt}
            onChange={(e) => setApproveAt(e.target.value)}
            className="w-full rounded border border-input bg-card px-3 py-2"
          >
            {["low", "medium", "high", "critical"].map((level) => (
              <option key={level} value={level}>
                {level}
              </option>
            ))}
          </select>
        </label>

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
            className="flex items-center gap-2 text-sm text-foreground"
          >
            <input
              type="checkbox"
              checked={value}
              onChange={(e) => setter(e.target.checked)}
              className="accent-primary"
            />
            {label}
          </label>
        ))}

        <button
          type="submit"
          disabled={busy}
          className="rounded bg-primary px-4 py-2 font-mono text-xs uppercase text-primary-foreground disabled:opacity-40"
        >
          {busy ? "Saving…" : "Save"}
        </button>
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
