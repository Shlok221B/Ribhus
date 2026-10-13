export interface ITaskEvent {
  ts: string;
  event: string;
  data: Record<string, unknown>;
}

export interface IPendingApproval {
  id: string;
  tool: string;
  risk: string;
  arguments: Record<string, unknown>;
  created_at: string;
}

export interface IMapsPlace {
  name: string;
  url: string;
}

export interface ITask {
  id: string;
  prompt: string;
  status:
    | "queued"
    | "running"
    | "awaiting_approval"
    | "completed"
    | "failed"
    | "cancelled";
  created_at: string;
  updated_at: string;
  result?: string | null;
  error?: string | null;
  events: ITaskEvent[];
  pending_approval?: IPendingApproval | null;
  skills?: string[];
  maps_places?: IMapsPlace[];
}

export interface ISkillInfo {
  name: string;
  version: string;
  description: string;
  triggers: string[];
  installed: boolean;
  path: string;
}

export interface IMemoryRecord {
  id: string;
  kind: string;
  key: string | null;
  content: string;
  disabled: boolean;
  created_at: string;
  updated_at: string;
}

export interface IChannelStatus {
  channel: string;
  enabled: boolean;
  killed: boolean;
  headed: boolean;
  profile_dir: string;
  kill_path: string;
  note: string;
}

export interface IMcpServer {
  name: string;
  enabled: boolean;
  connected: boolean;
  command: string;
  risk: string;
  tools: string[];
}

export interface IConfigSafe {
  model: string;
  base_url: string;
  api_key_set: boolean;
  api_key_masked: string;
  auto_approve: boolean;
  approve_at: string;
  memory_enabled: boolean;
  mcp_enabled: boolean;
  whatsapp_enabled: boolean;
  email_enabled: boolean;
  browser_headed: boolean;
  workspace: string;
  ribhus_dir: string;
  version: string;
}

function sessionToken(): string {
  return window.__RIBHUS_SESSION_TOKEN__ ?? "";
}

async function request<T>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  const token = sessionToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { ...init, headers });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body?.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail || `HTTP ${res.status}`);
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return (await res.json()) as T;
}

export const api = {
  health: () => request<{ ok: boolean; version: string }>("/api/health"),

  listTasks: () => request<ITask[]>("/api/tasks"),
  getTask: (id: string) => request<ITask>(`/api/tasks/${id}`),
  createTask: (prompt: string) =>
    request<ITask>("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ prompt }),
    }),
  resolveApproval: (
    taskId: string,
    body: { decision: "approve" | "deny" | "edit"; edited_text?: string },
  ) =>
    request<ITask>(`/api/tasks/${taskId}/approvals`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  listSkills: () => request<ISkillInfo[]>("/api/skills"),
  installSkill: (source: string) =>
    request<ISkillInfo>("/api/skills/install", {
      method: "POST",
      body: JSON.stringify({ source }),
    }),
  removeSkill: (name: string) =>
    request<{ ok: boolean }>(`/api/skills/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),

  listMemory: (q?: string) =>
    request<IMemoryRecord[]>(
      q ? `/api/memory?q=${encodeURIComponent(q)}` : "/api/memory",
    ),
  addMemory: (content: string, key?: string) =>
    request<IMemoryRecord>("/api/memory", {
      method: "POST",
      body: JSON.stringify({ content, key: key || null }),
    }),
  forgetMemory: (target: string) =>
    request<{ forgotten: string }>(
      `/api/memory/${encodeURIComponent(target)}`,
      { method: "DELETE" },
    ),

  listChannels: () => request<IChannelStatus[]>("/api/channels"),
  channelAction: (channel: "whatsapp" | "email", action: "kill" | "resume") =>
    request<IChannelStatus>(`/api/channels/${channel}/${action}`, {
      method: "POST",
    }),

  listMcp: () =>
    request<{ servers: IMcpServer[]; errors: string[]; config_path: string }>(
      "/api/mcp",
    ),
  testMcp: (server: string) =>
    request<{ ok: boolean; result: string }>(`/api/mcp/${server}/test`, {
      method: "POST",
    }),

  getConfig: () => request<IConfigSafe>("/api/config"),
  patchConfig: (patch: Record<string, unknown>) =>
    request<IConfigSafe>("/api/config", {
      method: "PATCH",
      body: JSON.stringify(patch),
    }),
};
