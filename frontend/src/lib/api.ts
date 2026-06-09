// Tiny typed client for the Pioneer FastAPI backend.
// Holds JWT in localStorage; dev-logs in once if missing.

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8001";
const DEV_EMAIL =
  process.env.NEXT_PUBLIC_DEV_EMAIL ?? "meetp0006@gmail.com";

const TOKEN_KEY = "pioneer.jwt";

// ---------- Types ----------

export type Workspace = {
  id: string;
  name: string;
  plan: string;
  created_at: string;
};

export type Usage = {
  period: string;
  tokens_used: number;
};

export type Connector = {
  id: string;
  workspace_id: string;
  provider: string;
  status: string;
  account_label: string | null;
  last_synced_at: string | null;
  created_at: string;
};

export type Agent = {
  id: string;
  workspace_id: string;
  provider: string;
  status: string;
};

export type Automation = {
  id: string;
  workspace_id: string;
  type: string;
  enabled: boolean;
};

export type Memory = {
  id: string;
  workspace_id: string;
  author_user_id: string | null;
  title: string;
  body: string;
  source: string;
  created_at: string;
};

export type SearchHit = {
  kind: "memory" | "document";
  score: number;
  memory: Memory | null;
  document_id: string | null;
  document_title: string | null;
  document_url: string | null;
  document_provider: string | null;
  chunk_index: number | null;
  chunk_text: string | null;
};

export type ChatResponse = {
  answer: string;
  hits: SearchHit[];
};

export type OAuthStart = {
  authorize_url: string;
  state: string;
};

export type SyncEnqueued = {
  job_id: string;
};

// ---------- Phase 3: access control + audit ----------

export type Grant = {
  principal_type: "user" | "agent";
  principal_id: string;
  sensitivity_max: number;       // -1=none, 0=public, 1=internal, 2=restricted
  collections: string[];          // ["*"] = wildcard
  actions: string[];              // ["read", "write"]
};

export type AgentKeyRow = {
  id: string;
  name: string;
  key_prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

export type AgentKeyCreated = AgentKeyRow & { plaintext: string };

export type AuditEntry = {
  id: string;
  seq: number;
  principal_type: string;
  principal_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  decision: string;
  scope: Record<string, unknown>;
  created_at: string;
};

export type AuditVerify = {
  ok: boolean;
  total: number;
  broken_at_seq: number | null;
  head_hash: string;
};

// ---------- Phase 4 ----------

export type ChatSource = {
  cite_id: string;
  kind: "memory" | "document";
  id: string;
  title: string;
  url: string | null;
  collection: string;
  sensitivity: string;
};

export type StreamUsage = {
  input_tokens: number;
  output_tokens: number;
  provider: string;
  model: string;
};

export type Draft = {
  id: string;
  workspace_id: string;
  automation_id: string;
  channel: string;
  thread_ref: string | null;
  recipient: string | null;
  incoming_excerpt: string;
  draft_body: string;
  status: "pending" | "edited" | "dismissed";
  created_at: string;
  updated_at: string;
};

export type AutomationRunRow = {
  id: string;
  status: string;
  inbound_seen: number;
  drafts_created: number;
  tokens_in: number;
  tokens_out: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
};

export type SyncStatus = {
  connector_id: string;
  connector_status: string;
  last_synced_at: string | null;
  run_id: string | null;
  run_status: string | null;
  docs_seen: number;
  docs_ingested: number;
  chunks_written: number;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
};

// ---------- Token mgmt ----------

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

function setToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
}

