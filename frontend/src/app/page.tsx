"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ChevronLeft, ChevronRight, MessageSquare, Plug, Bot, Zap, Brain,
  VenetianMask, Check, ChevronDown, ChevronUp, Plus, History, Send,
  Bold, Italic, Strikethrough, Code, Github, X, HelpCircle, LogOut,
  MoreVertical, ArrowUp, Inbox, Copy, Loader2, ShieldCheck, Key,
} from "lucide-react";

import {
  api,
  type Agent as AgentRow,
  type AgentKeyCreated,
  type AgentKeyRow,
  type AuditEntry,
  type AuditVerify,
  type Automation as AutomationRow,
  type ChatSource,
  type Connector as ConnectorRow,
  type Draft,
  type Grant,
  type Memory as MemoryRow,
  type StreamUsage,
  type SyncStatus,
  type Usage as UsageRow,
  type Workspace as WorkspaceRow,
} from "@/lib/api";

const SENS_LABELS = ["public", "internal", "restricted"] as const;
const KNOWN_COLLECTIONS = ["manual", "notion", "gmail", "slack-dm"] as const;

// ---------- Theme tokens (preserve prototype palette) ----------

const ACCENT = "#FF4A1C";
const ACCENT_SOFT = "rgba(255,74,28,0.13)";
const ACCENT_BORDER = "rgba(255,74,28,0.32)";
const PANEL = "#161413";
const CARD = "#161514";
const LINE = "rgba(255,255,255,0.07)";

// ---------- Small reusable bits ----------

type ToggleProps = { on: boolean; onClick: () => void; disabled?: boolean };
function Toggle({ on, onClick, disabled }: ToggleProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="relative h-7 w-12 shrink-0 rounded-full transition-colors duration-200 disabled:opacity-50"
      style={{ background: on ? ACCENT : "rgba(255,255,255,0.13)" }}
    >
      <span
        className="absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-all duration-200"
        style={{ left: on ? "26px" : "4px" }}
      />
    </button>
  );
}

function Connected() {
  return (
    <span className="flex items-center gap-1.5 text-sm font-medium" style={{ color: "#4ade80" }}>
      <Check size={16} /> Connected
    </span>
  );
}

type ConnectBtnProps = { label?: string; onClick?: () => void; busy?: boolean };
function ConnectBtn({ label = "Connect", onClick, busy }: ConnectBtnProps) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="flex items-center gap-2 rounded-xl px-5 py-2 text-sm font-medium text-white transition-colors disabled:opacity-60"
      style={{ background: "rgba(255,255,255,0.07)" }}
    >
      {busy && <Loader2 size={14} className="animate-spin" />} {label}
    </button>
  );
}

function Title({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-8">
      <h1 className="text-5xl font-bold tracking-tight text-white">{children}</h1>
      <div className="mt-3 h-1 w-12 rounded-full" style={{ background: ACCENT }} />
    </div>
  );
}

type TileProps = {
  bg?: string;
  color?: string;
  children?: React.ReactNode;
  icon?: React.ComponentType<{ size?: number }>;
};
function Tile({ bg = "#fff", color = "#000", children, icon: Icon }: TileProps) {
  return (
    <div
      className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-sm font-bold"
      style={{ background: bg, color }}
    >
      {Icon ? <Icon size={22} /> : children}
    </div>
  );
}

const BRAND = (
  <div className="flex items-center gap-0.5 text-3xl font-black" style={{ color: ACCENT }}>
    <span>⊢</span><span className="-ml-1">⊣</span>
  </div>
);

// ---------- Static provider/agent/automation metadata ----------

type ProviderMeta = {
  id: string;
  name: string;
  desc: string;
  bg: string;
  color: string;
  letter?: string;
  icon?: React.ComponentType<{ size?: number }>;
  /** When true, "Connect" kicks off a real OAuth redirect instead of the Phase-1 stub. */
  oauth?: boolean;
};

const CONNECTOR_META: ProviderMeta[] = [
  { id: "notion",  name: "Notion",          desc: "Pages and docs",         bg: "#fff",    color: "#000",    letter: "N", oauth: true },
  { id: "gmail",   name: "Gmail",           desc: "Inbox threads",          bg: "#fff",    color: "#ea4335", letter: "M", oauth: true },
  { id: "github",  name: "GitHub",          desc: "Markdown in repos",      bg: "#fff",    color: "#000",    icon: Github, oauth: true },
  { id: "gdrive",  name: "Google Drive",    desc: "Docs and sheets",        bg: "#fff",    color: "#1a73e8", letter: "▲" },
  { id: "gcal",    name: "Google Calendar", desc: "Meetings and events",    bg: "#1a73e8", color: "#fff",    letter: "31" },
  { id: "granola", name: "Granola",         desc: "Meeting notes",          bg: "#b9d44a", color: "#1a2c00", letter: "G" },
  { id: "slack",   name: "Slack",           desc: "Channel and DM history", bg: "#fff",    color: "#611f69", letter: "#" },
  { id: "linear",  name: "Linear",          desc: "Issues and projects",    bg: "#5e6ad2", color: "#fff",    letter: "L" },
];

const AGENT_META: Record<
  string,
  { name: string; desc: string; bg: string; letter?: string; icon?: React.ComponentType<{ size?: number }> }
> = {
  claude_code: { name: "Claude Code", desc: "Terminal & IDE sessions", bg: ACCENT,    letter: "▦" },
  cursor:      { name: "Cursor",      desc: "AI code editor",          bg: "#222",    letter: "◆" },
  chatgpt:     { name: "ChatGPT",     desc: "OpenAI chat assistant",   bg: "#000",    letter: "◎" },
  codex:       { name: "Codex",       desc: "OpenAI terminal agent",   bg: "#6366f1", letter: "</>" },
};

const AUTOMATION_META: Record<
  string,
  { title: string; desc: string; foot: string; tile: { bg: string; color: string; letter: string } }
> = {
  daily_digest: {
    title: "Daily digest",
    desc: "Summarize yesterday's activity across your connectors and drop it in your inbox each morning.",
    foot: "Pulls from Slack, Notion, GitHub, Gmail.",
    tile: { bg: "#fff", color: "#ea4335", letter: "M" },
  },
  weekly_review: {
    title: "Weekly review",
    desc: "Roll up the week — what shipped, what's blocked, what's overdue — and draft a recap doc you can share.",
    foot: "Writes to Notion if connected.",
    tile: { bg: "#0a66c2", color: "#fff", letter: "in" },
  },
  auto_summarize_threads: {
    title: "Auto-summarize threads",
    desc: "Watches Slack threads and writes a one-line summary back into Pioneer so it's searchable from any agent.",
    foot: "Indexed under shared workspace memory.",
    tile: { bg: "#fff", color: "#611f69", letter: "#" },
  },
};

// ---------- Helpers ----------

/** Strip raw [doc:UUID] / [mem:UUID] citation tokens so chat reads like prose. */
function stripCites(text: string): string {
  return text.replace(/\s*\[(?:doc|mem):[0-9a-fA-F-]{36}\]/g, "").trim();
}

