import { useEffect, useState } from "react";
import { api, type IMcpServer } from "@/lib/api";
import { Badge, Button, Card, PageHeader, statusTone } from "@/components/ui";

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

  const serverState = (server: IMcpServer) => {
    if (!server.enabled) return "disabled";
    return server.connected ? "connected" : "offline";
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <PageHeader
        title="MCP"
        description={`External tools from ${configPath || ".ribhus/mcp.json"}. Run ribhus mcp init if missing.`}
      />

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}
      {testOut ? (
        <Card className="p-4">
          <pre className="overflow-x-auto text-xs text-success">{testOut}</pre>
        </Card>
      ) : null}
      {errors.length > 0 ? (
        <ul className="space-y-1 text-sm text-warning">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      ) : null}

      {servers.length === 0 ? (
        <Card className="p-6 text-sm text-muted-foreground">
          No MCP servers configured.
        </Card>
      ) : (
        <ul className="space-y-3">
          {servers.map((server) => (
            <li key={server.name}>
              <Card className="p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-foreground">
                        {server.name}
                      </h3>
                      <Badge tone={statusTone(serverState(server))}>
                        {serverState(server)}
                      </Badge>
                    </div>
                    <p className="mt-2 text-xs text-muted-foreground">
                      risk={server.risk} · {server.command}
                    </p>
                  </div>
                  {server.enabled ? (
                    <Button
                      variant="secondary"
                      disabled={busy !== null}
                      onClick={() => void handleTest(server.name)}
                    >
                      {busy === server.name ? "Testing…" : "Test"}
                    </Button>
                  ) : null}
                </div>
                {server.tools.length > 0 ? (
                  <ul className="mt-4 flex flex-wrap gap-1.5">
                    {server.tools.map((t) => (
                      <li key={t}>
                        <Badge>
                          {server.name}__{t}
                        </Badge>
                      </li>
                    ))}
                  </ul>
                ) : null}
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

export default McpPage;
