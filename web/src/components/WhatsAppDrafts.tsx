import { useEffect, useMemo, useState } from "react";
import { Check, ExternalLink, MessageCircle, SkipForward } from "lucide-react";
import {
  applyWhatsAppTemplate,
  buildWhatsAppLink,
  countByStatus,
  loadWhatsAppDraftsState,
  saveWhatsAppDraftsState,
  type IWhatsAppDraftStatus,
  type IWhatsAppDraftsPayload,
  type IWhatsAppRecipient,
} from "@/lib/whatsappDrafts";
import { Badge, Button, TextArea } from "@/components/ui";
import { cn } from "@/lib/utils";

interface IWhatsAppDraftsProps {
  payload: IWhatsAppDraftsPayload;
  /** Persist Opened/Sent/Skip + template edits (e.g. task id). */
  storageKey: string;
  className?: string;
}

const statusTone = (
  status: IWhatsAppDraftStatus,
): "neutral" | "info" | "success" | "warning" => {
  if (status === "sent") return "success";
  if (status === "opened") return "info";
  if (status === "skip") return "warning";
  return "neutral";
};

const statusLabel = (status: IWhatsAppDraftStatus): string => {
  if (status === "pending") return "Ready";
  if (status === "opened") return "Opened";
  if (status === "sent") return "Sent";
  return "Skipped";
};

const formatPhoneDisplay = (digits: string): string => {
  if (digits.startsWith("91") && digits.length === 12) {
    return `+91 ${digits.slice(2, 7)} ${digits.slice(7)}`;
  }
  return `+${digits}`;
};

const RecipientRow = ({
  recipient,
  index,
  status,
  href,
  onWhatsApp,
  onMark,
}: {
  recipient: IWhatsAppRecipient;
  index: number;
  status: IWhatsAppDraftStatus;
  href: string | null;
  onWhatsApp: () => void;
  onMark: (next: IWhatsAppDraftStatus) => void;
}) => (
  <article
    className={cn(
      "rounded-xl border border-border/70 bg-background/50 p-3 sm:p-3.5",
      status === "skip" && "opacity-60",
      status === "sent" && "border-success/30",
    )}
  >
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            #{index + 1}
          </p>
          <Badge tone={statusTone(status)}>{statusLabel(status)}</Badge>
        </div>
        <h3 className="mt-1 text-sm font-semibold leading-snug text-foreground">
          {recipient.name}
        </h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {formatPhoneDisplay(recipient.phone)}
        </p>
        {recipient.note ? (
          <p className="mt-1 line-clamp-2 text-[11px] text-muted-foreground/80">
            {recipient.note}
          </p>
        ) : null}
      </div>

      <div className="flex flex-wrap items-center gap-2 sm:justify-end">
        <Button
          type="button"
          className="min-h-10 flex-1 sm:flex-none"
          disabled={!href || status === "skip"}
          onClick={onWhatsApp}
          aria-label={`WhatsApp ${recipient.name}`}
        >
          <MessageCircle className="h-4 w-4" aria-hidden />
          WhatsApp
          <ExternalLink className="h-3.5 w-3.5 opacity-70" aria-hidden />
        </Button>
        <Button
          type="button"
          variant="secondary"
          className="min-h-10"
          disabled={status === "sent"}
          onClick={() => onMark("sent")}
          aria-label={`Mark ${recipient.name} sent`}
        >
          <Check className="h-4 w-4" aria-hidden />
          Sent
        </Button>
        <Button
          type="button"
          variant="ghost"
          className="min-h-10"
          onClick={() => onMark(status === "skip" ? "pending" : "skip")}
          aria-label={
            status === "skip"
              ? `Unskip ${recipient.name}`
              : `Skip ${recipient.name}`
          }
        >
          <SkipForward className="h-4 w-4" aria-hidden />
          {status === "skip" ? "Unskip" : "Skip"}
        </Button>
      </div>
    </div>
  </article>
);

