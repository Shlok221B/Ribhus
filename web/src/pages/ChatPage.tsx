import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ArrowLeft, ArrowRight } from "lucide-react";
import {
  api,
  type IBot,
  type IChat,
  type IChatMessage,
  type ITask,
} from "@/lib/api";
import { MarkdownBody } from "@/components/Markdown";
import { Badge, Button, Card, TextArea, statusTone } from "@/components/ui";
import { cn } from "@/lib/utils";

const BOT_COLOR: Record<string, string> = {
  copper: "bg-[color:var(--palette-copper)]",
  blue: "bg-[color:var(--palette-blue)]",
  gold: "bg-[color:var(--palette-gold)]",
  verdigris: "bg-[color:var(--palette-verdigris)]",
  rose: "bg-[color:var(--palette-rose)]",
  info: "bg-[color:var(--palette-blue)]",
};

const colorClass = (color?: string) =>
  BOT_COLOR[color ?? "copper"] ?? BOT_COLOR.copper;

interface IChatPageProps {
  mode: "bot" | "chat";
}

const ChatPage = ({ mode }: IChatPageProps) => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [chat, setChat] = useState<IChat | null>(null);
  const [bots, setBots] = useState<IBot[]>([]);
  const [task, setTask] = useState<ITask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [editText, setEditText] = useState("");
  const [acting, setActing] = useState(false);
  const [mentionOpen, setMentionOpen] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    if (!id) return;
    try {
      const roster = await api.listBots();
      setBots(roster);
      let row: IChat;
      if (mode === "bot") {
        row = await api.getDirectChat(id);
      } else {
        row = await api.getChat(id);
      }
      setChat(row);
      setError(null);
      const activeId = row.active_task_id;
      if (activeId) {
        try {
          const t = await api.getTask(activeId);
          setTask(t);
          if (t.pending_approval) {
            const args = t.pending_approval.arguments;
            const body =
              (typeof args.message === "string" && args.message) ||
              (typeof args.body === "string" && args.body) ||
              "";
            setEditText(body);
          }
        } catch {
          setTask(null);
        }
      } else {
        setTask(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load chat");
    }
  }, [id, mode]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 1500);
    return () => window.clearInterval(timer);
  }, [load]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [chat?.messages?.length, task?.pending_approval?.id]);

  const memberBots = useMemo(() => {
    if (chat?.bots && chat.bots.length > 0) return chat.bots;
    const ids = new Set(chat?.bot_ids ?? []);
    return bots.filter((b) => ids.has(b.id));
  }, [chat, bots]);

  const title =
    chat?.kind === "group"
      ? chat.title
      : memberBots[0]?.name ?? chat?.title ?? "Chat";

  const handleSend = async (event?: FormEvent) => {
    event?.preventDefault();
    const text = draft.trim();
    if (!chat || !text || sending) return;
    setSending(true);
    setError(null);
    try {
      const result = await api.postChatMessage(chat.id, text);
      if (result.chat) setChat(result.chat);
      else await load();
      if (result.task) setTask(result.task);
      setDraft("");
      setMentionOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send");
    } finally {
      setSending(false);
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
      event.preventDefault();
      void handleSend();
      return;
    }
    if (chat?.kind === "group" && event.key === "@") {
      setMentionOpen(true);
    }
  };

  const insertMention = (bot: IBot) => {
    const base = draft.endsWith("@") ? draft.slice(0, -1) : draft;
    const needsSpace = base.length > 0 && !base.endsWith(" ");
    setDraft(`${base}${needsSpace ? " " : ""}@${bot.name} `);
    setMentionOpen(false);
  };

  const resolve = async (decision: "approve" | "deny" | "edit") => {
    if (!task?.id || acting) return;
    setActing(true);
    try {
      const updated = await api.resolveApproval(task.id, {
        decision,
        edited_text: decision === "edit" ? editText : undefined,
      });
      setTask(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Approval failed");
    } finally {
      setActing(false);
    }
  };

  if (error && !chat) {
    return (
      <p className="text-sm text-destructive" role="alert">
        {error}
      </p>
    );
  }

  if (!chat) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }

  const pending = task?.pending_approval;
  const busy =
    task != null &&
    ["queued", "running", "awaiting_approval"].includes(task.status);

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {mode === "chat" ? (
            <Link
              to="/"
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-info"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Home
            </Link>
          ) : (
            <button
              type="button"
              onClick={() => void navigate("/")}
              className="inline-flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-info"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Home
            </button>
          )}
          <h2 className="mt-2 flex items-center gap-2 text-xl font-semibold tracking-tight text-foreground md:text-2xl">
            <span
              className={cn(
                "inline-block h-3 w-3 shrink-0 rounded-full",
                colorClass(memberBots[0]?.color),
              )}
              aria-hidden
            />
            <span className="truncate">{title}</span>
          </h2>
          <div className="mt-2 flex flex-wrap gap-2">
            {memberBots.map((bot) => (
              <Badge key={bot.id} tone={bot.status === "idle" ? "neutral" : "info"}>
                {bot.name}
                {bot.status !== "idle" ? ` · ${bot.status}` : ""}
              </Badge>
            ))}
            {task ? (
              <Badge tone={statusTone(task.status)}>
                {task.status.replaceAll("_", " ")}
              </Badge>
            ) : null}
          </div>
          {memberBots[0]?.job && chat.kind === "direct" ? (
            <p className="mt-2 line-clamp-2 text-xs text-muted-foreground md:text-sm">
              {memberBots[0].job}
            </p>
          ) : null}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pb-2">
        {chat.messages.length === 0 ? (
          <Card className="p-5">
            <p className="text-sm text-muted-foreground">
              {chat.kind === "group"
                ? "Describe the shared outcome. Use @Name to assign a bot."
                : `Message ${title} to start.`}
            </p>
          </Card>
        ) : null}

        {chat.messages.map((msg) => (
          <MessageBubble key={msg.id} message={msg} />
        ))}

        {pending ? (
          <Card className="border-warning/35 p-5">
            <p className="text-xs font-medium uppercase tracking-wider text-warning">
              Approval required
            </p>
            <p className="mt-2 text-sm">
              <span className="text-muted-foreground">{pending.tool}</span>
              <span className="mx-2 text-muted-foreground">·</span>
              <span className="text-warning">{pending.risk}</span>
            </p>
            <pre className="mt-3 max-h-48 overflow-auto rounded-xl border border-border bg-background/70 p-3 text-xs text-muted-foreground">
              {JSON.stringify(pending.arguments, null, 2)}
            </pre>
            {(pending.tool === "whatsapp_send" ||
              pending.tool === "email_send") && (
              <TextArea
                value={editText}
                onChange={(e) => setEditText(e.target.value)}
                rows={4}
                className="mt-3"
                placeholder="Edit message body…"
              />
            )}
            <div className="mt-4 flex flex-wrap gap-2">
              <Button disabled={acting} onClick={() => void resolve("approve")}>
                Approve
              </Button>
              <Button
                variant="secondary"
                disabled={acting}
                onClick={() => void resolve("edit")}
              >
                Edit &amp; approve
              </Button>
              <Button
                variant="danger"
                disabled={acting}
                onClick={() => void resolve("deny")}
              >
                Cancel
              </Button>
            </div>
          </Card>
        ) : null}

        {busy && !pending ? (
          <p className="text-sm text-muted-foreground">Working…</p>
        ) : null}

        {task?.error ? (
          <p className="text-sm text-destructive" role="alert">
            {task.error}
          </p>
        ) : null}

        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={(e) => void handleSend(e)}
        className="relative space-y-3 rounded-2xl border border-border/70 bg-card/80 p-4 md:p-5"
      >
        {mentionOpen && chat.kind === "group" ? (
          <div
            className="absolute bottom-full left-4 right-4 z-10 mb-2 max-h-40 overflow-y-auto rounded-xl border border-border bg-popover p-2 shadow-lg"
            role="listbox"
            aria-label="Mention a bot"
          >
            {memberBots.map((bot) => (
              <button
                key={bot.id}
                type="button"
                className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-accent"
                onClick={() => insertMention(bot)}
              >
                <span
                  className={cn("h-2.5 w-2.5 rounded-full", colorClass(bot.color))}
                />
                @{bot.name}
              </button>
            ))}
          </div>
        ) : null}
        <TextArea
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            if (chat.kind === "group" && e.target.value.endsWith("@")) {
              setMentionOpen(true);
            }
          }}
          onKeyDown={handleKeyDown}
          rows={3}
          placeholder={
            chat.kind === "group"
              ? "Message the group… use @Name to assign"
              : `Message ${title}…`
          }
          disabled={sending}
          aria-label="Chat message"
        />
        {error ? (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        ) : null}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-xs text-muted-foreground">⌘ / Ctrl + Enter to send</p>
          <Button
            type="submit"
            disabled={sending || !draft.trim()}
            className="w-full sm:w-auto"
          >
            {sending ? "Sending…" : "Send"}
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </form>
    </div>
  );
};

const MessageBubble = ({ message }: { message: IChatMessage }) => {
  if (message.role === "handoff") {
    return (
      <Card className="border-info/30 bg-info/5 p-4">
        <p className="text-xs font-medium uppercase tracking-wider text-info">
          Handoff
        </p>
        <p className="mt-2 text-sm text-foreground/90">{message.content}</p>
      </Card>
    );
  }
  if (message.role === "user") {
    return (
      <Card className="p-4 md:p-5">
        <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          You
        </h3>
        <p className="mt-2 whitespace-pre-wrap text-sm leading-relaxed text-foreground/90">
          {message.content}
        </p>
      </Card>
    );
  }
  if (message.role === "system") {
    return (
      <p className="px-1 text-xs text-muted-foreground">{message.content}</p>
    );
  }
  return (
    <Card className="p-4 md:p-5">
      <h3 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
        {message.bot_name ?? "Assistant"}
      </h3>
      <MarkdownBody className="mt-3">{message.content}</MarkdownBody>
    </Card>
  );
};

export default ChatPage;
