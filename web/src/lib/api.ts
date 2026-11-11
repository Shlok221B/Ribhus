export interface ITaskEvent {
  event_id?: string;
  seq?: number;
  ts: string;
  event_type?: string;
  payload?: Record<string, unknown>;
  /** Legacy alias of event_type */
  event: string;
  /** Legacy alias of payload */
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

export interface ITaskTurn {
  role: "user" | "assistant";
  content: string;
}

export interface ITask {
  id: string;
  prompt: string;
  turns?: ITaskTurn[];
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
  chat_id?: string | null;
  bot_id?: string | null;
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

export type BotStatus = "idle" | "working" | "waiting";

export interface IBot {
  id: string;
  name: string;
  label: string;
  color: string;
  job: string;
  is_primary: boolean;
  status: BotStatus;
  created_at: string;
  updated_at: string;
  chat_id?: string;
}

export interface IChatMessage {
  id: string;
  role: "user" | "assistant" | "system" | "handoff" | "bot";
  content: string;
  created_at: string;
  bot_id?: string | null;
  bot_name?: string | null;
  task_id?: string | null;
  handoff?: Record<string, unknown> | null;
  mention_bot_ids?: string[];
}

export interface IChat {
  id: string;
  kind: "direct" | "group";
  title: string;
  bot_ids: string[];
  created_at: string;
  updated_at: string;
  messages: IChatMessage[];
  active_task_id?: string | null;
  bots?: IBot[];
}

export interface IChatUpload {
  name: string;
  path: string;
  size: number;
  content_type: string;
  extracted_text?: string | null;
  extract_error?: string | null;
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
  listTaskEvents: (id: string, afterSeq = 0) =>
    request<{
      task_id: string;
      events: ITaskEvent[];
      next_seq: number;
    }>(`/api/tasks/${id}/events?after_seq=${afterSeq}`),
  createTask: (prompt: string, botId?: string) =>
    request<ITask>("/api/tasks", {
      method: "POST",
      body: JSON.stringify({ prompt, bot_id: botId ?? null }),
    }),
  followUp: (taskId: string, prompt: string) =>
    request<ITask>(`/api/tasks/${taskId}/follow-up`, {
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

  listBots: () => request<IBot[]>("/api/bots"),
  getBot: (id: string) => request<IBot>(`/api/bots/${id}`),
  createBot: (body: {
    name: string;
    job?: string;
    label?: string;
    color?: string;
    make_primary?: boolean;
  }) =>
    request<IBot>("/api/bots", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateBot: (
    id: string,
    body: Partial<{
      name: string;
      job: string;
      label: string;
      color: string;
      is_primary: boolean;
    }>,
  ) =>
    request<IBot>(`/api/bots/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  setPrimaryBot: (id: string) =>
    request<IBot>(`/api/bots/${id}/primary`, { method: "POST" }),
  deleteBot: (id: string) =>
    request<{ ok: boolean }>(`/api/bots/${id}`, { method: "DELETE" }),

  listChats: () => request<IChat[]>("/api/chats"),
  getChat: (id: string) => request<IChat>(`/api/chats/${id}`),
  getDirectChat: (botId: string) =>
    request<IChat>(`/api/chats/by-bot/${botId}`),
  createGroup: (botIds: string[], title?: string) =>
    request<IChat>("/api/chats/group", {
      method: "POST",
      body: JSON.stringify({ bot_ids: botIds, title: title ?? "" }),
    }),
  updateChat: (id: string, body: { title?: string; bot_ids?: string[] }) =>
    request<IChat>(`/api/chats/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteChat: (id: string) =>
    request<{ ok: boolean }>(`/api/chats/${id}`, { method: "DELETE" }),
  postChatMessage: (chatId: string, content: string) =>
    request<{ chat: IChat; task?: ITask }>(`/api/chats/${chatId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  uploadChatFile: async (chatId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    const headers = new Headers();
    const token = sessionToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    headers.set("Accept", "application/json");
    // Do not set Content-Type — browser must add multipart boundary.
    const res = await fetch(`/api/chats/${chatId}/uploads`, {
      method: "POST",
      headers,
      body,
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const payload = (await res.json()) as { detail?: string };
        if (payload?.detail) detail = payload.detail;
      } catch {
        /* ignore */
      }
      throw new Error(detail || `HTTP ${res.status}`);
    }
    return (await res.json()) as IChatUpload;
  },

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

  listResearchRuns: (limit = 20) =>
    request<Record<string, unknown>[]>(`/api/research/runs?limit=${limit}`),
  getResearchRun: (runId: string) =>
    request<Record<string, unknown>>(`/api/research/runs/${encodeURIComponent(runId)}`),
  getResearchByTask: (taskId: string) =>
    request<Record<string, unknown>>(
      `/api/research/by-task/${encodeURIComponent(taskId)}`,
    ),
};
