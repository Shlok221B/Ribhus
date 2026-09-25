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
  Home,
  ListTodo,
  Menu,
  Package,
  Plug,
  Radio,
  Settings,
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

interface INavItem {
  path: string;
  label: string;
  icon: typeof Home;
}

const NAV: INavItem[] = [
  { path: "/", label: "Home", icon: Home },
  { path: "/tasks", label: "Tasks", icon: ListTodo },
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

  return (
    <div className="flex h-full min-h-0 bg-background text-foreground">
      {sidebarOpen ? (
        <button
          type="button"
          aria-label="Close sidebar"
          className="fixed inset-0 z-30 bg-background/80 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      ) : null}

      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-border bg-card transition-transform md:static md:translate-x-0",
          sidebarOpen ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex items-center justify-between border-b border-border px-4 py-4">
          <div className="flex min-w-0 items-center gap-3">
            {/* <img
              src="/ribhus-2.png"
              alt=""
              width={40}
              height={40}
              className="h-10 w-10 shrink-0 rounded-md object-cover"
            /> */}
            <div className="min-w-0">
              <div className="font-mono text-xs tracking-[0.2em] text-primary">
                RIBHUS
              </div>
              <div className="mt-1 text-sm text-muted-foreground">Dashboard</div>
            </div>
          </div>
          <button
            type="button"
            className="rounded border border-border p-1 text-muted-foreground md:hidden"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close menu"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <nav className="flex-1 space-y-0.5 overflow-y-auto p-2">
          {NAV.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.path}
                to={item.path}
                end={item.path === "/"}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2 rounded px-3 py-2 font-mono text-xs uppercase tracking-wide transition-colors",
                    isActive
                      ? "bg-accent text-primary"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground",
                  )
                }
              >
                <Icon className="h-3.5 w-3.5 shrink-0" />
                {item.label}
              </NavLink>
            );
          })}
        </nav>

        <div className="border-t border-border px-4 py-3 font-mono text-[10px] leading-relaxed text-muted-foreground">
          <div>v{info?.version ?? "…"}</div>
          <div className="mt-1 truncate" title={info?.ribhus_dir}>
            {info?.ribhus_dir ?? ".ribhus"}
          </div>
          <div className="mt-2 text-muted-foreground/80">
            Agents that get things done.
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-border bg-card px-4 py-3 md:px-6">
          <button
            type="button"
            className="rounded border border-border p-1.5 text-muted-foreground md:hidden"
            onClick={() => setSidebarOpen(true)}
            aria-label="Open menu"
          >
            <Menu className="h-4 w-4" />
          </button>
          <h1 className="font-mono text-sm uppercase tracking-wider text-foreground">
            {NAV.find((n) =>
              n.path === "/"
                ? location.pathname === "/"
                : location.pathname.startsWith(n.path),
            )?.label ?? "Ribhus"}
          </h1>
        </header>

        <main className="min-h-0 flex-1 overflow-y-auto p-4 md:p-6">
          <Suspense
            fallback={
              <div className="font-mono text-sm text-muted-foreground">
                Loading…
              </div>
            }
          >
            <Routes>
              <Route path="/" element={<HomePage />} />
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
    </div>
  );
};

export default App;