function timeAgo(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const s = Math.max(1, Math.floor(ms / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  return `${d}d ago`;
}

type ChatMessage =
  | { role: "user"; text: string }
  | {
      role: "ai";
      text: string;
      sources: ChatSource[];
      cited: string[] | null;     // null while streaming, [] when nothing cited
      usage: StreamUsage | null;
      streaming: boolean;
    };

// ---------- Page ----------

export default function PioneerPage() {
  const [view, setView] = useState<string>("workspace");
  const [wsOpen, setWsOpen] = useState(false);
  const [incognito, setIncognito] = useState(true);
  const [drawer, setDrawer] = useState(false);
  const [feedback, setFeedback] = useState(false);

  const [bootError, setBootError] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceRow | null>(null);
  const [usage, setUsage] = useState<UsageRow | null>(null);
  const [connectors, setConnectors] = useState<ConnectorRow[]>([]);
  const [agents, setAgents] = useState<AgentRow[]>([]);
  const [automations, setAutomations] = useState<AutomationRow[]>([]);
  const [memories, setMemories] = useState<MemoryRow[]>([]);

  const [connectBusy, setConnectBusy] = useState<Record<string, boolean>>({});
  const [syncStatus, setSyncStatus] = useState<Record<string, SyncStatus>>({});
  const [oauthBanner, setOauthBanner] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  // Phase 3 — access control + audit
  const [auditRows, setAuditRows] = useState<AuditEntry[]>([]);
  const [auditVerify, setAuditVerify] = useState<AuditVerify | null>(null);
  const [auditBusy, setAuditBusy] = useState(false);
  const [expandedAgentId, setExpandedAgentId] = useState<string | null>(null);
  const [grantByAgent, setGrantByAgent] = useState<Record<string, Grant | null>>({});
  const [keysByAgent, setKeysByAgent] = useState<Record<string, AgentKeyRow[]>>({});
  const [grantDraft, setGrantDraft] = useState<Record<string, Grant>>({});
  const [newKeyToast, setNewKeyToast] = useState<AgentKeyCreated | null>(null);

  const [rememberText, setRememberText] = useState("");
  const [rememberBusy, setRememberBusy] = useState(false);

  const [chatInput, setChatInput] = useState("");
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [chatBusy, setChatBusy] = useState(false);

  // Phase 4 — drafts drawer
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [draftsOpen, setDraftsOpen] = useState(false);
  const [editingDraftId, setEditingDraftId] = useState<string | null>(null);
  const [editingBody, setEditingBody] = useState<string>("");
  const [runBusy, setRunBusy] = useState<Record<string, boolean>>({});

  // Toggle per-message sources view. Default = hidden (Gemini-style).
  const [openSourcesFor, setOpenSourcesFor] = useState<Record<number, boolean>>({});

  const reloadAll = useCallback(async () => {
    try {
      const [w, u, c, a, au, m] = await Promise.all([
        api.workspace.current(),
        api.workspace.usage(),
        api.connectors.list(),
        api.agents.list(),
        api.automations.list(),
        api.memories.list(),
      ]);
      setWorkspace(w);
      setUsage(u);
      setConnectors(c);
      setAgents(a);
      setAutomations(au);
      setMemories(m);
      setBootError(null);
    } catch (e) {
      setBootError(String(e));
    }
  }, []);

  useEffect(() => {
    void reloadAll();
  }, [reloadAll]);

  const loadAudit = useCallback(async () => {
    try {
      const [rows, v] = await Promise.all([api.audit.list(50), api.audit.verify()]);
      setAuditRows(rows);
      setAuditVerify(v);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => {
    if (view === "audit") void loadAudit();
  }, [view, loadAudit]);

  const loadAgentAccess = useCallback(async (agentId: string) => {
    try {
      const [g, keys] = await Promise.all([
        api.agents.getAccess(agentId),
        api.agents.listKeys(agentId),
      ]);
      setGrantByAgent((s) => ({ ...s, [agentId]: g }));
      setKeysByAgent((s) => ({ ...s, [agentId]: keys }));
      setGrantDraft((s) => ({
        ...s,
        [agentId]: g ?? {
          principal_type: "agent",
          principal_id: agentId,
          sensitivity_max: -1,
          collections: [],
          actions: [],
        },
      }));
    } catch (e) {
      console.error(e);
    }
  }, []);

  const toggleAgentExpand = (agentId: string) => {
    const next = expandedAgentId === agentId ? null : agentId;
    setExpandedAgentId(next);
    if (next && !grantByAgent[next]) void loadAgentAccess(next);
  };

  const saveAccess = async (agentId: string) => {
    const draft = grantDraft[agentId];
    if (!draft) return;
    try {
      const updated = await api.agents.setAccess(agentId, {
        sensitivity_max: draft.sensitivity_max,
        collections: draft.collections,
        actions: draft.actions,
      });
      setGrantByAgent((s) => ({ ...s, [agentId]: updated }));
    } catch (e) {
      console.error(e);
    }
  };

  const mintKey = async (agentId: string) => {
    const name = window.prompt("Key name (e.g. claude-code-laptop)") ?? "";
    if (!name.trim()) return;
    try {
      const created = await api.agents.createKey(agentId, name.trim());
      setNewKeyToast(created);
      const keys = await api.agents.listKeys(agentId);
      setKeysByAgent((s) => ({ ...s, [agentId]: keys }));
    } catch (e) {
      console.error(e);
    }
  };

  const revokeKey = async (agentId: string, keyId: string) => {
    if (!window.confirm("Revoke this key? It will stop working immediately.")) return;
    try {
      await api.agents.revokeKey(agentId, keyId);
      const keys = await api.agents.listKeys(agentId);
      setKeysByAgent((s) => ({ ...s, [agentId]: keys }));
    } catch (e) {
      console.error(e);
    }
  };

  const runVerify = async () => {
    setAuditBusy(true);
    try {
      const v = await api.audit.verify();
      setAuditVerify(v);
    } finally {
      setAuditBusy(false);
    }
  };

  const connectorByProvider = useMemo(() => {
    const m: Record<string, ConnectorRow> = {};
    for (const c of connectors) m[c.provider] = c;
    return m;
  }, [connectors]);

  const agentByProvider = useMemo(() => {
    const m: Record<string, AgentRow> = {};
    for (const a of agents) m[a.provider] = a;
    return m;
  }, [agents]);

  const connect = async (meta: ProviderMeta) => {
    const provider = meta.id;
    setConnectBusy((s) => ({ ...s, [provider]: true }));
    try {
      if (meta.oauth) {
        // Real OAuth — hand off to the provider's consent page.
        const { authorize_url } = await api.connectors.oauthStart(provider);
        window.location.href = authorize_url;
        return; // navigation; component about to unmount
      }
      // Phase-1 stub for non-OAuth providers.
      const updated = await api.connectors.connect(provider);
      setConnectors((rows) => {
        const idx = rows.findIndex((r) => r.provider === provider);
        if (idx < 0) return [...rows, updated];
        const copy = rows.slice();
        copy[idx] = updated;
        return copy;
      });
    } catch (e) {
      console.error(e);
      setOauthBanner({ kind: "err", text: `Couldn't connect ${meta.name}: ${e}` });
    } finally {
      setConnectBusy((s) => ({ ...s, [provider]: false }));
    }
  };

  const manualSync = async (connectorId: string) => {
    try {
      await api.connectors.sync(connectorId);
    } catch (e) {
      console.error(e);
    }
  };

  // Read OAuth-callback URL params on mount. The backend redirects to
  // /?view=connectors&status=connected&connector_id=… (or status=error:*).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const v = params.get("view");
    const status = params.get("status");
    const provider = params.get("provider");
    if (!v && !status) return;
    if (v === "connectors") setView("connectors");
    if (status) {
      if (status === "connected") {
        setOauthBanner({
          kind: "ok",
          text: `${provider ?? "Connector"} connected — first sync starting…`,
        });
      } else if (status.startsWith("error:")) {
        setOauthBanner({
          kind: "err",
          text: `${provider ?? "Connector"} connect failed: ${status.slice(6)}`,
        });
      }
      // Scrub the query so a refresh doesn't re-fire the banner.
      const clean = window.location.pathname;
      window.history.replaceState({}, "", clean);
    }
  }, []);

  // Poll any connector that's actively syncing (or just connected from OAuth).
  useEffect(() => {
    const live = connectors.filter(
      (c) => c.status === "connecting" || c.status === "syncing"
    );
    if (live.length === 0) return;
    let stopped = false;
    const tick = async () => {
      const results = await Promise.allSettled(
        live.map((c) => api.connectors.status(c.id))
      );
      if (stopped) return;
      const next: Record<string, SyncStatus> = {};
      for (let i = 0; i < live.length; i++) {
        const r = results[i];
        if (r.status === "fulfilled") next[live[i].id] = r.value;
      }
      setSyncStatus((s) => ({ ...s, ...next }));
      // Update the connectors list with new statuses so polling stops naturally.
      const becomeTerminal = Object.values(next).some(
        (s) => s.connector_status !== "connecting" && s.connector_status !== "syncing"
      );
      if (becomeTerminal) {
        try {
          const fresh = await api.connectors.list();
          if (!stopped) setConnectors(fresh);
        } catch (e) {
          console.error(e);
        }
      }
    };
    void tick();
    const handle = window.setInterval(tick, 2000);
    return () => {
      stopped = true;
      window.clearInterval(handle);
    };
  }, [connectors]);

  const toggleAutomation = async (a: AutomationRow) => {
    const next = !a.enabled;
    setAutomations((rows) => rows.map((r) => (r.id === a.id ? { ...r, enabled: next } : r)));
    try {
      const updated = await api.automations.toggle(a.id, next);
      setAutomations((rows) => rows.map((r) => (r.id === a.id ? updated : r)));
    } catch (e) {
      console.error(e);
      setAutomations((rows) => rows.map((r) => (r.id === a.id ? { ...r, enabled: !next } : r)));
    }
  };

  const sendChat = async () => {
    const q = chatInput.trim();
    if (!q || chatBusy) return;
    // Add user msg + an empty streaming AI shell we'll mutate as deltas arrive.
    setChat((c) => [
      ...c,
      { role: "user", text: q },
      { role: "ai", text: "", sources: [], cited: null, usage: null, streaming: true },
    ]);
    setChatInput("");
    setChatBusy(true);

    const updateAi = (mutate: (ai: ChatMessage & { role: "ai" }) => void) => {
      setChat((c) => {
        const copy = c.slice();
        for (let i = copy.length - 1; i >= 0; i--) {
          const m = copy[i];
          if (m.role === "ai") {
            const next = { ...m } as ChatMessage & { role: "ai" };
            mutate(next);
            copy[i] = next;
            break;
          }
        }
        return copy;
      });
    };

    try {
      await api.chat.stream(q, {
        onSources: (sources) => updateAi((ai) => { ai.sources = sources; }),
        onDelta: (delta) => updateAi((ai) => { ai.text += delta; }),
        onUsage: (u) => updateAi((ai) => { ai.usage = u; }),
        onDone: (cited) => updateAi((ai) => { ai.cited = cited; ai.streaming = false; }),
        onError: (err) => updateAi((ai) => { ai.text = `Error: ${err}`; ai.streaming = false; }),
      });
      // Refresh real usage bar after a successful chat.
      try {
        const u = await api.workspace.usage();
        setUsage(u);
      } catch { /* ignore */ }
    } catch (e) {
      updateAi((ai) => { ai.text = `Error: ${e}`; ai.streaming = false; });
    } finally {
      setChatBusy(false);
    }
  };

  // ----- Phase 4 drafts handlers -----
  const loadDrafts = useCallback(async () => {
    try {
      const rows = await api.drafts.list();
      setDrafts(rows);
    } catch (e) {
      console.error(e);
    }
  }, []);

  const runAutomation = async (a: AutomationRow) => {
    setRunBusy((s) => ({ ...s, [a.id]: true }));
    try {
      await api.automationsRun.enqueue(a.id);
      // Poll for ~10s for new drafts.
      for (let i = 0; i < 5; i++) {
        await new Promise((r) => setTimeout(r, 1500));
        await loadDrafts();
      }
      setDraftsOpen(true);
    } catch (e) {
      console.error(e);
    } finally {
      setRunBusy((s) => ({ ...s, [a.id]: false }));
    }
  };

  const openDrafts = async () => {
    await loadDrafts();
    setDraftsOpen(true);
  };

  const startEdit = (d: Draft) => {
    setEditingDraftId(d.id);
    setEditingBody(d.draft_body);
  };

  const saveEdit = async (d: Draft) => {
    try {
      const updated = await api.drafts.patch(d.id, { draft_body: editingBody });
      setDrafts((rows) => rows.map((r) => (r.id === d.id ? updated : r)));
      setEditingDraftId(null);
    } catch (e) {
      console.error(e);
    }
  };

  const dismissDraft = async (d: Draft) => {
    try {
      const updated = await api.drafts.patch(d.id, { status: "dismissed" });
      setDrafts((rows) => rows.map((r) => (r.id === d.id ? updated : r)));
    } catch (e) {
      console.error(e);
    }
  };

  const saveMemory = async () => {
    const txt = rememberText.trim();
    if (!txt || rememberBusy) return;
    setRememberBusy(true);
    try {
      const title = txt.split(/\n|\.\s/)[0].slice(0, 80) || "New note";
      const m = await api.memories.create(title, txt);
      setMemories((rows) => [m, ...rows]);
      setRememberText("");
      setDrawer(true);
    } catch (e) {
      console.error(e);
    } finally {
      setRememberBusy(false);
    }
  };

  const greeting = useMemo(() => {
    const h = new Date().getHours();
    return h < 12 ? "Good morning" : h < 18 ? "Good afternoon" : "Good evening";
  }, []);

  const userDisplayName = workspace?.name ?? "your workspace";

  const nav = [
    { id: "chat",        label: "Chat",        icon: MessageSquare },
    { id: "connectors",  label: "Connectors",  icon: Plug },
    { id: "agents",      label: "Agents",      icon: Bot },
    { id: "automations", label: "Automations", icon: Zap },
    { id: "remember",    label: "Remember",    icon: Brain },
    { id: "audit",       label: "Audit",       icon: ShieldCheck },
  ] as const;

  const go = (v: string) => { setView(v); setWsOpen(false); };

  type NavItemProps = { item: { id: string; label: string; icon: React.ComponentType<{ size?: number }> } };
  const NavItem = ({ item }: NavItemProps) => {
    const active = view === item.id;
    const Icon = item.icon;
    return (
      <button
        onClick={() => go(item.id)}
        className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] font-medium transition-colors"
        style={{
          background: active ? ACCENT_SOFT : "transparent",
          color: active ? ACCENT : "rgba(255,255,255,0.82)",
        }}
        onMouseEnter={(e) => { if (!active) (e.currentTarget as HTMLButtonElement).style.background = "rgba(255,255,255,0.05)"; }}
        onMouseLeave={(e) => { if (!active) (e.currentTarget as HTMLButtonElement).style.background = "transparent"; }}
      >
        <Icon size={19} /> {item.label}
      </button>
    );
  };

  return (
    <div
      className="flex h-screen w-full overflow-hidden font-sans text-white"
      style={{
        background: "#0b0a09",
        backgroundImage:
          "radial-gradient(circle at 75% 25%, rgba(255,74,28,0.06), transparent 42%), radial-gradient(circle at 45% 85%, rgba(255,255,255,0.025), transparent 55%)",
      }}
    >
      {/* SIDEBAR */}
      <div className="flex shrink-0 flex-col p-4" style={{ width: 320 }}>
        <div className="flex flex-col rounded-2xl border p-2.5" style={{ background: PANEL, borderColor: LINE }}>
          <div className="mb-1 flex items-center gap-3 px-2 py-1.5 text-white/40">
            <ChevronLeft size={20} /><ChevronRight size={20} />
          </div>

          <button
            onClick={() => go("workspace")}
            className="flex items-center gap-3 rounded-xl px-2.5 py-2.5 transition-colors"
            style={{
              background: view === "workspace" ? ACCENT_SOFT : "transparent",
              border: view === "workspace" ? `1px solid ${ACCENT_BORDER}` : "1px solid transparent",
            }}
          >
            <span
              className="flex h-9 w-9 items-center justify-center rounded-lg text-base font-bold"
              style={{ background: view === "workspace" ? ACCENT : "rgba(255,255,255,0.1)", color: "#fff" }}
            >P</span>
            <span className="text-[15px] font-semibold" style={{ color: view === "workspace" ? ACCENT : "#fff" }}>
              {workspace?.name ?? "Workspace"}
            </span>
          </button>

          <div className="mt-1 flex flex-col gap-0.5">
            {nav.map((item) => <NavItem key={item.id} item={item} />)}
            <div className="flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-[15px] font-medium text-white/82">
              <span className="flex items-center gap-3"><VenetianMask size={19} /> Incognito</span>
              <Toggle on={incognito} onClick={() => setIncognito((v) => !v)} />
            </div>
          </div>

          <div className="my-2 h-px" style={{ background: LINE }} />

          <button
            onClick={() => go("account")}
            className="flex items-center gap-3 rounded-xl px-2.5 py-2.5 transition-colors"
            style={{
              background: view === "account" ? ACCENT_SOFT : "rgba(255,255,255,0.02)",
              border: view === "account" ? `1px solid ${ACCENT_BORDER}` : "1px solid transparent",
            }}
          >
            <span
              className="flex h-9 w-9 items-center justify-center rounded-lg text-sm font-bold"
              style={{ background: "linear-gradient(135deg,#7c5cff,#ff4a1c)" }}
            >MP</span>
            <span className="text-[15px] font-semibold" style={{ color: view === "account" ? ACCENT : "#fff" }}>
              Meetkumar Patel
            </span>
          </button>
        </div>

        <button
          onClick={() => setFeedback(true)}
          className="mt-auto flex h-12 w-12 items-center justify-center rounded-full border text-white/60 transition-colors hover:text-white"
          style={{ background: "rgba(255,255,255,0.03)", borderColor: LINE }}
        >
          <HelpCircle size={22} />
        </button>
      </div>

      {/* MAIN */}
      <div className="relative flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-6 py-12">
          {bootError && (
            <div className="mb-6 rounded-2xl border px-5 py-4 text-sm" style={{ background: "#2a1410", borderColor: ACCENT_BORDER, color: "#ffb6a3" }}>
              Couldn&apos;t reach the API: <code className="font-mono">{bootError}</code>
            </div>
          )}

          {oauthBanner && (
            <div
              className="mb-6 flex items-center justify-between rounded-2xl border px-5 py-3 text-sm"
              style={{
                background: oauthBanner.kind === "ok" ? "rgba(74,222,128,0.07)" : "#2a1410",
                borderColor: oauthBanner.kind === "ok" ? "rgba(74,222,128,0.32)" : ACCENT_BORDER,
                color: oauthBanner.kind === "ok" ? "#bbf7d0" : "#ffb6a3",
              }}
            >
              <span>{oauthBanner.text}</span>
              <button
                onClick={() => setOauthBanner(null)}
                className="rounded p-1 text-white/40 hover:text-white"
                aria-label="Dismiss"
              >
                <X size={14} />
              </button>
            </div>
          )}

          {/* WORKSPACE */}
          {view === "workspace" && (
            <>
              <Title>Workspace</Title>

              <div className="relative mb-4">
                <button
                  onClick={() => setWsOpen((v) => !v)}
                  className="flex w-full items-center justify-between rounded-2xl border px-5 py-4"
                  style={{ background: CARD, borderColor: LINE }}
                >
                  <span className="flex items-center gap-3">
                    <span className="flex h-9 w-9 items-center justify-center rounded-lg text-base font-bold" style={{ background: "rgba(255,255,255,0.1)" }}>P</span>
                    <span className="text-lg font-semibold">{workspace?.name ?? "Workspace"}</span>
                  </span>
                  {wsOpen ? <ChevronUp size={22} className="text-white/50" /> : <ChevronDown size={22} className="text-white/50" />}
                </button>
                {wsOpen && (
                  <div className="absolute z-10 mt-2 w-full overflow-hidden rounded-2xl border" style={{ background: "#1a1817", borderColor: LINE }}>
                    <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: `1px solid ${LINE}` }}>
                      <span className="flex items-center gap-3">
                        <span className="flex h-9 w-9 items-center justify-center rounded-lg text-base font-bold" style={{ background: "rgba(255,255,255,0.1)" }}>P</span>
                        <span className="text-lg font-semibold">{workspace?.name ?? "Workspace"}</span>
                      </span>
                      <Check size={20} style={{ color: "#4ade80" }} />
                    </div>
                    <button className="flex w-full items-center gap-3 px-5 py-4 transition-colors hover:bg-white/5">
                      <span className="flex h-9 w-9 items-center justify-center rounded-lg" style={{ background: "rgba(255,255,255,0.1)" }}><Plus size={20} /></span>
                      <span className="text-lg font-semibold">Create workspace</span>
                    </button>
                  </div>
                )}
              </div>

              <div className="mb-8 rounded-2xl border px-5 py-5 text-[15px] leading-relaxed text-white/70" style={{ background: CARD, borderColor: LINE }}>
                Personal workspaces are just for you, with 1M tokens of free usage a month. To collaborate with others or get more usage, create or switch to a new workspace using the dropdown.
              </div>

              <div className="mb-4 flex items-center gap-3 text-sm font-semibold uppercase tracking-wide text-white/50">
                <span className="h-1 w-6 rounded" style={{ background: ACCENT }} /> Billing
              </div>
              <div className="mb-4 rounded-2xl border px-6 py-5" style={{ background: CARD, borderColor: LINE }}>
                <p className="text-xl font-bold capitalize">{workspace?.plan ?? "—"}</p>
                <p className="mt-1 text-white/55">{usage ? `Period ${usage.period}` : "—"}</p>
              </div>

              <div className="rounded-2xl border px-6 py-6" style={{ background: CARD, borderColor: LINE }}>
                <p className="mb-5 text-xl font-bold">Usage</p>
                <div className="mb-2 flex items-center justify-between text-[15px]">
                  <span className="font-semibold">{usage ? `Period ${usage.period}` : "—"}</span>
                  <span className="font-bold">
                    {(usage?.tokens_used ?? 0).toLocaleString()} tokens / 1M tokens
                  </span>
                </div>
                <div className="h-3 w-full overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.08)" }}>
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${Math.min(100, ((usage?.tokens_used ?? 0) / 1_000_000) * 100)}%`,
                      background: ACCENT,
                    }}
                  />
                </div>
                <p className="mt-5 text-sm text-white/45">
                  {memories.length} memories filed · {connectors.filter((c) => c.status === "connected").length} connectors active
                </p>
              </div>
            </>
          )}

          {/* CHAT */}
          {view === "chat" && (
            <div className="flex min-h-[70vh] flex-col items-center justify-center">
              <h1 className="text-center text-6xl font-bold tracking-tight">{greeting}, {userDisplayName}</h1>
              <div className="mt-2 h-1 w-12 rounded-full" style={{ background: ACCENT }} />
              {chat.length === 0 ? (
                <div className="mt-10 flex max-w-2xl flex-wrap justify-center gap-3">
                  {[
                    "Which vector database did we pick?",
                    "What did we decide about pricing?",
                    "Summarize the Acme call.",
                    "What is the launch plan?",
                  ].map((q) => (
                    <button
                      key={q}
                      onClick={() => setChatInput(q)}
                      className="rounded-full border px-5 py-3 text-[15px] text-white/85 transition-colors hover:bg-white/5"
                      style={{ background: CARD, borderColor: LINE }}
                    >
                      {q}
                    </button>
                  ))}
                </div>
              ) : (
                <div className="mt-8 w-full max-w-2xl space-y-3">
                  {chat.map((m, i) => (
                    <div key={i}>
                      <div
                        className={`rounded-2xl border px-5 py-3 text-[15px] ${m.role === "user" ? "ml-auto max-w-[80%]" : "mr-auto max-w-[85%]"}`}
                        style={{
                          background: m.role === "user" ? ACCENT_SOFT : CARD,
                          borderColor: m.role === "user" ? ACCENT_BORDER : LINE,
                        }}
                      >
                        {m.role === "ai" && m.streaming && m.text.length === 0 ? (
                          <span className="flex items-center gap-2 text-white/55">
                            <Loader2 size={14} className="animate-spin" /> reading workspace memory…
                          </span>
                        ) : (
                          <span className="whitespace-pre-wrap">{m.role === "ai" ? stripCites(m.text) : m.text}{m.role === "ai" && m.streaming ? "▍" : ""}</span>
                        )}
                      </div>
                      {m.role === "ai" && !m.streaming && m.sources.length > 0 && (() => {
                        const cited = new Set(m.cited ?? []);
                        const visible = m.cited && m.cited.length > 0
                          ? m.sources.filter((s) => cited.has(s.cite_id))
                          : m.sources;
                        const isOpen = !!openSourcesFor[i];
                        return (
                          <div className="mr-auto mt-2 max-w-[85%]">
                            <button
                              onClick={() => setOpenSourcesFor((s) => ({ ...s, [i]: !s[i] }))}
                              className="flex items-center gap-1.5 text-[11px] font-medium text-white/45 hover:text-white/85 transition-colors"
                            >
                              {isOpen ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                              {visible.length} source{visible.length === 1 ? "" : "s"}
                              {m.usage ? <span className="ml-2 text-white/30">· {m.usage.input_tokens + m.usage.output_tokens} tok · {m.usage.provider}</span> : null}
                            </button>
                            {isOpen && (
                              <div className="mt-2 space-y-2">
                                {visible.map((s) => {
                                  const isDoc = s.kind === "document";
                                  return (
                                    <div
                                      key={s.cite_id}
                                      className="rounded-xl border px-4 py-2 text-[13px]"
                                      style={{ background: "rgba(255,255,255,0.02)", borderColor: LINE }}
                                    >
                                      <div className="flex items-center justify-between text-white/60">
                                        <span className="flex items-center gap-2 text-white/85 font-medium">
                                          {isDoc
                                            ? <Plug size={14} style={{ color: ACCENT }} />
                                            : <Brain size={14} style={{ color: ACCENT }} />}
                                          {s.title}
                                        </span>
                                      </div>
                                      <p className="mt-1 text-white/50 text-[11px]">{s.collection} · {s.sensitivity}</p>
                                      {isDoc && s.url && (
                                        <a
                                          href={s.url}
                                          target="_blank"
                                          rel="noreferrer"
                                          className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium"
                                          style={{ color: ACCENT }}
                                        >
                                          Open ↗
                                        </a>
                                      )}
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        );
                      })()}
                    </div>
                  ))}
                </div>
              )}

              <div
                className="mt-8 flex w-full max-w-2xl items-center gap-3 rounded-2xl border-2 px-4 py-3"
                style={{ background: CARD, borderColor: ACCENT_BORDER }}
              >
                <History size={22} className="shrink-0 text-white/45" />
                <input
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && sendChat()}
                  placeholder="Search or ask anything"
                  className="flex-1 bg-transparent text-[15px] outline-none placeholder:text-white/40"
                />
                <button
                  onClick={sendChat}
                  disabled={chatBusy}
                  className="flex h-9 w-9 items-center justify-center rounded-full disabled:opacity-50"
                  style={{ background: "rgba(255,255,255,0.1)" }}
                >
                  {chatBusy ? <Loader2 size={18} className="animate-spin" /> : <ArrowUp size={20} />}
                </button>
              </div>
            </div>
          )}

          {/* CONNECTORS */}
          {view === "connectors" && (
            <>
              <Title>Connectors</Title>
              <p className="mb-6 text-[15px] leading-relaxed text-white/70">
                Sync knowledge from the tools your team already uses. Connect more than one account per service if you need to.
              </p>
              <div className="mb-4 rounded-2xl border px-6 py-6" style={{ background: CARD, borderColor: LINE }}>
                <div className="flex items-center justify-between px-6">
                  <div className="flex flex-col gap-2">
                    {["G", "S", "N"].map((l) => (
                      <span key={l} className="flex h-9 w-9 items-center justify-center rounded-lg text-sm font-bold" style={{ background: "#fff", color: "#000" }}>{l}</span>
                    ))}
                  </div>
                  <div className="flex-1 px-6 text-center text-2xl tracking-widest" style={{ color: ACCENT }}>· · · · · ·</div>
                  {BRAND}
                </div>
                <p className="mt-5 text-[15px] leading-relaxed text-white/70">
                  Connectors help our agents learn everything about your company. Once you connect, our agents ingest and synthesize all of the information across your tools and make it accessible inside Pioneer.
                </p>
              </div>

              {CONNECTOR_META.map((c) => {
                const row = connectorByProvider[c.id];
                const live = row ? syncStatus[row.id] : undefined;
                const status = row?.status ?? "disconnected";
                const connected = status === "connected";
                const syncing = status === "connecting" || status === "syncing";
                const errored = status === "error";
                return (
                  <div key={c.id} className="mb-4 rounded-2xl border px-5 py-4" style={{ background: CARD, borderColor: LINE }}>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-4">
                        <Tile bg={c.bg} color={c.color} icon={c.icon}>{c.letter}</Tile>
                        <div>
                          <p className="font-semibold">{c.name}</p>
                          <p className="text-sm text-white/50">
                            {c.desc}
                            {row?.last_synced_at && !syncing
                              ? ` · last sync ${timeAgo(row.last_synced_at)}`
                              : ""}
                          </p>
                        </div>
                      </div>
                      {syncing ? (
                        <span className="flex items-center gap-2 text-sm font-medium" style={{ color: ACCENT }}>
                          <Loader2 size={14} className="animate-spin" />
                          {live?.run_status === "running"
                            ? `Syncing — ${live.docs_ingested}/${Math.max(live.docs_seen, live.docs_ingested)} docs`
                            : "Queued…"}
                        </span>
                      ) : connected ? (
                        <div className="flex items-center gap-3">
                          <Connected />
                          {c.oauth && row && (
                            <button
                              onClick={() => manualSync(row.id)}
                              className="rounded-lg px-3 py-1.5 text-xs font-medium text-white/80 transition-colors"
                              style={{ background: "rgba(255,255,255,0.07)" }}
                              title="Sync now"
                            >
                              Sync now
                            </button>
                          )}
                        </div>
                      ) : errored ? (
                        <span className="text-sm font-medium text-red-300">
                          Error
                        </span>
                      ) : (
                        <ConnectBtn busy={!!connectBusy[c.id]} onClick={() => connect(c)} />
                      )}
                    </div>
                    {errored && live?.error && (
                      <p className="mt-3 rounded-lg border px-3 py-2 text-xs leading-relaxed text-red-200" style={{ background: "rgba(120,30,20,0.18)", borderColor: "rgba(255,80,60,0.25)" }}>
                        {live.error}
                      </p>
                    )}
                    {syncing && live && live.docs_seen > 0 && (
                      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.06)" }}>
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${Math.min(100, (live.docs_ingested / Math.max(live.docs_seen, 1)) * 100)}%`,
                            background: ACCENT,
                          }}
                        />
                      </div>
                    )}
                  </div>
                );
              })}

              <div className="flex items-center gap-3 rounded-2xl border px-5 py-4 text-white/45" style={{ background: CARD, borderColor: LINE }}>
                <div className="flex gap-1.5">
                  {Array.from({ length: 8 }).map((_, i) => (
                    <span key={i} className="h-7 w-7 rounded-full" style={{ background: "rgba(255,255,255,0.08)" }} />
                  ))}
                </div>
                <span className="text-sm">More coming soon</span>
              </div>
            </>
          )}

          {/* AGENTS */}
          {view === "agents" && (
            <>
              <Title>Agents</Title>
              <p className="mb-6 text-[15px] leading-relaxed text-white/70">
                Connect your AI tools so they can read and write to this workspace memory over MCP.
              </p>

              <div className="mb-4 flex items-center gap-3 text-sm font-semibold uppercase tracking-wide text-white/50">
                <span className="h-1 w-6 rounded" style={{ background: ACCENT }} /> Agents
              </div>

              {Object.entries(AGENT_META).map(([provider, meta]) => {
                const row = agentByProvider[provider];
                const expanded = row && expandedAgentId === row.id;
                const grant = row ? grantByAgent[row.id] : undefined;
                const draft = row ? grantDraft[row.id] : undefined;
                const keys = (row ? keysByAgent[row.id] : []) ?? [];
                return (
                  <div key={provider} className="mb-4 rounded-2xl border" style={{ background: CARD, borderColor: LINE }}>
                    <div className="flex items-center justify-between px-5 py-4">
                      <div className="flex items-center gap-4">
                        <Tile bg={meta.bg} color="#fff" icon={meta.icon}>{meta.letter}</Tile>
                        <div>
                          <p className="font-semibold">{meta.name}</p>
                          <p className="text-sm text-white/50">{meta.desc}</p>
                          {row && grant && (
                            <p className="mt-1 text-xs text-white/45">
                              {grant.sensitivity_max >= 0
                                ? `read up to ${SENS_LABELS[grant.sensitivity_max]} · ${grant.collections.join(", ") || "no collections"}`
                                : "no access (deny-by-default)"}
                            </p>
                          )}
                        </div>
                      </div>
                      <div className="flex items-center gap-3">
                        {row && (
                          <button
                            onClick={() => toggleAgentExpand(row.id)}
                            className="rounded-xl px-4 py-2 text-sm font-medium"
                            style={{
                              background: expanded ? ACCENT_SOFT : "rgba(255,255,255,0.07)",
                              color: expanded ? ACCENT : "#fff",
                            }}
                          >
                            Access {expanded ? <ChevronUp size={14} className="inline -mt-0.5" /> : <ChevronDown size={14} className="inline -mt-0.5" />}
                          </button>
                        )}
                      </div>
                    </div>
                    {expanded && row && draft && (
                      <div className="border-t px-5 py-4 space-y-4" style={{ borderColor: LINE }}>
                        <div>
                          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/55">Read sensitivity ceiling</p>
                          <div className="flex gap-2">
                            {[-1, 0, 1, 2].map((rank) => {
                              const labels = ["none", "public", "internal", "restricted"];
                              const label = labels[rank + 1];
                              const active = draft.sensitivity_max === rank;
                              return (
                                <button
                                  key={rank}
                                  onClick={() =>
                                    setGrantDraft((s) => ({
                                      ...s,
                                      [row.id]: { ...draft, sensitivity_max: rank },
                                    }))
                                  }
                                  className="rounded-lg px-3 py-1.5 text-xs font-medium"
                                  style={{
                                    background: active ? ACCENT : "rgba(255,255,255,0.06)",
                                    color: active ? "#fff" : "rgba(255,255,255,0.75)",
                                  }}
                                >
                                  {label}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                        <div>
                          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/55">Collections</p>
                          <div className="flex flex-wrap gap-2">
                            {[...KNOWN_COLLECTIONS, "*"].map((col) => {
                              const active = draft.collections.includes(col);
                              return (
                                <button
                                  key={col}
                                  onClick={() =>
                                    setGrantDraft((s) => ({
                                      ...s,
                                      [row.id]: {
                                        ...draft,
                                        collections: active
                                          ? draft.collections.filter((c) => c !== col)
                                          : [...draft.collections, col],
                                      },
                                    }))
                                  }
                                  className="rounded-lg px-3 py-1.5 text-xs font-medium"
                                  style={{
                                    background: active ? ACCENT : "rgba(255,255,255,0.06)",
                                    color: active ? "#fff" : "rgba(255,255,255,0.75)",
                                  }}
                                >
                                  {col === "*" ? "all (wildcard)" : col}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                        <div>
                          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/55">Actions</p>
                          <div className="flex gap-2">
                            {(["read", "write"] as const).map((act) => {
                              const active = draft.actions.includes(act);
                              return (
                                <button
                                  key={act}
                                  onClick={() =>
                                    setGrantDraft((s) => ({
                                      ...s,
                                      [row.id]: {
                                        ...draft,
                                        actions: active
                                          ? draft.actions.filter((a) => a !== act)
                                          : [...draft.actions, act],
                                      },
                                    }))
                                  }
                                  className="rounded-lg px-3 py-1.5 text-xs font-medium"
                                  style={{
                                    background: active ? ACCENT : "rgba(255,255,255,0.06)",
                                    color: active ? "#fff" : "rgba(255,255,255,0.75)",
                                  }}
                                >
                                  {act}
                                </button>
                              );
                            })}
                          </div>
                        </div>
                        <div className="flex items-center justify-between pt-2">
                          <button
                            onClick={() => saveAccess(row.id)}
                            className="rounded-xl px-4 py-2 text-sm font-semibold text-white"
                            style={{ background: ACCENT }}
                          >
                            Save access
                          </button>
                          <button
                            onClick={() => mintKey(row.id)}
                            className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium"
                            style={{ background: "rgba(255,255,255,0.08)" }}
                          >
                            <Key size={14} /> Generate key
                          </button>
                        </div>

                        <div>
                          <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-white/55">Keys</p>
                          <div className="space-y-2">
                            {keys.length === 0 && (
                              <p className="text-xs text-white/40">No keys yet.</p>
                            )}
                            {keys.map((k) => (
                              <div
                                key={k.id}
                                className="flex items-center justify-between rounded-lg border px-3 py-2"
                                style={{ background: "rgba(255,255,255,0.03)", borderColor: LINE }}
                              >
                                <div className="flex flex-col">
                                  <span className="font-mono text-xs">
                                    {k.key_prefix}…
                                    <span className="text-white/45 ml-2">{k.name}</span>
                                  </span>
                                  <span className="text-[11px] text-white/40">
                                    {k.revoked_at
                                      ? "revoked"
                                      : k.last_used_at
                                      ? `last used ${timeAgo(k.last_used_at)}`
                                      : "never used"}
                                  </span>
                                </div>
                                {!k.revoked_at && (
                                  <button
                                    onClick={() => revokeKey(row.id, k.id)}
                                    className="rounded px-2 py-1 text-xs text-red-300 hover:bg-red-500/10"
                                  >
                                    Revoke
                                  </button>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}

              <div className="rounded-2xl border px-5 py-5" style={{ background: CARD, borderColor: LINE }}>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-[15px] font-medium">Other tool? Add Pioneer as an MCP server</p>
                    <p className="mt-1 font-mono text-sm text-white/60">uv run python -m mcp.server</p>
                  </div>
                  <button
                    onClick={() => navigator.clipboard?.writeText("uv run python -m mcp.server")}
                    className="flex h-9 w-9 items-center justify-center rounded-lg"
                    style={{ background: "rgba(255,255,255,0.07)" }}
                  >
                    <Copy size={18} />
                  </button>
                </div>
              </div>
            </>
          )}

          {/* AUTOMATIONS */}
          {view === "automations" && (
            <>
              <Title>Automations</Title>
              <p className="mb-6 text-[15px] leading-relaxed text-white/70">
                Background tasks powered by your Pioneer memory. They run quietly and write back to your tools.
              </p>
              <div className="mb-4 rounded-2xl border px-6 py-6 text-[15px] leading-relaxed text-white/70" style={{ background: CARD, borderColor: LINE }}>
                <div className="mb-4 flex items-center gap-4">
                  {BRAND}
                  <div className="flex-1 space-y-2">
                    {[1, 2, 3].map((i) => (
                      <div key={i} className="h-1 rounded-full" style={{ width: `${70 + i * 8}%`, background: ACCENT }} />
                    ))}
                  </div>
                </div>
                Automations use the connectors you already gave access to in order to do boring, repetitive work in the background 24/7.
              </div>

              {automations.map((a) => {
                const meta = AUTOMATION_META[a.type] ?? {
                  title: a.type,
                  desc: "Background automation.",
                  foot: "",
                  tile: { bg: "#fff", color: "#000", letter: "•" },
                };
                return (
                  <div key={a.id} className="mb-4 rounded-2xl border px-5 py-5" style={{ background: CARD, borderColor: LINE }}>
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex gap-4">
                        <Tile bg={meta.tile.bg} color={meta.tile.color}>{meta.tile.letter}</Tile>
                        <div>
                          <p className="font-semibold">{meta.title}</p>
                          <p className="mt-1 text-sm leading-relaxed text-white/55">{meta.desc}</p>
                          {meta.foot && <p className="mt-2 text-sm font-semibold">{meta.foot}</p>}
                          {a.enabled && (
                            <div className="mt-3 flex items-center gap-2">
                              <button
                                onClick={() => runAutomation(a)}
                                disabled={!!runBusy[a.id]}
                                className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                                style={{ background: ACCENT }}
                              >
                                {runBusy[a.id] ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} Run now
                              </button>
                              <button
                                onClick={openDrafts}
                                className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium"
                                style={{ background: "rgba(255,255,255,0.07)" }}
                              >
                                <Inbox size={16} /> View drafts
                              </button>
                            </div>
                          )}
                        </div>
                      </div>
                      <Toggle on={a.enabled} onClick={() => toggleAutomation(a)} />
                    </div>
                  </div>
                );
              })}
            </>
          )}

          {/* AUDIT */}
          {view === "audit" && (
            <>
              <Title>Audit</Title>
              <p className="mb-4 text-[15px] leading-relaxed text-white/70">
                Every read, write, and denial in this workspace is recorded as an immutable, hash-chained entry. Verify integrity any time.
              </p>
              <div className="mb-4 flex items-center justify-between rounded-2xl border px-5 py-4" style={{ background: CARD, borderColor: LINE }}>
                <div>
                  <p className="text-[15px] font-semibold">
                    {auditVerify
                      ? auditVerify.ok
                        ? "✓ Chain valid"
                        : "✗ Tamper detected"
                      : "—"}
                  </p>
                  <p className="mt-1 text-xs text-white/55">
                    {auditVerify
                      ? `${auditVerify.total} entries · head ${auditVerify.head_hash.slice(0, 16)}…${
                          auditVerify.broken_at_seq != null ? ` · broken at seq ${auditVerify.broken_at_seq}` : ""
                        }`
                      : "Click Verify to compute the chain."}
                  </p>
                </div>
                <button
                  onClick={runVerify}
                  disabled={auditBusy}
                  className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                  style={{ background: ACCENT }}
                >
                  {auditBusy ? <Loader2 size={14} className="animate-spin" /> : <ShieldCheck size={14} />} Verify integrity
                </button>
              </div>

              <div className="rounded-2xl border" style={{ background: CARD, borderColor: LINE }}>
                <div
                  className="grid border-b px-5 py-3 text-[11px] font-semibold uppercase tracking-wide text-white/45"
                  style={{ borderColor: LINE, gridTemplateColumns: "60px 90px 1fr 1fr 80px 80px" }}
                >
                  <span>seq</span>
                  <span>who</span>
                  <span>action</span>
                  <span>resource</span>
                  <span>decision</span>
                  <span>time</span>
                </div>
                {auditRows.length === 0 && (
                  <p className="px-5 py-4 text-sm text-white/40">No entries yet — start using Chat or Remember.</p>
                )}
                {auditRows.map((r) => (
                  <div
                    key={r.id}
                    className="grid border-b px-5 py-3 text-[13px]"
                    style={{ borderColor: LINE, gridTemplateColumns: "60px 90px 1fr 1fr 80px 80px" }}
                  >
                    <span className="font-mono text-white/55">{r.seq}</span>
                    <span className="text-white/75">{r.principal_type}</span>
                    <span className="font-mono text-white/85">{r.action}</span>
                    <span className="text-white/55">
                      {r.resource_type}
                      {r.resource_id ? ` · ${r.resource_id.slice(0, 8)}…` : ""}
                    </span>
                    <span
                      style={{
                        color: r.decision === "deny" ? "#fda4af" : "#4ade80",
                      }}
                    >
                      {r.decision}
                    </span>
                    <span className="text-white/45">{timeAgo(r.created_at)}</span>
                  </div>
                ))}
              </div>
            </>
          )}

          {/* REMEMBER */}
          {view === "remember" && (
            <>
              <Title>Remember</Title>
              <p className="mb-6 text-[15px] leading-relaxed text-white/70">
                Write or paste anything, and Pioneer will index it into shared memory for all your humans and AI tools.
              </p>
              <div className="overflow-hidden rounded-2xl border" style={{ background: CARD, borderColor: LINE }}>
                <div className="flex items-center gap-4 border-b px-5 py-3 text-white/55" style={{ borderColor: LINE }}>
                  <Bold size={18} /><Italic size={18} /><Strikethrough size={18} /><Code size={18} />
                </div>
                <textarea
                  value={rememberText}
                  onChange={(e) => setRememberText(e.target.value)}
                  placeholder="Start typing…"
                  rows={12}
                  className="w-full resize-none bg-transparent px-5 py-4 text-[15px] outline-none placeholder:text-white/30"
                />
                <div className="flex items-center justify-between px-5 py-3">
                  <button onClick={() => setDrawer(true)} className="text-white/50 hover:text-white" aria-label="Open filed memories">
                    <History size={20} />
                  </button>
                  <button
                    onClick={saveMemory}
                    disabled={rememberBusy || !rememberText.trim()}
                    className="flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold disabled:opacity-50"
                    style={{ background: "rgba(255,255,255,0.1)" }}
                  >
                    {rememberBusy ? <Loader2 size={16} className="animate-spin" /> : <Send size={16} />} Remember
                  </button>
                </div>
              </div>
            </>
          )}

          {/* ACCOUNT */}
          {view === "account" && (
            <>
              <Title>Account</Title>
              <div className="flex items-center justify-between rounded-2xl border px-5 py-5" style={{ background: CARD, borderColor: LINE }}>
                <div className="flex items-center gap-4">
                  <span className="flex h-12 w-12 items-center justify-center rounded-xl text-base font-bold" style={{ background: "linear-gradient(135deg,#7c5cff,#ff4a1c)" }}>MP</span>
                  <div><p className="font-semibold">Meetkumar Patel</p><p className="text-sm text-white/50">meetp0006@gmail.com</p></div>
                </div>
                <button
                  onClick={() => { window.localStorage.removeItem("pioneer.jwt"); window.location.reload(); }}
                  className="flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium"
                  style={{ background: "rgba(255,255,255,0.07)" }}
                >
                  <LogOut size={16} /> Sign out
                </button>
              </div>
            </>
          )}
        </div>

        {/* FILED MEMORIES DRAWER */}
        {drawer && (
          <div className="absolute right-0 top-0 z-20 h-full w-[420px] overflow-y-auto border-l p-6" style={{ background: "#0d0c0b", borderColor: LINE }}>
            <button onClick={() => setDrawer(false)} className="mb-6 flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium" style={{ background: "rgba(255,255,255,0.07)" }}>
              <ChevronLeft size={18} /> Close
            </button>
            <h2 className="mb-4 text-4xl font-bold">Filed memories</h2>
            <div className="mb-3 flex items-center gap-3 text-sm font-semibold uppercase tracking-wide text-white/50">
              <span className="h-1 w-6 rounded" style={{ background: ACCENT }} /> Recent
            </div>
            <div className="space-y-3">
              {memories.length === 0 && (
                <p className="text-sm text-white/40">No memories yet. Use the Remember view to file one.</p>
              )}
              {memories.map((m) => (
                <div key={m.id} className="rounded-2xl border px-5 py-4" style={{ background: CARD, borderColor: LINE }}>
                  <p className="flex items-center gap-2 font-semibold"><Brain size={18} style={{ color: ACCENT }} /> {m.title}</p>
                  <p className="mt-1 text-sm leading-relaxed text-white/55 line-clamp-3">{m.body}</p>
                  <div className="mt-3 flex items-center justify-between text-sm text-white/50">
                    <span className="flex items-center gap-2">
                      <span className="h-5 w-5 rounded" style={{ background: "linear-gradient(135deg,#7c5cff,#ff4a1c)" }} /> {m.source}
                    </span>
                    <span>{timeAgo(m.created_at)}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* DRAFTS DRAWER */}
        {draftsOpen && (
          <div className="absolute right-0 top-0 z-20 h-full w-[480px] overflow-y-auto border-l p-6" style={{ background: "#0d0c0b", borderColor: LINE }}>
            <div className="mb-6 flex items-center justify-between">
              <button onClick={() => setDraftsOpen(false)} className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium" style={{ background: "rgba(255,255,255,0.07)" }}>
                <ChevronLeft size={18} /> Close
              </button>
              <button onClick={loadDrafts} className="text-xs text-white/45 hover:text-white/85">Refresh</button>
            </div>
            <h2 className="mb-2 text-4xl font-bold">Drafts</h2>
            <p className="mb-4 text-sm leading-relaxed text-white/55">
              Reply drafts generated by your automations. Nothing is sent — review, edit, copy, then send from the source app yourself.
            </p>
            <div className="mb-3 flex items-center gap-3 text-sm font-semibold uppercase tracking-wide text-white/50">
              <span className="h-1 w-6 rounded" style={{ background: ACCENT }} /> Pending
            </div>
            <div className="space-y-3">
              {drafts.length === 0 && (
                <p className="text-sm text-white/40">No drafts yet. Enable an automation and click <span className="font-semibold text-white/75">Run now</span>.</p>
              )}
              {drafts.map((d) => {
                const isEditing = editingDraftId === d.id;
                const dim = d.status === "dismissed";
                return (
                  <div key={d.id} className={`rounded-2xl border px-5 py-4 ${dim ? "opacity-50" : ""}`} style={{ background: CARD, borderColor: LINE }}>
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold uppercase tracking-wide text-white/50">
                        {d.channel} · {d.recipient ?? "unknown"}
                      </span>
                      <span className="text-[11px]" style={{ color: d.status === "dismissed" ? "#fda4af" : d.status === "edited" ? ACCENT : "#4ade80" }}>
                        {d.status}
                      </span>
                    </div>
                    <p className="mt-2 rounded-lg border px-3 py-2 text-xs leading-relaxed text-white/55" style={{ background: "rgba(255,255,255,0.02)", borderColor: LINE }}>
                      <span className="font-semibold text-white/70">Incoming:</span> {d.incoming_excerpt.slice(0, 220)}
                    </p>
                    {isEditing ? (
                      <textarea
                        value={editingBody}
                        onChange={(e) => setEditingBody(e.target.value)}
                        rows={6}
                        className="mt-3 w-full resize-none rounded-lg border bg-transparent px-3 py-2 text-sm outline-none"
                        style={{ borderColor: ACCENT_BORDER }}
                      />
                    ) : (
                      <p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed text-white/85">{d.draft_body}</p>
                    )}
                    <div className="mt-3 flex items-center justify-between">
                      <span className="text-[11px] text-white/40">{timeAgo(d.updated_at)}</span>
                      <div className="flex items-center gap-2">
                        {isEditing ? (
                          <>
                            <button onClick={() => setEditingDraftId(null)} className="rounded-lg px-3 py-1.5 text-xs text-white/65 hover:bg-white/5">Cancel</button>
                            <button onClick={() => saveEdit(d)} className="rounded-lg px-3 py-1.5 text-xs font-semibold text-white" style={{ background: ACCENT }}>Save</button>
                          </>
                        ) : (
                          <>
                            {!dim && (
                              <>
                                <button onClick={() => navigator.clipboard?.writeText(d.draft_body)} className="flex items-center gap-1 rounded-lg px-3 py-1.5 text-xs text-white/75 hover:bg-white/5"><Copy size={12} /> Copy</button>
                                <button onClick={() => startEdit(d)} className="rounded-lg px-3 py-1.5 text-xs text-white/75 hover:bg-white/5">Edit</button>
                                <button onClick={() => dismissDraft(d)} className="rounded-lg px-3 py-1.5 text-xs text-red-300 hover:bg-red-500/10">Dismiss</button>
                              </>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* NEW AGENT KEY MODAL — shown ONCE on creation */}
        {newKeyToast && (
          <div className="absolute inset-0 z-40 flex items-center justify-center bg-black/60 p-6">
            <div className="w-full max-w-xl rounded-2xl border p-6" style={{ background: "#1a1817", borderColor: ACCENT_BORDER }}>
              <div className="mb-3 flex items-center justify-between">
                <p className="font-semibold">Copy this key now</p>
                <button onClick={() => setNewKeyToast(null)} className="text-white/50 hover:text-white"><X size={18} /></button>
              </div>
              <p className="mb-3 text-sm text-white/65">
                Pioneer only stores a sha256 hash. You won&apos;t see this plaintext again — copy it and paste into your agent&apos;s config.
              </p>
              <pre className="overflow-auto rounded-xl border px-3 py-2 font-mono text-sm" style={{ background: "#0d0c0b", borderColor: LINE }}>{newKeyToast.plaintext}</pre>
              <div className="mt-3 flex items-center justify-between">
                <span className="text-xs text-white/40">key id: {newKeyToast.id.slice(0, 8)}…</span>
                <button
                  onClick={() => {
                    navigator.clipboard?.writeText(newKeyToast.plaintext);
                    setNewKeyToast(null);
                  }}
                  className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold text-white"
                  style={{ background: ACCENT }}
                >
                  <Copy size={14} /> Copy & close
                </button>
              </div>
            </div>
          </div>
        )}

        {/* FEEDBACK POPUP */}
        {feedback && (
          <div className="absolute bottom-6 left-6 z-30 w-80 rounded-2xl border p-5" style={{ background: "#1a1817", borderColor: LINE }}>
            <div className="mb-3 flex items-center justify-between">
              <p className="font-semibold">Send feedback</p>
              <button onClick={() => setFeedback(false)} className="text-white/50 hover:text-white"><X size={20} /></button>
            </div>
            <textarea
              placeholder="What's on your mind?"
              rows={4}
              className="w-full resize-none rounded-xl border bg-transparent px-3 py-2 text-sm outline-none placeholder:text-white/40"
              style={{ borderColor: ACCENT_BORDER }}
            />
            <div className="mt-3 flex justify-end">
              <button className="rounded-xl px-5 py-2 text-sm font-medium" style={{ background: "rgba(255,255,255,0.1)" }}>Send</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
