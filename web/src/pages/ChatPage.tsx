import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { useNavigate, useParams } from "react-router";

import {
  ArrowUp,
  Ellipsis,
  FileText,
  Paperclip,
  Plus,
  Trash2,
  X,
} from "lucide-react";
import {
  api,
  type IBot,
  type IChat,
  type IChatMessage,
  type IChatUpload,
  type ITask,
} from "@/lib/api";
import { ResearchMessageBody } from "@/components/JobResults";
import { ResearchStatus } from "@/components/ResearchStatus";
import {
  BOT_BG,
  Badge,
  BotAvatar,
  Button,
  Card,
  TextArea,
  statusTone,
} from "@/components/ui";
import { researchProgressFromTask } from "@/lib/researchStatus";
import { cn } from "@/lib/utils";

const colorClass = (color?: string) => BOT_BG[color ?? "copper"] ?? BOT_BG.copper;

const formatBytes = (n: number) => {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
};

const buildMessageWithAttachments = (
  text: string,
  files: IChatUpload[],
): string => {
  const body = text.trim();
  if (files.length === 0) return body;
  const lines = files.map((f) => {
    const note = f.extract_error
      ? ` (extract failed: ${f.extract_error})`
      : f.extracted_text
        ? " (text extracted)"
        : "";
    return `- ${f.name} (workspace path: \`${f.path}\`${note})`;
  });
  const block = `Attached file${files.length > 1 ? "s" : ""}:\n${lines.join("\n")}`;
  return body ? `${body}\n\n${block}` : block;
};

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
  const [attachments, setAttachments] = useState<IChatUpload[]>([]);
  const [uploading, setUploading] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

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

  useEffect(() => {
    setMenuOpen(false);
  }, [id, mode]);

  useEffect(() => {
    if (!menuOpen) return;
    const handlePointer = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };
    const handleKey = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", handlePointer);
    document.addEventListener("keydown", handleKey);
    return () => {
      document.removeEventListener("mousedown", handlePointer);
      document.removeEventListener("keydown", handleKey);
    };
  }, [menuOpen]);

  const memberBots = useMemo(() => {
    if (chat?.bots && chat.bots.length > 0) return chat.bots;
    const ids = new Set(chat?.bot_ids ?? []);
    return bots.filter((b) => ids.has(b.id));
  }, [chat, bots]);

  const title =
    chat?.kind === "group"
      ? chat.title
      : memberBots[0]?.name ?? chat?.title ?? "Chat";

  const canDeleteBot = mode === "bot" && Boolean(id) && bots.length > 1;

  const handleDeleteBot = async () => {
    if (!id || !canDeleteBot || deleting) return;
    const name = memberBots[0]?.name ?? title;
    const ok = window.confirm(
      `Delete ${name}? Direct chat and private memories for this bot will be removed.`,
    );
    if (!ok) {
      setMenuOpen(false);
      return;
    }
    setDeleting(true);
    setError(null);
    setMenuOpen(false);
    try {
      await api.deleteBot(id);
      const remaining = bots.filter((b) => b.id !== id);
      const next =
        remaining.find((b) => b.is_primary)?.id ?? remaining[0]?.id ?? null;
      void navigate(next ? `/bots/${next}` : "/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not delete bot");
      setDeleting(false);
    }
  };

  const handleSend = async (event?: FormEvent) => {
    event?.preventDefault();
    const text = draft.trim();
    if (!chat || sending || uploading) return;
    if (!text && attachments.length === 0) return;
    setSending(true);
    setError(null);
    try {
      const content = buildMessageWithAttachments(text, attachments);
      const result = await api.postChatMessage(chat.id, content);
      if (result.chat) setChat(result.chat);
      else await load();
      if (result.task) setTask(result.task);
      setDraft("");
      setAttachments([]);
      setMentionOpen(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send");
    } finally {
      setSending(false);
    }
  };

  const handlePickFile = () => {
    fileInputRef.current?.click();
  };

  const handleFileSelected = async (
    event: ChangeEvent<HTMLInputElement>,
  ) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !chat || uploading) return;
    setUploading(true);
    setError(null);
    try {
      const uploaded = await api.uploadChatFile(chat.id, file);
      setAttachments((prev) => {
        if (prev.some((a) => a.path === uploaded.path)) return prev;
        return [...prev, uploaded];
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const removeAttachment = (path: string) => {
    setAttachments((prev) => prev.filter((a) => a.path !== path));
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
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
  const researchProgress = researchProgressFromTask(task);

  return (
    <div className="mx-auto flex h-full w-full max-w-3xl flex-col gap-3">
      <div className="animate-fade-in flex justify-center">
        <div className="relative flex max-w-full items-center gap-2.5 rounded-full bg-card px-2 py-1.5 pr-2 shadow-[0_8px_30px_-12px_rgba(0,0,0,0.8)] sm:pr-3">
          {chat.kind === "group" ? (
            <span className="flex -space-x-2">
              {memberBots.slice(0, 3).map((bot) => (
                <BotAvatar
                  key={bot.id}
                  color={bot.color}
                  size="sm"
                  className="ring-2 ring-card"
                />
              ))}
            </span>
          ) : (
            <BotAvatar
              color={memberBots[0]?.color}
              size="sm"
              live={memberBots[0] != null && memberBots[0].status !== "idle"}
            />
          )}
          <span className="truncate text-sm font-semibold text-foreground">
            {title}
          </span>
          {task && task.status !== "completed" ? (
            <Badge tone={statusTone(task.status)}>
              {researchProgress?.phase === "working" || !researchProgress
                ? task.status.replaceAll("_", " ")
                : researchProgress.label}
            </Badge>
          ) : null}
          {mode === "bot" ? (
            <div className="relative shrink-0" ref={menuRef}>
              <button
                type="button"
                className="press-scale flex h-8 w-8 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                aria-label="Bot options"
                aria-haspopup="menu"
                aria-expanded={menuOpen}
                disabled={deleting}
                onClick={() => setMenuOpen((open) => !open)}
              >
                <Ellipsis className="h-4 w-4" />
              </button>
              {menuOpen ? (
                <div
                  className="animate-scale-in absolute right-0 top-full z-20 mt-2 w-44 rounded-xl border border-border bg-popover p-1 shadow-lg"
                  role="menu"
                >
                  <button
                    type="button"
                    role="menuitem"
                    disabled={!canDeleteBot || deleting}
                    title={
                      canDeleteBot
                        ? "Delete this bot"
                        : "Keep at least one bot"
                    }
                    className="press-scale flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-destructive transition-colors hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-40"
                    onClick={() => void handleDeleteBot()}
                  >
                    <Trash2 className="h-4 w-4 shrink-0" />
                    {deleting ? "Deleting…" : "Delete bot"}
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pb-2">
        {chat.messages.length === 0 ? (
          <p className="animate-fade-in mt-8 text-center text-sm text-muted-foreground">
            {chat.kind === "group"
              ? "Describe the shared outcome. Use @Name to assign a bot."
              : `Message ${title} to start.`}
          </p>
        ) : null}

        {chat.messages.map((msg) => (
          <MessageBubble
            key={msg.id}
            message={msg}
            showName={chat.kind === "group"}
          />
        ))}

        {pending ? (
          <Card className="animate-scale-in animate-glow-breathe border-0 p-5">
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

        {busy && !pending && researchProgress ? (
          <ResearchStatus progress={researchProgress} />
        ) : null}

        {task?.error ? (
          <div
            className="animate-bubble-bot max-w-[85%] self-start rounded-[1.4rem] rounded-bl-lg bg-destructive px-4 py-3 text-sm leading-relaxed text-white"
            role="alert"
          >
            {task.error}
          </div>
        ) : null}

        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={(e) => void handleSend(e)}
        className="composer-glow relative rounded-[1.75rem] bg-card p-2"
      >
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={(e) => void handleFileSelected(e)}
          accept=".txt,.md,.csv,.json,.yaml,.yml,.toml,.tex,.py,.js,.ts,.tsx,.jsx,.html,.css,.xml,.pdf,.docx,.doc,.rtf,.png,.jpg,.jpeg,.webp,.gif,.svg"
          aria-hidden
          tabIndex={-1}
        />
        {mentionOpen && chat.kind === "group" ? (
          <div
            className="animate-scale-in absolute bottom-full left-4 right-4 z-10 mb-2 max-h-40 overflow-y-auto rounded-xl border border-border bg-popover p-2 shadow-lg"
            role="listbox"
            aria-label="Mention a bot"
          >
            {memberBots.map((bot) => (
              <button
                key={bot.id}
                type="button"
                className="press-scale flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors hover:bg-accent"
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
        {attachments.length > 0 ? (
          <ul className="flex flex-wrap gap-2 px-2 pb-1 pt-1">
            {attachments.map((file) => (
              <li
                key={file.path}
                className="animate-scale-in flex max-w-full items-center gap-2 rounded-full bg-background/80 px-3 py-1.5 text-xs text-foreground"
              >
                <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 truncate font-medium">{file.name}</span>
                <span className="shrink-0 text-muted-foreground">
                  {formatBytes(file.size)}
                </span>
                <button
                  type="button"
                  className="press-scale rounded-full p-0.5 text-muted-foreground hover:text-foreground"
                  aria-label={`Remove ${file.name}`}
                  onClick={() => removeAttachment(file.path)}
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        {error ? (
          <p className="px-3 pb-1 text-xs text-destructive" role="alert">
            {error}
          </p>
        ) : null}
        <div className="flex items-end gap-1.5 pl-1">
          <button
            type="button"
            onClick={handlePickFile}
            disabled={sending || uploading}
            aria-label="Attach file"
            title="Attach file"
            className="press-scale mb-0.5 flex h-10 w-10 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-40"
          >
            {uploading ? (
              <Paperclip className="h-5 w-5 animate-pulse" />
            ) : (
              <Plus className="h-5 w-5" />
            )}
          </button>
          <TextArea
            value={draft}
            onChange={(e) => {
              setDraft(e.target.value);
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
              if (chat.kind === "group" && e.target.value.endsWith("@")) {
                setMentionOpen(true);
              }
            }}
            onKeyDown={handleKeyDown}
            rows={1}
            placeholder={
              chat.kind === "group"
                ? `Message ${title}… use @Name to assign`
                : `Message ${title}`
            }
            disabled={sending}
            aria-label="Chat message"
            className="max-h-40 min-h-0 flex-1 resize-none border-0 bg-transparent px-0 py-2.5 text-[15px] shadow-none focus-visible:ring-0"
          />
          <button
            type="submit"
            disabled={
              sending ||
              uploading ||
              (!draft.trim() && attachments.length === 0)
            }
            aria-label="Send"
            className="press-scale flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-primary text-white transition-all duration-150 hover:brightness-110 disabled:opacity-40"
          >
            <ArrowUp className="h-5 w-5" />
          </button>
        </div>
      </form>
    </div>
  );
};

interface IMessageBubbleProps {
  message: IChatMessage;
  showName?: boolean;
}

const MessageBubble = ({ message, showName }: IMessageBubbleProps) => {
  if (message.role === "handoff") {
    return (
      <p className="animate-fade-in px-4 text-center text-xs text-muted-foreground">
        <span className="font-medium text-foreground/70">Handoff</span>
        <span className="mx-1.5">·</span>
        {message.content}
      </p>
    );
  }
  if (message.role === "user") {
    return (
      <div className="animate-bubble-user max-w-[85%] self-end rounded-[1.4rem] rounded-br-lg bg-primary px-4 py-2.5 md:max-w-[75%]">
        <p className="whitespace-pre-wrap text-[15px] leading-relaxed text-white">
          {message.content}
        </p>
      </div>
    );
  }
  if (message.role === "system") {
    return (
      <p className="animate-fade-in px-4 text-center text-xs text-muted-foreground">
        {message.content}
      </p>
    );
  }
  return (
    <div className="animate-bubble-bot min-w-0 max-w-[92%] self-start rounded-[1.4rem] rounded-bl-lg bg-card px-4 py-3 md:max-w-[85%]">
      {showName ? (
        <h3 className="mb-1 text-xs font-semibold text-muted-foreground">
          {message.bot_name ?? "Assistant"}
        </h3>
      ) : null}
      <ResearchMessageBody markdown={message.content} />
    </div>
  );
};

export default ChatPage;
