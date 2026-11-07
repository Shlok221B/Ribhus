import { useEffect, useState, type SyntheticEvent } from "react";
import { api, type IJobApplication, type IJobBatch } from "@/lib/api";
import { JobDraftReview } from "@/components/JobDraftReview";
import { Badge, Button, Card } from "@/components/ui";

interface IJobBatchPanelProps {
  batch: IJobBatch;
  busy: boolean;
  approved: boolean;
  progress: string | null;
  result: string | null;
  onChange: (batch: IJobBatch) => void;
  onApproved: (approved: boolean) => void;
  onSend: () => void;
}

interface IJobResumePdfProps {
  applicationId: string;
  company: string;
}

const JobResumePdf = ({ applicationId, company }: IJobResumePdfProps) => {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [url]);

  const handleToggle = (event: SyntheticEvent<HTMLDetailsElement>) => {
    if (!event.currentTarget.open || url) return;
    void api.jobPdf(applicationId).then((blob) => {
      setUrl((current) => {
        if (current) URL.revokeObjectURL(current);
        return URL.createObjectURL(blob);
      });
    });
  };

  return (
    <details className="mt-3" onToggle={handleToggle}>
      <summary className="cursor-pointer text-sm text-foreground">Resume PDF</summary>
      {url ? (
        <iframe
          title={`Resume PDF for ${company}`}
          src={url}
          className="mt-3 h-80 w-full rounded-xl border border-border bg-background sm:h-[32rem]"
        />
      ) : null}
    </details>
  );
};

const statusTone = (status: string) => {
  if (status === "sent") return "success" as const;
  if (status === "failed") return "danger" as const;
  if (status === "skipped") return "neutral" as const;
  return "warning" as const;
};

export const JobBatchPanel = ({
  batch,
  busy,
  approved,
  progress,
  result,
  onChange,
  onApproved,
  onSend,
}: IJobBatchPanelProps) => {
  const applications = batch.applications ?? [];
  const kept = applications.filter((app) => app.kept !== false);
  const ready = kept.filter((app) => app.status !== "sent" && app.to.includes("@"));

  const handlePatch = (id: string, patch: Partial<IJobApplication>) => {
    onApproved(false);
    onChange({
      ...batch,
      applications: applications.map((app) => (app.id === id ? { ...app, ...patch } : app)),
    });
  };

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="text-base font-semibold text-foreground">
            {applications.length} opening{applications.length === 1 ? "" : "s"}
          </h3>
          <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
            Review each draft, then drop any you do not want to send.
          </p>
        </div>
        <Badge tone={batch.status === "done" ? "success" : batch.status === "failed" ? "danger" : "warning"}>
          {batch.status}
        </Badge>
      </div>

      {batch.note ? (
        <p className="mt-3 text-sm leading-relaxed text-muted-foreground">{batch.note}</p>
      ) : null}
      {batch.error ? (
        <p className="mt-3 text-sm text-destructive" role="alert">
          {batch.error}
        </p>
      ) : null}
      {progress ? (
        <p className="mt-3 text-sm text-foreground" role="status">
          {progress}
        </p>
      ) : null}
      {result ? <p className="mt-3 text-sm text-foreground">{result}</p> : null}

      <div className="mt-4 flex flex-col gap-4">
        {applications.map((app) => {
          const dropped = app.kept === false;
          const locked = busy || app.status === "sent";
          return (
            <div
              key={app.id}
              className={`rounded-2xl border border-border p-4 ${dropped ? "opacity-60" : ""}`}
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <h4 className="text-sm font-semibold text-foreground">
                    {app.role || "Role"}
                    {app.company && app.company !== "Company" ? ` · ${app.company}` : ""}
                  </h4>
                  {app.url ? (
                    <a
                      href={app.url}
                      className="mt-1 block truncate text-xs text-primary underline-offset-2 hover:underline"
                      target="_blank"
                      rel="noreferrer"
                    >
                      {app.url}
                    </a>
                  ) : null}
                </div>
                <Badge tone={statusTone(app.status)}>{dropped ? "dropped" : app.status}</Badge>
              </div>

              {app.error ? (
                <p className="mt-2 text-sm text-destructive" role="alert">
                  {app.error}
                </p>
              ) : null}

              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  variant={dropped ? "ghost" : "secondary"}
                  disabled={locked}
                  aria-pressed={!dropped}
                  onClick={() => handlePatch(app.id, { kept: true })}
                >
                  Keep
                </Button>
                <Button
                  variant={dropped ? "danger" : "ghost"}
                  disabled={locked}
                  aria-pressed={dropped}
                  onClick={() => handlePatch(app.id, { kept: false })}
                >
                  Drop
                </Button>
              </div>

              <JobDraftReview
                application={app}
                locked={locked}
                onChange={(patch) => handlePatch(app.id, patch)}
              />
              {app.pdf_ready ? <JobResumePdf applicationId={app.id} company={app.company || "company"} /> : null}
            </div>
          );
        })}
      </div>

      <label className="mt-4 flex items-start gap-2 text-sm text-foreground">
        <input
          type="checkbox"
          className="mt-1"
          checked={approved}
          disabled={busy || ready.length === 0}
          onChange={(event) => onApproved(event.target.checked)}
        />
        <span>I approve sending the kept emails and the attached resume PDF.</span>
      </label>
      <Button
        className="mt-4 w-full sm:w-auto"
        disabled={busy || !approved || ready.length === 0}
        onClick={onSend}
      >
        {busy ? "Sending…" : "Send one by one"}
      </Button>
    </Card>
  );
};
