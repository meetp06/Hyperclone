import { useState } from "react";
import {
    ChevronLeft, ChevronRight, MessageSquare, Plug, Bot, Zap, Brain,
    VenetianMask, Check, ChevronDown, ChevronUp, Plus, History, Send,
    Bold, Italic, Strikethrough, Code, Github, X, HelpCircle, LogOut,
    MoreVertical, ArrowUp, Inbox, Copy, Sparkles
} from "lucide-react";

const ACCENT = "#FF4A1C";
const ACCENT_SOFT = "rgba(255,74,28,0.13)";
const ACCENT_BORDER = "rgba(255,74,28,0.32)";
const PANEL = "#161413";
const CARD = "#161514";
const CARD_HOVER = "#1d1b1a";
const LINE = "rgba(255,255,255,0.07)";

function Toggle({ on, onClick }) {
    return (
        <button onClick={onClick}
            className="relative h-7 w-12 shrink-0 rounded-full transition-colors duration-200"
            style={{ background: on ? ACCENT : "rgba(255,255,255,0.13)" }}>
            <span className="absolute top-1 h-5 w-5 rounded-full bg-white shadow transition-all duration-200"
                style={{ left: on ? "26px" : "4px" }} />
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

function ConnectBtn({ label = "Connect", onClick }) {
    return (
        <button onClick={onClick}
            className="rounded-xl px-5 py-2 text-sm font-medium text-white transition-colors"
            style={{ background: "rgba(255,255,255,0.07)" }}
            onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.13)")}
            onMouseLeave={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.07)")}>
            {label}
        </button>
    );
}

function Title({ children }) {
    return (
        <div className="mb-8">
            <h1 className="text-5xl font-bold tracking-tight text-white">{children}</h1>
            <div className="mt-3 h-1 w-12 rounded-full" style={{ background: ACCENT }} />
        </div>
    );
}

function Tile({ bg = "#fff", color = "#000", children, icon: Icon }) {
    return (
        <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl text-sm font-bold"
            style={{ background: bg, color }}>
            {Icon ? <Icon size={22} /> : children}
        </div>
    );
}

const BRAND = (
    <div className="flex items-center gap-0.5 text-3xl font-black" style={{ color: ACCENT }}>
        <span>⊢</span><span className="-ml-1">⊣</span>
    </div>
);

export default function Pioneer() {
    const [view, setView] = useState("workspace");
    const [wsOpen, setWsOpen] = useState(false);
    const [incognito, setIncognito] = useState(true);
    const [drawer, setDrawer] = useState(false);
    const [feedback, setFeedback] = useState(false);
    const [auto, setAuto] = useState({ email: false, linkedin: true });
    const [rememberText, setRememberText] = useState("");
    const [memories, setMemories] = useState([
        { title: "MLE Role Information", role: "User role", who: "Meetkumar", when: "7m ago" },
    ]);
    const [chatInput, setChatInput] = useState("");
    const [chat, setChat] = useState([]);
    const [conns, setConns] = useState({
        notion: false, gdrive: false, gmail: false, gcal: false,
        granola: false, github: false, slack: false,
    });

    const hour = new Date().getHours();
    const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";

    const nav = [
        { id: "chat", label: "Chat", icon: MessageSquare },
        { id: "connectors", label: "Connectors", icon: Plug },
        { id: "agents", label: "Agents", icon: Bot },
        { id: "automations", label: "Automations", icon: Zap },
        { id: "remember", label: "Remember", icon: Brain },
    ];

    const go = (v) => { setView(v); setWsOpen(false); };

    const sendChat = () => {
        if (!chatInput.trim()) return;
        setChat((c) => [...c, { role: "user", text: chatInput },
        { role: "ai", text: "Pulling from your connected memory… here's what I found across Slack, Notion and Gmail." }]);
        setChatInput("");
    };

    const saveMemory = () => {
        if (!rememberText.trim()) return;
        setMemories((m) => [{ title: rememberText.slice(0, 32) || "New note", role: "Note", who: "Meetkumar", when: "just now" }, ...m]);
        setRememberText("");
        setDrawer(true);
    };

    const NavItem = ({ item }) => {
        const active = view === item.id;
        const Icon = item.icon;
        return (
            <button onClick={() => go(item.id)}
                className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-[15px] font-medium transition-colors"
                style={{
                    background: active ? ACCENT_SOFT : "transparent",
                    color: active ? ACCENT : "rgba(255,255,255,0.82)",
                }}
                onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = "rgba(255,255,255,0.05)"; }}
                onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = "transparent"; }}>
                <Icon size={19} /> {item.label}
            </button>
        );
    };

    return (
        <div className="flex h-screen w-full overflow-hidden font-sans text-white"
            style={{
                background: "#0b0a09",
                backgroundImage:
                    "radial-gradient(circle at 75% 25%, rgba(255,74,28,0.06), transparent 42%), radial-gradient(circle at 45% 85%, rgba(255,255,255,0.025), transparent 55%)",
            }}>

            {/* SIDEBAR */}
            <div className="flex shrink-0 flex-col p-4" style={{ width: 320 }}>
                <div className="flex flex-col rounded-2xl border p-2.5"
                    style={{ background: PANEL, borderColor: LINE }}>
                    <div className="mb-1 flex items-center gap-3 px-2 py-1.5 text-white/40">
                        <ChevronLeft size={20} /><ChevronRight size={20} />
                    </div>

                    {/* Workspace pill */}
                    <button onClick={() => go("workspace")}
                        className="flex items-center gap-3 rounded-xl px-2.5 py-2.5 transition-colors"
                        style={{
                            background: view === "workspace" ? ACCENT_SOFT : "transparent",
                            border: view === "workspace" ? `1px solid ${ACCENT_BORDER}` : "1px solid transparent",
                        }}>
                        <span className="flex h-9 w-9 items-center justify-center rounded-lg text-base font-bold"
                            style={{ background: view === "workspace" ? ACCENT : "rgba(255,255,255,0.1)", color: "#fff" }}>P</span>
                        <span className="text-[15px] font-semibold" style={{ color: view === "workspace" ? ACCENT : "#fff" }}>Personal</span>
                    </button>

                    <div className="mt-1 flex flex-col gap-0.5">
                        {nav.map((item) => <NavItem key={item.id} item={item} />)}
                        <div className="flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-[15px] font-medium text-white/82">
                            <span className="flex items-center gap-3"><VenetianMask size={19} /> Incognito</span>
                            <Toggle on={incognito} onClick={() => setIncognito((v) => !v)} />
                        </div>
                    </div>

                    <div className="my-2 h-px" style={{ background: LINE }} />

                    <button onClick={() => go("account")}
                        className="flex items-center gap-3 rounded-xl px-2.5 py-2.5 transition-colors"
                        style={{
                            background: view === "account" ? ACCENT_SOFT : "rgba(255,255,255,0.02)",
                            border: view === "account" ? `1px solid ${ACCENT_BORDER}` : "1px solid transparent",
                        }}>
                        <span className="flex h-9 w-9 items-center justify-center rounded-lg text-sm font-bold"
                            style={{ background: "linear-gradient(135deg,#7c5cff,#ff4a1c)" }}>MP</span>
                        <span className="text-[15px] font-semibold" style={{ color: view === "account" ? ACCENT : "#fff" }}>Meetkumar Patel</span>
                    </button>
                </div>

                <button onClick={() => setFeedback(true)}
                    className="mt-auto flex h-12 w-12 items-center justify-center rounded-full border text-white/60 transition-colors hover:text-white"
                    style={{ background: "rgba(255,255,255,0.03)", borderColor: LINE }}>
                    <HelpCircle size={22} />
                </button>
            </div>

            {/* MAIN */}
            <div className="relative flex-1 overflow-y-auto">
                <div className="mx-auto max-w-3xl px-6 py-12">

                    {/* WORKSPACE */}
                    {view === "workspace" && (
                        <>
                            <Title>Workspace</Title>
                            <div className="relative mb-4">
                                <button onClick={() => setWsOpen((v) => !v)}
                                    className="flex w-full items-center justify-between rounded-2xl border px-5 py-4"
                                    style={{ background: CARD, borderColor: LINE }}>
                                    <span className="flex items-center gap-3">
                                        <span className="flex h-9 w-9 items-center justify-center rounded-lg text-base font-bold" style={{ background: "rgba(255,255,255,0.1)" }}>P</span>
                                        <span className="text-lg font-semibold">Personal</span>
                                    </span>
                                    {wsOpen ? <ChevronUp size={22} className="text-white/50" /> : <ChevronDown size={22} className="text-white/50" />}
                                </button>
                                {wsOpen && (
                                    <div className="absolute z-10 mt-2 w-full overflow-hidden rounded-2xl border" style={{ background: "#1a1817", borderColor: LINE }}>
                                        <div className="flex items-center justify-between px-5 py-4" style={{ borderBottom: `1px solid ${LINE}` }}>
                                            <span className="flex items-center gap-3">
                                                <span className="flex h-9 w-9 items-center justify-center rounded-lg text-base font-bold" style={{ background: "rgba(255,255,255,0.1)" }}>P</span>
                                                <span className="text-lg font-semibold">Personal</span>
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
                                <p className="text-xl font-bold">Personal</p>
                                <p className="mt-1 text-white/55">Free · Resets Jun 30</p>
                            </div>

                            <div className="rounded-2xl border px-6 py-6" style={{ background: CARD, borderColor: LINE }}>
                                <p className="mb-5 text-xl font-bold">Usage</p>
                                <div className="mb-2 flex items-center justify-between text-[15px]">
                                    <span className="font-semibold">Resets Jun 30</span>
                                    <span className="font-bold">12,000 tokens / 1M tokens</span>
                                </div>
                                <div className="h-3 w-full overflow-hidden rounded-full" style={{ background: "rgba(255,255,255,0.08)" }}>
                                    <div className="h-full rounded-full" style={{ width: "4%", background: ACCENT }} />
                                </div>
                                <div className="mt-4 flex gap-6 text-sm text-white/70">
                                    {["LinkedIn", "Desktop chat", "MCP"].map((l) => (
                                        <span key={l} className="flex items-center gap-2"><span className="h-3 w-3 rounded" style={{ background: ACCENT }} /> {l}</span>
                                    ))}
                                </div>
                                <p className="mt-5 text-sm text-white/45">37 facts learned · 20 facts surfaced</p>
                            </div>
                        </>
                    )}

                    {/* CHAT */}
                    {view === "chat" && (
                        <div className="flex min-h-[70vh] flex-col items-center justify-center">
                            <h1 className="text-center text-6xl font-bold tracking-tight">{greeting}, Meetkumar</h1>
                            <div className="mt-2 h-1 w-12 rounded-full" style={{ background: ACCENT }} />
                            {chat.length === 0 ? (
                                <div className="mt-10 flex max-w-2xl flex-wrap justify-center gap-3">
                                    {["What is the team working on this sprint?", "What blockers are blocking progress?",
                                        "Who is assigned to the frontend project?", "What shipped last week?"].map((q) => (
                                            <button key={q} onClick={() => { setChatInput(q); }}
                                                className="rounded-full border px-5 py-3 text-[15px] text-white/85 transition-colors hover:bg-white/5"
                                                style={{ background: CARD, borderColor: LINE }}>{q}</button>
                                        ))}
                                </div>
                            ) : (
                                <div className="mt-8 w-full max-w-2xl space-y-3">
                                    {chat.map((m, i) => (
                                        <div key={i} className={`rounded-2xl border px-5 py-3 text-[15px] ${m.role === "user" ? "ml-auto max-w-[80%]" : "mr-auto max-w-[85%]"}`}
                                            style={{ background: m.role === "user" ? ACCENT_SOFT : CARD, borderColor: m.role === "user" ? ACCENT_BORDER : LINE }}>
                                            {m.text}
                                        </div>
                                    ))}
                                </div>
                            )}
                            <div className="mt-8 flex w-full max-w-2xl items-center gap-3 rounded-2xl border-2 px-4 py-3"
                                style={{ background: CARD, borderColor: ACCENT_BORDER }}>
                                <History size={22} className="shrink-0 text-white/45" />
                                <input value={chatInput} onChange={(e) => setChatInput(e.target.value)}
                                    onKeyDown={(e) => e.key === "Enter" && sendChat()}
                                    placeholder="Search or ask anything"
                                    className="flex-1 bg-transparent text-[15px] outline-none placeholder:text-white/40" />
                                <button onClick={sendChat} className="flex h-9 w-9 items-center justify-center rounded-full" style={{ background: "rgba(255,255,255,0.1)" }}>
                                    <ArrowUp size={20} />
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
                                    Connectors help our agents learn everything about your company. Once you connect, our agents ingest and synthesize all of the information across your tools and make it accessible inside Pioneer. Every new document, meeting and message is automatically ingested as long as the connection stays open.
                                </p>
                            </div>

                            {[
                                { id: "notion", name: "Notion", desc: "Pages and docs", bg: "#fff", color: "#000", letter: "N" },
                                { id: "gdrive", name: "Google Drive", desc: "Docs and sheets", bg: "#fff", color: "#1a73e8", letter: "▲" },
                                { id: "gmail", name: "Gmail", desc: "Inbox threads", bg: "#fff", color: "#ea4335", letter: "M" },
                                { id: "gcal", name: "Google Calendar", desc: "Meetings and events", bg: "#1a73e8", color: "#fff", letter: "31" },
                                { id: "granola", name: "Granola", desc: "Meeting notes", bg: "#b9d44a", color: "#1a2c00", letter: "G" },
                                { id: "github", name: "GitHub", desc: "Markdown in repos", bg: "#fff", color: "#000", icon: Github },
                            ].map((c) => (
                                <div key={c.id} className="mb-4 flex items-center justify-between rounded-2xl border px-5 py-4" style={{ background: CARD, borderColor: LINE }}>
                                    <div className="flex items-center gap-4">
                                        <Tile bg={c.bg} color={c.color} icon={c.icon}>{c.letter}</Tile>
                                        <div><p className="font-semibold">{c.name}</p><p className="text-sm text-white/50">{c.desc}</p></div>
                                    </div>
                                    {conns[c.id] ? <Connected /> : <ConnectBtn onClick={() => setConns((s) => ({ ...s, [c.id]: true }))} />}
                                </div>
                            ))}

                            {/* LinkedIn connected */}
                            <div className="mb-4 rounded-2xl border px-5 py-4" style={{ background: CARD, borderColor: LINE }}>
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-4">
                                        <Tile bg="#0a66c2" color="#fff">in</Tile>
                                        <div><p className="font-semibold">LinkedIn</p><p className="text-sm text-white/50">1 account connected</p></div>
                                    </div>
                                    <button className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium" style={{ background: "rgba(255,255,255,0.07)" }}><Plus size={16} /> Add account</button>
                                </div>
                                <div className="mt-4 flex items-center justify-between rounded-xl px-4 py-3" style={{ background: "rgba(255,255,255,0.04)" }}>
                                    <div className="flex items-center gap-3">
                                        <span className="flex h-7 w-7 items-center justify-center rounded text-xs font-bold" style={{ background: "linear-gradient(135deg,#7c5cff,#ff4a1c)" }}>MP</span>
                                        <span className="text-sm">meetp0006@gmail.com</span>
                                    </div>
                                    <div className="flex items-center gap-3 text-white/50"><Check size={18} style={{ color: "#4ade80" }} /><MoreVertical size={18} /></div>
                                </div>
                            </div>

                            <div className="mb-4 flex items-center justify-between rounded-2xl border px-5 py-4" style={{ background: CARD, borderColor: LINE }}>
                                <div className="flex items-center gap-4"><Tile bg="#fff" color="#611f69">#</Tile><div><p className="font-semibold">Slack</p><p className="text-sm text-white/50">Channel and DM history</p></div></div>
                                {conns.slack ? <Connected /> : <ConnectBtn onClick={() => setConns((s) => ({ ...s, slack: true }))} />}
                            </div>

                            <div className="flex items-center gap-3 rounded-2xl border px-5 py-4 text-white/45" style={{ background: CARD, borderColor: LINE }}>
                                <div className="flex gap-1.5">{Array.from({ length: 8 }).map((_, i) => (<span key={i} className="h-7 w-7 rounded-full" style={{ background: "rgba(255,255,255,0.08)" }} />))}</div>
                                <span className="text-sm">More coming soon</span>
                            </div>
                        </>
                    )}

                    {/* AGENTS */}
                    {view === "agents" && (
                        <>
                            <Title>Agents</Title>
                            <p className="mb-6 text-[15px] leading-relaxed text-white/70">Connect your AI tools so they can read and write to this workspace.</p>
                            <div className="mb-4 flex items-center gap-3 text-sm font-semibold uppercase tracking-wide text-white/50"><span className="h-1 w-6 rounded" style={{ background: ACCENT }} /> Chat</div>
                            {[
                                { name: "ChatGPT", desc: "OpenAI chat assistant", connected: false, bg: "#000", letter: "◎" },
                                { name: "Claude", desc: "Anthropic chat assistant", connected: true, bg: ACCENT, icon: Sparkles },
                            ].map((a) => (
                                <div key={a.name} className="mb-4 flex items-center justify-between rounded-2xl border px-5 py-4" style={{ background: CARD, borderColor: LINE }}>
                                    <div className="flex items-center gap-4"><Tile bg={a.bg} color="#fff" icon={a.icon}>{a.letter}</Tile><div><p className="font-semibold">{a.name}</p><p className="text-sm text-white/50">{a.desc}</p></div></div>
                                    {a.connected ? <Connected /> : <ConnectBtn />}
                                </div>
                            ))}

                            <div className="my-4 flex items-center gap-3 text-sm font-semibold uppercase tracking-wide text-white/50"><span className="h-1 w-6 rounded" style={{ background: ACCENT }} /> Agents</div>
                            {[
                                { name: "Claude Code", desc: "Terminal & IDE sessions", connected: true, bg: ACCENT, letter: "▦" },
                                { name: "Claude Cowork", desc: "Desktop agent for knowledge work", connected: true, bg: ACCENT, icon: Sparkles },
                                { name: "Cursor", desc: "AI code editor", connected: false, bg: "#222", letter: "◆" },
                                { name: "Codex", desc: "OpenAI terminal agent", connected: false, bg: "#6366f1", letter: "</>" },
                            ].map((a) => (
                                <div key={a.name} className="mb-4 flex items-center justify-between rounded-2xl border px-5 py-4" style={{ background: CARD, borderColor: LINE }}>
                                    <div className="flex items-center gap-4"><Tile bg={a.bg} color="#fff" icon={a.icon}>{a.letter}</Tile><div><p className="font-semibold">{a.name}</p><p className="text-sm text-white/50">{a.desc}</p></div></div>
                                    {a.connected ? <span className="flex items-center gap-3"><Connected /><MoreVertical size={18} className="text-white/40" /></span> : <ConnectBtn />}
                                </div>
                            ))}
                            <div className="mb-4 flex items-center justify-between rounded-2xl border px-5 py-4 opacity-70" style={{ background: CARD, borderColor: LINE }}>
                                <div className="flex items-center gap-4"><Tile bg="#7a1f1f" color="#fff">🦞</Tile><div><p className="font-semibold">OpenClaw</p><p className="text-sm text-white/50">Install to connect</p></div></div>
                                <span className="text-sm text-white/45">Not installed</span>
                            </div>

                            <div className="rounded-2xl border px-5 py-5" style={{ background: CARD, borderColor: LINE }}>
                                <div className="flex items-center justify-between">
                                    <div><p className="text-[15px] font-medium">Other tool? Paste as an MCP server</p><p className="mt-1 font-mono text-sm text-white/60">https://api.pioneer.ai/mcp</p></div>
                                    <button className="flex h-9 w-9 items-center justify-center rounded-lg" style={{ background: "rgba(255,255,255,0.07)" }}><Copy size={18} /></button>
                                </div>
                            </div>
                        </>
                    )}

                    {/* AUTOMATIONS */}
                    {view === "automations" && (
                        <>
                            <Title>Automations</Title>
                            <p className="mb-6 text-[15px] leading-relaxed text-white/70">Background tasks powered by your Pioneer memory. They run quietly and write back to your tools.</p>
                            <div className="mb-4 rounded-2xl border px-6 py-6 text-[15px] leading-relaxed text-white/70" style={{ background: CARD, borderColor: LINE }}>
                                <div className="mb-4 flex items-center gap-4">{BRAND}<div className="flex-1 space-y-2">{[1, 2, 3].map((i) => (<div key={i} className="h-1 rounded-full" style={{ width: `${70 + i * 8}%`, background: ACCENT }} />))}</div></div>
                                Automations use the connectors you already gave access to in order to do boring, repetitive work in the background 24/7, like drafting emails or replying to LinkedIn DMs.
                            </div>

                            <div className="mb-4 rounded-2xl border px-5 py-5" style={{ background: CARD, borderColor: LINE }}>
                                <div className="flex items-start justify-between gap-4">
                                    <div className="flex gap-4"><Tile bg="#fff" color="#ea4335">M</Tile>
                                        <div><p className="font-semibold">Draft replies to important work emails</p>
                                            <p className="mt-1 text-sm leading-relaxed text-white/55">Writes it in your voice using your past writing and information about your company pulled from Pioneer. Review and send later from Gmail.</p>
                                            <p className="mt-2 text-sm font-semibold">Starts by drafting replies to your last 30 days of emails.</p></div>
                                    </div>
                                    <Toggle on={auto.email} onClick={() => setAuto((a) => ({ ...a, email: !a.email }))} />
                                </div>
                            </div>

                            <div className="mb-4 rounded-2xl border px-5 py-5" style={{ background: CARD, borderColor: LINE }}>
                                <div className="flex items-start justify-between gap-4">
                                    <div className="flex gap-4"><Tile bg="#0a66c2" color="#fff">in</Tile>
                                        <div><p className="font-semibold">Draft replies to LinkedIn DMs</p>
                                            <p className="mt-1 text-sm leading-relaxed text-white/55">Writes LinkedIn DM replies in your voice using your past chats and your company info from Pioneer. Drafts open in the drawer for you to review, tweak and send.</p>
                                            <p className="mt-2 text-sm font-semibold">Starts by drafting replies to your last 30 days of LinkedIn DMs.</p>
                                            {auto.linkedin && (<button className="mt-3 flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium" style={{ background: "rgba(255,255,255,0.07)" }}><Inbox size={16} /> View drafts</button>)}
                                        </div>
                                    </div>
                                    <Toggle on={auto.linkedin} onClick={() => setAuto((a) => ({ ...a, linkedin: !a.linkedin }))} />
                                </div>
                            </div>
                        </>
                    )}

                    {/* REMEMBER */}
                    {view === "remember" && (
                        <>
                            <Title>Remember</Title>
                            <p className="mb-6 text-[15px] leading-relaxed text-white/70">Write or paste anything, and Pioneer will synthesize it into the shared memory for all your humans and AI tools.</p>
                            <div className="overflow-hidden rounded-2xl border" style={{ background: CARD, borderColor: LINE }}>
                                <div className="flex items-center gap-4 border-b px-5 py-3 text-white/55" style={{ borderColor: LINE }}>
                                    <Bold size={18} /><Italic size={18} /><Strikethrough size={18} /><Code size={18} />
                                </div>
                                <textarea value={rememberText} onChange={(e) => setRememberText(e.target.value)}
                                    placeholder="Start typing…" rows={12}
                                    className="w-full resize-none bg-transparent px-5 py-4 text-[15px] outline-none placeholder:text-white/30" />
                                <div className="flex items-center justify-between px-5 py-3">
                                    <button onClick={() => setDrawer(true)} className="text-white/50 hover:text-white"><History size={20} /></button>
                                    <button onClick={saveMemory} className="flex items-center gap-2 rounded-xl px-5 py-2.5 text-sm font-semibold" style={{ background: "rgba(255,255,255,0.1)" }}>
                                        <Send size={16} /> Remember
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
                                <button className="flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm font-medium" style={{ background: "rgba(255,255,255,0.07)" }}><LogOut size={16} /> Sign out</button>
                            </div>
                        </>
                    )}
                </div>

                {/* FILED MEMORIES DRAWER */}
                {drawer && (
                    <div className="absolute right-0 top-0 z-20 h-full w-[420px] border-l p-6" style={{ background: "#0d0c0b", borderColor: LINE }}>
                        <button onClick={() => setDrawer(false)} className="mb-6 flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium" style={{ background: "rgba(255,255,255,0.07)" }}>
                            <ChevronLeft size={18} /> Close
                        </button>
                        <h2 className="mb-4 text-4xl font-bold">Filed memories</h2>
                        <div className="mb-3 flex items-center gap-3 text-sm font-semibold uppercase tracking-wide text-white/50"><span className="h-1 w-6 rounded" style={{ background: ACCENT }} /> Today</div>
                        <div className="space-y-3">
                            {memories.map((m, i) => (
                                <div key={i} className="rounded-2xl border px-5 py-4" style={{ background: CARD, borderColor: LINE }}>
                                    <p className="flex items-center gap-2 font-semibold"><Brain size={18} style={{ color: ACCENT }} /> {m.title}</p>
                                    <p className="mt-1 text-sm text-white/55">{m.role}</p>
                                    <div className="mt-3 flex items-center justify-between text-sm text-white/50">
                                        <span className="flex items-center gap-2"><span className="h-5 w-5 rounded" style={{ background: "linear-gradient(135deg,#7c5cff,#ff4a1c)" }} /> {m.who}</span>
                                        <span>{m.when}</span>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                )}

                {/* FEEDBACK POPUP */}
                {feedback && (
                    <div className="absolute bottom-6 left-6 z-30 w-80 rounded-2xl border p-5" style={{ background: "#1a1817", borderColor: LINE }}>
                        <div className="mb-3 flex items-center justify-between"><p className="font-semibold">Send feedback</p><button onClick={() => setFeedback(false)} className="text-white/50 hover:text-white"><X size={20} /></button></div>
                        <textarea placeholder="What's on your mind?" rows={4} className="w-full resize-none rounded-xl border bg-transparent px-3 py-2 text-sm outline-none placeholder:text-white/40" style={{ borderColor: ACCENT_BORDER }} />
                        <div className="mt-3 flex justify-end"><button className="rounded-xl px-5 py-2 text-sm font-medium" style={{ background: "rgba(255,255,255,0.1)" }}>Send</button></div>
                    </div>
                )}
            </div>
        </div>
    );
}