export const WhatsAppDrafts = ({
  payload,
  storageKey,
  className,
}: IWhatsAppDraftsProps) => {
  const payloadFingerprint = useMemo(
    () =>
      JSON.stringify({
        title: payload.title ?? "",
        template: payload.template ?? "",
        recipients: payload.recipients.map((row) => ({
          id: row.id,
          name: row.name,
          phone: row.phone,
        })),
      }),
    [payload],
  );

  const [state, setState] = useState(() =>
    loadWhatsAppDraftsState(storageKey, payload),
  );

  useEffect(() => {
    setState(loadWhatsAppDraftsState(storageKey, payload));
    // Reload only when the draft list / default template identity changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fingerprint covers payload
  }, [storageKey, payloadFingerprint]);

  useEffect(() => {
    saveWhatsAppDraftsState(storageKey, state);
  }, [storageKey, state]);

  const counts = useMemo(
    () => countByStatus(payload.recipients, state.statuses),
    [payload.recipients, state.statuses],
  );

  const handleTemplateChange = (value: string) => {
    setState((prev) => ({ ...prev, template: value }));
  };

  const handleMark = (id: string, next: IWhatsAppDraftStatus) => {
    setState((prev) => ({
      ...prev,
      statuses: { ...prev.statuses, [id]: next },
    }));
  };

  const handleWhatsApp = (recipient: IWhatsAppRecipient) => {
    const message = applyWhatsAppTemplate(state.template, recipient);
    const href = buildWhatsAppLink(recipient.phone, message);
    if (!href) return;
    window.open(href, "_blank", "noopener,noreferrer");
    setState((prev) => {
      const current = prev.statuses[recipient.id] ?? "pending";
      if (current === "sent" || current === "skip") return prev;
      return {
        ...prev,
        statuses: { ...prev.statuses, [recipient.id]: "opened" },
      };
    });
  };

  if (!payload.recipients?.length) return null;

  return (
    <section
      className={cn(
        "rounded-2xl border border-border/60 bg-card/55 p-3.5 shadow-[0_16px_48px_-28px_rgba(232,66,44,0.28)] backdrop-blur-md sm:p-4",
        className,
      )}
      aria-label="WhatsApp drafts"
    >
      <header className="space-y-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-sm font-semibold text-foreground">
            {payload.title?.trim() || "WhatsApp drafts"}
          </h2>
          <p className="text-[11px] text-muted-foreground">
            {counts.sent} sent · {counts.opened} opened · {counts.skip} skipped ·{" "}
            {counts.pending} left
          </p>
        </div>
        <p className="text-xs text-muted-foreground">
          Edit the template once. Each WhatsApp button opens a chat with the
          draft filled in — you press Send. Use{" "}
          <code className="rounded bg-background/80 px-1 py-0.5 text-[11px]">
            {"{{name}}"}
          </code>{" "}
          for the contact name.
        </p>
      </header>

      <label className="mt-3 block">
        <span className="sr-only">Shared message template</span>
        <TextArea
          value={state.template}
          onChange={(event) => handleTemplateChange(event.target.value)}
          rows={7}
          aria-label="Shared WhatsApp message template"
          className="min-h-[9rem] font-normal"
        />
      </label>

      <div className="mt-3 space-y-2.5">
        {payload.recipients.map((recipient, index) => {
          const message = applyWhatsAppTemplate(state.template, recipient);
          const href = buildWhatsAppLink(recipient.phone, message);
          const status = state.statuses[recipient.id] ?? "pending";
          return (
            <RecipientRow
              key={recipient.id}
              recipient={recipient}
              index={index}
              status={status}
              href={href}
              onWhatsApp={() => handleWhatsApp(recipient)}
              onMark={(next) => handleMark(recipient.id, next)}
            />
          );
        })}
      </div>
    </section>
  );
};

export default WhatsAppDrafts;
