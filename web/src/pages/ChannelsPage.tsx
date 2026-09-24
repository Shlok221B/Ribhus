import { useEffect, useState } from "react";
import { api, type IChannelStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const ChannelsPage = () => {
  const [channels, setChannels] = useState<IChannelStatus[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = async () => {
    try {
      setChannels(await api.listChannels());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load channels");
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const act = async (channel: "whatsapp" | "email", action: "kill" | "resume") => {
    const key = `${channel}:${action}`;
    setBusy(key);
    try {
      await api.channelAction(channel, action);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <p className="text-sm text-muted-foreground">
        Browser-automation channels (not official APIs). QR / Google sign-in
        stays in Chromium via CLI —{" "}
        <code className="font-mono text-xs text-info">
          ribhus whatsapp status --check-login
        </code>
        .
      </p>

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <ul className="space-y-3">
        {channels.map((ch) => (
          <li
            key={ch.channel}
            className="rounded border border-border bg-card p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="font-mono text-sm uppercase tracking-wide text-foreground">
                {ch.channel}
              </h3>
              <div className="flex gap-2 font-mono text-[10px] uppercase">
                <span className={ch.enabled ? "text-success" : "text-destructive"}>
                  {ch.enabled ? "enabled" : "disabled"}
                </span>
                <span className={ch.killed ? "text-destructive" : "text-success"}>
                  {ch.killed ? "killed" : "live"}
                </span>
              </div>
            </div>
            <p className="mt-2 text-sm text-muted-foreground">{ch.note}</p>
            <p className="mt-2 font-mono text-[10px] text-muted-foreground/70">
              profile: {ch.profile_dir}
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy !== null}
                onClick={() =>
                  void act(ch.channel as "whatsapp" | "email", "kill")
                }
                className={cn(
                  "rounded border border-destructive/40 px-3 py-1.5 font-mono text-[10px] uppercase text-destructive",
                  busy?.startsWith(ch.channel) && "opacity-40",
                )}
              >
                Kill
              </button>
              <button
                type="button"
                disabled={busy !== null}
                onClick={() =>
                  void act(ch.channel as "whatsapp" | "email", "resume")
                }
                className="rounded border border-border px-3 py-1.5 font-mono text-[10px] uppercase text-foreground"
              >
                Resume
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
};

export default ChannelsPage;