async function devLogin(email: string = DEV_EMAIL): Promise<string> {
  const res = await fetch(`${API_BASE}/auth/dev-login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`dev-login failed: ${res.status} ${txt}`);
  }
  const data = (await res.json()) as { access_token: string };
  setToken(data.access_token);
  return data.access_token;
}

export async function ensureToken(): Promise<string> {
  const existing = getToken();
  if (existing) return existing;
  return await devLogin();
}

// ---------- HTTP ----------

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
): Promise<T> {
  const token = await ensureToken();
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      authorization: `bearer ${token}`,
      ...(body !== undefined ? { "content-type": "application/json" } : {}),
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    // Token rotted or revoked — clear and retry once.
    clearToken();
    const fresh = await ensureToken();
    const res2 = await fetch(`${API_BASE}${path}`, {
      method,
      headers: {
        authorization: `bearer ${fresh}`,
        ...(body !== undefined ? { "content-type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!res2.ok) throw new Error(`${method} ${path} → ${res2.status}`);
    return (await res2.json()) as T;
  }
  if (!res.ok) {
    const txt = await res.text();
    throw new Error(`${method} ${path} → ${res.status} ${txt}`);
  }
  if (res.status === 204) return undefined as unknown as T;
  return (await res.json()) as T;
}

// ---------- API surface ----------

export const api = {
  health: () => fetch(`${API_BASE}/health`).then((r) => r.json()),

  workspace: {
    current: () => request<Workspace>("GET", "/workspaces/current"),
    usage: () => request<Usage>("GET", "/workspaces/current/usage"),
  },

  connectors: {
    list: () => request<Connector[]>("GET", "/connectors"),
    connect: (provider: string) =>
      request<Connector>("POST", `/connectors/${provider}/connect`),
    oauthStart: (provider: string) =>
      request<OAuthStart>("GET", `/connectors/${provider}/oauth/start`),
    sync: (connectorId: string) =>
      request<SyncEnqueued>("POST", `/connectors/${connectorId}/sync`),
    status: (connectorId: string) =>
      request<SyncStatus>("GET", `/connectors/${connectorId}/status`),
  },

  agents: {
    list: () => request<Agent[]>("GET", "/agents"),
    getAccess: (agentId: string) =>
      request<Grant | null>("GET", `/agents/${agentId}/access`),
    setAccess: (agentId: string, grant: Omit<Grant, "principal_type" | "principal_id">) =>
      request<Grant>("PUT", `/agents/${agentId}/access`, grant),
    listKeys: (agentId: string) =>
      request<AgentKeyRow[]>("GET", `/agents/${agentId}/keys`),
    createKey: (agentId: string, name: string) =>
      request<AgentKeyCreated>("POST", `/agents/${agentId}/keys`, { name }),
    revokeKey: (agentId: string, keyId: string) =>
      request<void>("DELETE", `/agents/${agentId}/keys/${keyId}`),
  },

  audit: {
    list: (limit = 50, beforeSeq?: number) => {
      const q = new URLSearchParams({ limit: String(limit) });
      if (beforeSeq !== undefined) q.set("before_seq", String(beforeSeq));
      return request<AuditEntry[]>("GET", `/audit?${q}`);
    },
    verify: () => request<AuditVerify>("GET", "/audit/verify"),
  },

  automations: {
    list: () => request<Automation[]>("GET", "/automations"),
    toggle: (id: string, enabled: boolean) =>
      request<Automation>("PATCH", `/automations/${id}`, { enabled }),
  },

  memories: {
    list: () => request<Memory[]>("GET", "/memories"),
    create: (title: string, body: string, source = "manual") =>
      request<Memory>("POST", "/memories", { title, body, source }),
  },

  chat: {
    ask: (query: string, top_k = 5) =>
      request<ChatResponse>("POST", "/chat", { query, top_k }),

    /** Stream a grounded chat reply via SSE. Calls `onEvent` for every
     * server-sent event. Resolves when the stream closes. */
    stream: async (
      query: string,
      handlers: {
        onSources?: (s: ChatSource[]) => void;
        onDelta?: (text: string) => void;
        onUsage?: (u: StreamUsage) => void;
        onDone?: (cited: string[]) => void;
        onError?: (err: string) => void;
      },
      top_k = 5,
      signal?: AbortSignal,
    ) => {
      const token = await ensureToken();
      const res = await fetch(`${API_BASE}/chat/stream`, {
        method: "POST",
        headers: {
          authorization: `bearer ${token}`,
          "content-type": "application/json",
        },
        body: JSON.stringify({ query, top_k }),
        signal,
      });
      if (!res.ok || !res.body) {
        handlers.onError?.(`stream HTTP ${res.status}`);
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        // SSE frames are separated by blank lines.
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const frame = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          let event = "message";
          let data = "";
          for (const line of frame.split("\n")) {
            if (line.startsWith("event:")) event = line.slice(6).trim();
            else if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (!data) continue;
          try {
            const parsed = JSON.parse(data);
            if (event === "sources") handlers.onSources?.(parsed as ChatSource[]);
            else if (event === "delta") handlers.onDelta?.((parsed as { text: string }).text);
            else if (event === "usage") handlers.onUsage?.(parsed as StreamUsage);
            else if (event === "done") handlers.onDone?.((parsed as { cited: string[] }).cited);
          } catch {
            // ignore unparseable frames
          }
        }
      }
    },
  },

  drafts: {
    list: (status?: string) =>
      request<Draft[]>(
        "GET",
        status ? `/drafts?status=${encodeURIComponent(status)}` : "/drafts",
      ),
    patch: (id: string, body: { draft_body?: string; status?: string }) =>
      request<Draft>("PATCH", `/drafts/${id}`, body),
  },

  automationsRun: {
    enqueue: (id: string) =>
      request<{ job_id: string }>("POST", `/automations/${id}/run`),
    runs: (id: string) =>
      request<AutomationRunRow[]>("GET", `/automations/${id}/runs?limit=3`),
  },
};
