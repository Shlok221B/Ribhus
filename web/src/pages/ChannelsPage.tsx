import { useEffect, useState } from "react";
import { api, type IChannelStatus } from "@/lib/api";
import { Badge, Button, Card, PageHeader } from "@/components/ui";

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
      <PageHeader
        title="Channels"
        description="Browser-automation channels (not official APIs). QR and Google sign-in stay in Chromium via the CLI."
      />

      {error ? (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      ) : null}

      <ul className="space-y-3">
        {channels.map((ch) => (
          <li key={ch.channel}>
            <Card className="p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h3 className="text-base font-semibold capitalize text-foreground">
                  {ch.channel}
                </h3>
                <div className="flex gap-2">
                  <Badge tone={ch.enabled ? "success" : "danger"}>
                    {ch.enabled ? "enabled" : "disabled"}
                  </Badge>
                  <Badge tone={ch.killed ? "danger" : "success"}>
                    {ch.killed ? "killed" : "live"}
                  </Badge>
                </div>
              </div>
              <p className="mt-3 text-sm leading-relaxed text-muted-foreground">
                {ch.note}
              </p>
              <p className="mt-2 truncate text-[11px] text-muted-foreground/70">
                profile: {ch.profile_dir}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button
                  variant="danger"
                  disabled={busy !== null}
                  onClick={() =>
                    void act(ch.channel as "whatsapp" | "email", "kill")
                  }
                >
                  Kill
                </Button>
                <Button
                  variant="secondary"
                  disabled={busy !== null}
                  onClick={() =>
                    void act(ch.channel as "whatsapp" | "email", "resume")
                  }
                >
                  Resume
                </Button>
              </div>
            </Card>
          </li>
        ))}
      </ul>
    </div>
  );
};

export default ChannelsPage;
