import { Suspense, lazy, useEffect, useState } from "react";
import {
  NavLink,
  Navigate,
  Route,
  Routes,
  useLocation,
} from "react-router";
import {
  Brain,
  Briefcase,
  Home,
  ListTodo,
  Menu,
  Package,
  Plug,
  Radio,
  Settings,
  Sparkles,
  X,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { api, type IConfigSafe } from "@/lib/api";

const HomePage = lazy(() => import("@/pages/HomePage"));
const TasksPage = lazy(() => import("@/pages/TasksPage"));
const TaskDetailPage = lazy(() => import("@/pages/TaskDetailPage"));
const SkillsPage = lazy(() => import("@/pages/SkillsPage"));
const MemoryPage = lazy(() => import("@/pages/MemoryPage"));
const ChannelsPage = lazy(() => import("@/pages/ChannelsPage"));
const McpPage = lazy(() => import("@/pages/McpPage"));
const ConfigPage = lazy(() => import("@/pages/ConfigPage"));
const JobHuntPage = lazy(() => import("@/pages/JobHuntPage"));

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

const App = () => {
  const location = useLocation();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [info, setInfo] = useState<IConfigSafe | null>(null);

  useEffect(() => {
    void api
      .getConfig()
      .then(setInfo)
      .catch(() => setInfo(null));
  }, []);

  useEffect(() => {
    setSidebarOpen(false);
  }, [location.pathname]);

  const page = NAV.find((n) =>
    n.path === "/"
      ? location.pathname === "/"
      : location.pathname.startsWith(n.path),
  );

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

        <nav className="flex-1 space-y-1 overflow-y-auto px-3 pb-3">
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
            Agents that get things done.
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
              {page?.label ?? "Ribhus"}
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
