import { useEffect, useState } from "react";
import { api, type IMcpServer } from "@/lib/api";

const McpPage = () => {
  const [servers, setServers] = useState<IMcpServer[]>([]);
  const [errors, setErrors] = useState<string[]>([]);
  const [configPath, setConfigPath] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [testOut, setTestOut] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = async () => {
    try {
      const data = await api.listMcp();
      setServers(data.servers);
      setErrors(data.errors);
      setConfigPath(data.config_path);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load MCP");
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const handleTest = async (name: string) => {
    setBusy(name);
    setTestOut(null);
    try {
      const res = await api.testMcp(name);
      setTestOut(`${name}: ${res.result}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Test failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <p className="text-sm text-muted-foreground">
        External tools from{" "}
        <code className="font-mono text-xs text-info">
          {configPath || ".ribhus/mcp.json"}
        </code>
        . Run{" "}
        <code className="font-mono text-xs">ribhus mcp init</code> if missing.
      </p>

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      {testOut ? (
        <pre className="overflow-x-auto rounded border border-border bg-card p-3 text-xs text-success">
          {testOut}
        </pre>
      ) : null}
      {errors.length > 0 ? (
        <ul className="space-y-1 text-sm text-warning">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      ) : null}

      {servers.length === 0 ? (
        <p className="text-sm text-muted-foreground">No MCP servers configured.</p>
      ) : (
        <ul className="space-y-3">
          {servers.map((server) => (
            <li
              key={server.name}
              className="rounded border border-border bg-card p-4"
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h3 className="font-mono text-sm text-foreground">{server.name}</h3>
                  <p className="mt-1 font-mono text-[10px] text-muted-foreground">
                    {server.enabled
                      ? server.connected
                        ? "connected"
                        : "offline"
                      : "disabled"}{" "}
                    · risk={server.risk} · {server.command}
                  </p>
                </div>
                {server.enabled ? (
                  <button
                    type="button"
                    disabled={busy !== null}
                    onClick={() => void handleTest(server.name)}
                    className="rounded border border-border px-3 py-1.5 font-mono text-[10px] uppercase"
                  >
                    {busy === server.name ? "Testing…" : "Test"}
                  </button>
                ) : null}
              </div>
              {server.tools.length > 0 ? (
                <ul className="mt-3 space-y-1 font-mono text-[11px] text-muted-foreground">
                  {server.tools.map((t) => (
                    <li key={t}>
                      {server.name}__{t}
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default McpPage;
