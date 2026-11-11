import {
  Suspense,
  lazy,
  useCallback,
  useEffect,
  useRef,
  useState,
  type MouseEvent,
} from "react";
import { createPortal } from "react-dom";
import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router";
import {
  Brain,
  Ellipsis,
  Home,
  Menu,
  Plus,
  Plug,
  Radio,
  Settings,
  Sparkles,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { BotAvatar } from "@/components/ui";
import { api, type IBot, type IChat, type IConfigSafe } from "@/lib/api";

interface IBotMenuPos {
  top: number;
  left: number;
}

const HomePage = lazy(() => import("@/pages/HomePage"));
const TasksPage = lazy(() => import("@/pages/TasksPage"));
const TaskDetailPage = lazy(() => import("@/pages/TaskDetailPage"));
const SkillsPage = lazy(() => import("@/pages/SkillsPage"));
const MemoryPage = lazy(() => import("@/pages/MemoryPage"));
const ChannelsPage = lazy(() => import("@/pages/ChannelsPage"));
const McpPage = lazy(() => import("@/pages/McpPage"));
const ConfigPage = lazy(() => import("@/pages/ConfigPage"));
const ChatPage = lazy(() => import("@/pages/ChatPage"));
const NewBotPage = lazy(() => import("@/pages/NewBotPage"));
const NewGroupPage = lazy(() => import("@/pages/NewGroupPage"));

interface INavItem {
  path: string;
  label: string;
  icon: typeof Home;
}

const NAV: INavItem[] = [
  { path: "/", label: "Home", icon: Home },
  { path: "/memory", label: "Memory", icon: Brain },
  { path: "/channels", label: "Channels", icon: Radio },
  { path: "/mcp", label: "MCP", icon: Plug },
  { path: "/config", label: "Config", icon: Settings },
];

const App = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [info, setInfo] = useState<IConfigSafe | null>(null);
  const [bots, setBots] = useState<IBot[]>([]);
  const [chats, setChats] = useState<IChat[]>([]);
  const [botMenuId, setBotMenuId] = useState<string | null>(null);
  const [botMenuPos, setBotMenuPos] = useState<IBotMenuPos | null>(null);
  const [deletingBotId, setDeletingBotId] = useState<string | null>(null);
  const botMenuRef = useRef<HTMLDivElement | null>(null);

  const refreshRoster = useCallback(async () => {
    try {
      const [roster, rows] = await Promise.all([
        api.listBots(),
        api.listChats(),
      ]);
      setBots(roster);
      setChats(rows);
    } catch {
      /* ignore */
    }
  }, []);

  const groups = chats.filter((c) => c.kind === "group");

  const previewFor = (chat?: IChat): string => {
    const last = chat?.messages?.[chat.messages.length - 1];
    if (!last?.content) return "";
    const text = last.content.replace(/\s+/g, " ").trim();
    return last.role === "user" ? `You: ${text}` : text;
  };

  const directChatFor = (botId: string): IChat | undefined =>
    chats.find((c) => c.kind === "direct" && c.bot_ids?.[0] === botId);

  const closeBotMenu = () => {
    setBotMenuId(null);
    setBotMenuPos(null);
  };

  const handleOpenBotMenu = (
    event: MouseEvent<HTMLButtonElement>,
    botId: string,
  ) => {
    event.preventDefault();
    event.stopPropagation();
    if (botMenuId === botId) {
      closeBotMenu();
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    const width = 176;
    const left = Math.max(8, Math.min(rect.right - width, window.innerWidth - width - 8));
    setBotMenuPos({ top: rect.bottom + 6, left });
    setBotMenuId(botId);
  };

  const handleDeleteBot = async (bot: IBot) => {
    if (deletingBotId || bots.length <= 1) return;
    const ok = window.confirm(
      `Delete ${bot.name}? Direct chat and private memories for this bot will be removed.`,
    );
    if (!ok) {
      closeBotMenu();
      return;
    }
    closeBotMenu();
    setDeletingBotId(bot.id);
    try {
      await api.deleteBot(bot.id);
      const remaining = bots.filter((b) => b.id !== bot.id);
      setBots(remaining);
      setChats((rows) =>
        rows.filter(
          (c) =>
            !(c.kind === "direct" && c.bot_ids?.[0] === bot.id),
        ),
      );
      if (location.pathname === `/bots/${bot.id}`) {
        const next =
          remaining.find((b) => b.is_primary)?.id ?? remaining[0]?.id ?? null;
        void navigate(next ? `/bots/${next}` : "/", { replace: true });
      }
      await refreshRoster();
    } catch (err) {
      window.alert(
        err instanceof Error ? err.message : "Could not delete bot",
      );
    } finally {
      setDeletingBotId(null);
    }
  };

  useEffect(() => {
    void api
      .getConfig()
      .then(setInfo)
      .catch(() => setInfo(null));
  }, []);

  useEffect(() => {
    void refreshRoster();
    const timer = window.setInterval(() => void refreshRoster(), 4000);
    return () => window.clearInterval(timer);
  }, [refreshRoster, location.pathname]);

  useEffect(() => {
    setSidebarOpen(false);
    closeBotMenu();
  }, [location.pathname]);

  useEffect(() => {
    if (!botMenuId) return;
    const handlePointer = (event: globalThis.MouseEvent) => {
      const target = event.target as Node;
      if (botMenuRef.current?.contains(target)) return;
      closeBotMenu();
    };
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeBotMenu();
    };
    const handleRepositionClose = () => closeBotMenu();
    // Use click (not mousedown) so menu item clicks always register first.
    document.addEventListener("click", handlePointer);
    document.addEventListener("keydown", handleKey);
    window.addEventListener("resize", handleRepositionClose);
    window.addEventListener("scroll", handleRepositionClose, true);
    return () => {
      document.removeEventListener("click", handlePointer);
      document.removeEventListener("keydown", handleKey);
      window.removeEventListener("resize", handleRepositionClose);
      window.removeEventListener("scroll", handleRepositionClose, true);
    };
  }, [botMenuId]);

  const page = NAV.find((n) =>
    n.path === "/"
      ? location.pathname === "/"
      : location.pathname.startsWith(n.path),
  );

  const isChatRoute =
    /^\/(bots|chats)\/[^/]+$/.test(location.pathname) &&
    !location.pathname.endsWith("/new");

  const headerTitle = (() => {
    if (location.pathname.startsWith("/bots/new")) return "New bot";
    if (location.pathname.startsWith("/chats/new")) return "New group";
    if (location.pathname.startsWith("/bots/")) {
      const id = location.pathname.split("/")[2];
      return bots.find((b) => b.id === id)?.name ?? "Bot";
    }
    if (location.pathname.startsWith("/chats/")) {
      const id = location.pathname.split("/")[2];
      return groups.find((g) => g.id === id)?.title ?? "Group";
    }
    return page?.label ?? "Ribhus";
  })();

  return (
    <div className="surface-horizon flex h-full min-h-0 text-foreground">
      {sidebarOpen ? (
        <button
          type="button"
          aria-label="Close sidebar"
          className="fixed inset-0 z-30 bg-background/70 backdrop-blur-sm md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      ) : null}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-72 flex-col bg-background transition-transform md:static md:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between px-4 pb-2 pt-4">
          <NavLink
            to="/"
            className="press-scale flex h-9 w-9 items-center justify-center rounded-full bg-card text-muted-foreground transition-colors hover:text-foreground"
            aria-label="Home"
            title="Home"
          >
            <Sparkles className="h-4 w-4" />
          </NavLink>
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="press-scale flex h-9 w-9 items-center justify-center rounded-full bg-card text-muted-foreground transition-colors hover:text-foreground"
              aria-label="New group"
              title="New group"
              onClick={() => void navigate("/chats/new")}
            >
              <Users className="h-4 w-4" />
            </button>
            <button
              type="button"
              className="press-scale flex h-9 w-9 items-center justify-center rounded-full bg-card text-muted-foreground transition-colors hover:text-foreground"
              aria-label="New bot"
              title="New bot"
              onClick={() => void navigate("/bots/new")}
            >
              <Plus className="h-4 w-4" />
            </button>
            <button
              type="button"
              className="flex h-9 w-9 items-center justify-center rounded-full bg-card text-muted-foreground md:hidden"
              onClick={() => setSidebarOpen(false)}
              aria-label="Close menu"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        <div className="anim-stagger flex gap-4 overflow-x-auto px-4 py-3">
          {bots.map((bot) => (
            <NavLink
              key={bot.id}
              to={`/bots/${bot.id}`}
              className="press-scale flex w-14 shrink-0 flex-col items-center gap-1.5"
              title={bot.name}
            >
              <BotAvatar
                color={bot.color}
                size="lg"
                primary={bot.is_primary}
                live={bot.status !== "idle"}
              />
              <span className="w-full truncate text-center text-[11px] text-muted-foreground">
                {bot.name}
              </span>
            </NavLink>
          ))}
        </div>

        <nav className="anim-stagger flex-1 space-y-0.5 overflow-y-auto px-2 py-1">
          {bots.map((bot) => {
            const preview = previewFor(directChatFor(bot.id)) || bot.job;
            const menuOpen = botMenuId === bot.id;
            const deleting = deletingBotId === bot.id;
            return (
              <NavLink
                key={bot.id}
                to={`/bots/${bot.id}`}
                className={({ isActive }) =>
                  cn(
                    "group flex items-center gap-3 rounded-2xl px-3 py-2.5 transition-colors duration-150",
                    isActive ? "bg-card" : "hover:bg-card/60",
                  )
                }
              >
                <BotAvatar
                  color={bot.color}
                  size="md"
                  live={bot.status !== "idle"}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-semibold text-foreground">
                    {bot.name}
                    {bot.is_primary ? (
                      <span className="ml-1 text-[10px] text-warning">★</span>
                    ) : null}
                  </span>
                  <span
                    className={cn(
                      "block truncate text-xs",
                      bot.status !== "idle"
                        ? "text-shimmer"
                        : "text-muted-foreground",
                    )}
                  >
                    {bot.status !== "idle" ? bot.status : preview}
                  </span>
                </span>
                <button
                  type="button"
                  aria-label={`${bot.name} options`}
                  aria-haspopup="menu"
                  aria-expanded={menuOpen}
                  disabled={deletingBotId != null}
                  title="Bot options"
                  onClick={(event) => handleOpenBotMenu(event, bot.id)}
                  className={cn(
                    "press-scale flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:opacity-40",
                    (menuOpen || deleting) && "bg-accent text-foreground",
                  )}
                >
                  <Ellipsis className="h-4 w-4" />
                </button>
              </NavLink>
            );
          })}
          {groups.map((g) => (
            <NavLink
              key={g.id}
              to={`/chats/${g.id}`}
              className={({ isActive }) =>
                cn(
                  "flex items-center gap-3 rounded-2xl px-3 py-2.5 transition-colors duration-150",
                  isActive ? "bg-card" : "hover:bg-card/60",
                )
              }
            >
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-secondary">
                <Users className="h-4 w-4 text-muted-foreground" />
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-foreground">
                  {g.title}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {previewFor(g) || "Group chat"}
                </span>
              </span>
            </NavLink>
          ))}
        </nav>

        <div className="flex items-center justify-around border-t border-border/40 px-2 py-1.5">
          {NAV.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === "/"}
                title={item.label}
                aria-label={item.label}
                className={({ isActive }) =>
                  cn(
                    "press-scale flex h-9 w-9 items-center justify-center rounded-full transition-colors duration-150",
                    isActive
                      ? "bg-card text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )
                }
              >
                <Icon className="h-4 w-4" />
              </NavLink>
            );
          })}
        </div>

        <div className="flex items-center gap-3 px-4 py-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-[image:var(--gradient-ember)] text-sm font-semibold text-white">
            R
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-sm font-medium text-foreground">
              Ribhus
            </div>
            <div className="truncate text-xs text-muted-foreground">
              v{info?.version ?? "…"} · local
            </div>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col bg-[#0e0e10] md:my-2 md:mr-2 md:rounded-2xl">
        <header
          className={cn(
            "flex items-center gap-3 px-4 py-3 md:px-8",
            isChatRoute && "md:hidden",
          )}
        >
          <button
            type="button"
            className="flex h-9 w-9 items-center justify-center rounded-full bg-card text-muted-foreground md:hidden"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open menu"
          >
            <Menu className="h-4 w-4" />
          </button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-medium text-foreground">
              {headerTitle}
            </h1>
          </div>
          {info?.model ? (
            <span className="hidden max-w-[40%] truncate rounded-full bg-card px-3 py-1 text-[11px] text-muted-foreground sm:inline">
              {info.model}
            </span>
          ) : null}
        </header>

        <main
          key={location.pathname}
          className="page-enter min-h-0 flex-1 overflow-y-auto p-4 md:p-8"
        >
          <Suspense
            fallback={
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <span className="text-shimmer">Loading…</span>
              </div>
            }
          >
            <Routes>
              <Route path="/" element={<HomePage />} />
              <Route path="/bots/new" element={<NewBotPage />} />
              <Route path="/bots/:id" element={<ChatPage mode="bot" />} />
              <Route path="/chats/new" element={<NewGroupPage />} />
              <Route path="/chats/:id" element={<ChatPage mode="chat" />} />
              <Route path="/tasks" element={<TasksPage />} />
              <Route path="/tasks/:id" element={<TaskDetailPage />} />
              <Route path="/skills" element={<SkillsPage />} />
              <Route path="/memory" element={<MemoryPage />} />
              <Route path="/channels" element={<ChannelsPage />} />
              <Route path="/mcp" element={<McpPage />} />
              <Route path="/config" element={<ConfigPage />} />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </main>
      </div>

      {botMenuId && botMenuPos
        ? createPortal(
            (() => {
              const menuBot = bots.find((b) => b.id === botMenuId);
              if (!menuBot) return null;
              const canDelete = bots.length > 1;
              const deleting = deletingBotId === menuBot.id;
              return (
                <div
                  ref={botMenuRef}
                  className="animate-scale-in fixed z-[80] w-44 rounded-xl border border-border bg-popover p-1 shadow-lg"
                  style={{ top: botMenuPos.top, left: botMenuPos.left }}
                  role="menu"
                >
                  <button
                    type="button"
                    role="menuitem"
                    disabled={!canDelete || deleting}
                    title={
                      canDelete
                        ? `Delete ${menuBot.name}`
                        : "Keep at least one bot"
                    }
                    className="press-scale flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm text-destructive transition-colors hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-40"
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      void handleDeleteBot(menuBot);
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5 shrink-0" />
                    {deleting ? "Deleting…" : "Delete bot"}
                  </button>
                </div>
              );
            })(),
            document.body,
          )
        : null}
    </div>
  );
};

export default App;
