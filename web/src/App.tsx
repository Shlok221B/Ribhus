import { Suspense, lazy, useCallback, useEffect, useState } from "react";
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
  Briefcase,
  Home,
  ListTodo,
  Menu,
  Package,
  Plus,
  Plug,
  Radio,
  Settings,
  Sparkles,
  Users,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api, type IBot, type IChat, type IConfigSafe } from "@/lib/api";

const HomePage = lazy(() => import("@/pages/HomePage"));
const TasksPage = lazy(() => import("@/pages/TasksPage"));
const TaskDetailPage = lazy(() => import("@/pages/TaskDetailPage"));
const SkillsPage = lazy(() => import("@/pages/SkillsPage"));
const MemoryPage = lazy(() => import("@/pages/MemoryPage"));
const ChannelsPage = lazy(() => import("@/pages/ChannelsPage"));
const McpPage = lazy(() => import("@/pages/McpPage"));
const ConfigPage = lazy(() => import("@/pages/ConfigPage"));
const JobHuntPage = lazy(() => import("@/pages/JobHuntPage"));
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
  { path: "/tasks", label: "Tasks", icon: ListTodo },
  { path: "/jobs", label: "Job hunt", icon: Briefcase },
  { path: "/skills", label: "Skills", icon: Package },
  { path: "/memory", label: "Memory", icon: Brain },
  { path: "/channels", label: "Channels", icon: Radio },
  { path: "/mcp", label: "MCP", icon: Plug },
  { path: "/config", label: "Config", icon: Settings },
];

const COLOR_DOT: Record<string, string> = {
  copper: "bg-[color:var(--palette-copper)]",
  blue: "bg-[color:var(--palette-blue)]",
  gold: "bg-[color:var(--palette-gold)]",
  verdigris: "bg-[color:var(--palette-verdigris)]",
  rose: "bg-[color:var(--palette-rose)]",
  info: "bg-[color:var(--palette-blue)]",
};

const App = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [info, setInfo] = useState<IConfigSafe | null>(null);
  const [bots, setBots] = useState<IBot[]>([]);
  const [groups, setGroups] = useState<IChat[]>([]);

  const refreshRoster = useCallback(async () => {
    try {
      const [roster, chats] = await Promise.all([
        api.listBots(),
        api.listChats(),
      ]);
      setBots(roster);
      setGroups(chats.filter((c) => c.kind === "group"));
    } catch {
      /* ignore */
    }
  }, []);

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
  }, [location.pathname]);

  const page = NAV.find((n) =>
    n.path === "/"
      ? location.pathname === "/"
      : location.pathname.startsWith(n.path),
  );

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
          "fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-border/70 bg-card/80 backdrop-blur-xl transition-transform md:static md:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between px-5 py-5">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/15 ring-1 ring-primary/25">
              <Sparkles className="h-5 w-5 text-primary" aria-hidden />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold tracking-tight text-foreground">
                Ribhus
              </div>
              <div className="text-xs text-muted-foreground">Local dashboard</div>
            </div>
          </div>
          <button
            type="button"
            className="rounded-lg border border-border p-1.5 text-muted-foreground md:hidden"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close menu"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="px-3 pb-2">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Bots
            </span>
            <div className="flex gap-1">
              <button
                type="button"
                className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                aria-label="New bot"
                title="New bot"
                onClick={() => void navigate("/bots/new")}
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
              <button
                type="button"
                className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                aria-label="New group"
                title="New group"
                onClick={() => void navigate("/chats/new")}
              >
                <Users className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
          <nav className="max-h-48 space-y-0.5 overflow-y-auto sm:max-h-64">
            {bots.map((bot) => (
              <NavLink
                key={bot.id}
                to={`/bots/${bot.id}`}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition-colors",
                    isActive
                      ? "bg-primary/12 text-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground",
                  )
                }
              >
                <span
                  className={cn(
                    "relative h-2.5 w-2.5 shrink-0 rounded-full",
                    COLOR_DOT[bot.color] ?? COLOR_DOT.copper,
                  )}
                >
                  {bot.status !== "idle" ? (
                    <span className="absolute -right-0.5 -top-0.5 h-1.5 w-1.5 rounded-full bg-info ring-1 ring-card" />
                  ) : null}
                </span>
                <span className="min-w-0 flex-1 truncate">
                  {bot.name}
                  {bot.is_primary ? (
                    <span className="ml-1 text-[10px] text-primary">★</span>
                  ) : null}
                </span>
              </NavLink>
            ))}
            {groups.map((g) => (
              <NavLink
                key={g.id}
                to={`/chats/${g.id}`}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition-colors",
                    isActive
                      ? "bg-primary/12 text-foreground"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground",
                  )
                }
              >
                <Users className="h-3.5 w-3.5 shrink-0 opacity-70" />
                <span className="min-w-0 flex-1 truncate">{g.title}</span>
              </NavLink>
            ))}
          </nav>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto border-t border-border/50 px-3 pb-3 pt-3">
          {NAV.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === "/"}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors",
                    isActive
                      ? "bg-primary/12 text-foreground shadow-[inset_0_0_0_1px_color-mix(in_oklab,var(--primary)_28%,transparent)]"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground",
                  )
                }
              >
                <Icon className="h-4 w-4 shrink-0 opacity-80" />
                {item.label}
              </NavLink>
            );
          })}
        </nav>

        <div className="mx-3 mb-4 rounded-xl border border-border/70 bg-background/40 px-4 py-3 text-xs leading-relaxed text-muted-foreground">
          <div className="font-medium text-foreground/80">
            v{info?.version ?? "…"}
          </div>
          <div className="mt-1 truncate" title={info?.ribhus_dir}>
            {info?.ribhus_dir ?? ".ribhus"}
          </div>
          <div className="mt-2 text-muted-foreground/80">
            Bots that get things done.
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-border/60 bg-card/40 px-4 py-3 backdrop-blur-md md:px-8">
          <button
            type="button"
            className="rounded-lg border border-border p-1.5 text-muted-foreground md:hidden"
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
            <span className="hidden max-w-[40%] truncate rounded-full border border-border/70 bg-background/50 px-2.5 py-1 text-[11px] text-muted-foreground sm:inline">
              {info.model}
            </span>
          ) : null}
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto p-4 md:p-8">
          <Suspense
            fallback={
              <div className="text-sm text-muted-foreground">Loading…</div>
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
              <Route path="/jobs" element={<JobHuntPage />} />
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
    </div>
  );
};

export default App;
