import { useEffect, useRef, useState } from "react";
import ModelPicker from "./ModelPicker";
import { ToolStep, md } from "./CodePage";
import { ApprovalCard } from "./CoworkPage";
import { runStream } from "../utils/runs";
import { SendIcon, StopIcon } from "./Icons";
import TabDrawer, { MenuButton } from "./TabDrawer";
import VoiceInput from "./VoiceInput";

const API = import.meta.env.VITE_API_URL || "";
const CHAT_KEY = id => `semblance_bot_chat_${id}`;
const IDEAS = ["A WhatsApp bot for my bakery: menu, prices, opening hours, take orders",
    "A study buddy that quizzes me and explains things simply",
    "A personal assistant that checks my calendar and email for me"];
const TOOL_LABELS = {
    web_search: "Search the web", fetch_url: "Read web pages", deep_research: "Deep research",
    search_memory: "Your Sem memory", gmail_search: "Search your Gmail", gmail_read: "Read your email",
    gmail_send: "Send email (asks you)", calendar_list: "See your calendar", calendar_create: "Add events (asks you)",
    drive_list: "List your Drive", drive_read: "Read your Drive", drive_create_note: "Write Drive notes",
    drive_append_note: "Add to Drive notes", set_reminder: "Set reminders", list_reminders: "See reminders",
    contacts_search: "Your contacts", generate_image: "Make images (app only)",
};
const card = { border: "1px solid var(--border)", borderRadius: "16px", padding: "14px", background: "var(--bg)" };
const btn = { padding: "8px 12px", borderRadius: "999px", border: "1px solid var(--border)", background: "var(--surface)",
    color: "var(--text)", fontSize: "13px", fontWeight: 600, cursor: "pointer" };
const primary = { ...btn, background: "var(--accent)", color: "var(--accent-contrast)", border: "none" };
const field = { width: "100%", padding: "10px 12px", borderRadius: "12px", border: "1px solid var(--border)",
    background: "var(--surface)", color: "var(--text)", fontSize: "14px", fontFamily: "inherit", boxSizing: "border-box" };
const hint = { fontSize: "12px", color: "var(--text-muted)", lineHeight: 1.5 };

function loadChat(id) { try { return JSON.parse(localStorage.getItem(CHAT_KEY(id))) || []; } catch { return []; } }
function saveChat(id, items) {
    try { localStorage.setItem(CHAT_KEY(id), JSON.stringify(items.filter(i => i.kind !== "image").slice(-150))); } catch { /* full */ }
}

// The bot's settings: personality, tools, model, and its WhatsApp number.
function BotEditor({ bot, tools, headers, onSaved, onDelete, onClose }) {
    const [form, setForm] = useState(bot);
    const [wa, setWa] = useState({ phone_number_id: bot.whatsapp?.phone_number_id || "", token: "", app_secret: "",
        trusted: (bot.whatsapp?.trusted || []).join(", ") });
    const [msg, setMsg] = useState("");
    const [saving, setSaving] = useState(false);
    const set = (k, v) => setForm(f => ({ ...f, [k]: v }));
    const toggleTool = t => set("tools", form.tools.includes(t) ? form.tools.filter(x => x !== t) : [...form.tools, t]);
    const call = async (path, method, body) => {
        setSaving(true); setMsg("");
        try {
            const r = await fetch(`${API}${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined });
            const d = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(d.detail || `Failed (${r.status})`);
            return d;
        } catch (e) { setMsg(e.message); return null; } finally { setSaving(false); }
    };
    const save = async () => {
        const d = await call(`/bots/${bot.id}`, "PUT", form);
        if (d) { onSaved(d); setMsg("Saved."); }
    };
    const connect = async () => {
        const d = await call(`/bots/${bot.id}/whatsapp`, "POST", { ...wa, trusted: wa.trusted.split(/[,\s]+/).filter(Boolean) });
        if (d) { onSaved(d); setForm(d); setWa(w => ({ ...w, token: "", app_secret: "" })); setMsg("Connected to WhatsApp. Now paste the webhook details into Meta (below)."); }
    };
    const disconnect = async () => { const d = await call(`/bots/${bot.id}/whatsapp`, "DELETE"); if (d) { onSaved(d); setForm(d); } };
    const w = form.whatsapp || {};
    const group = (title, list) => (
        <div><div style={{ ...hint, fontWeight: 700, margin: "6px 0 4px" }}>{title}</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                {list.map(t => (
                    <button key={t} onClick={() => toggleTool(t)} aria-pressed={form.tools.includes(t)} className={`ds-chip${form.tools.includes(t) ? " is-selected" : ""}`}>
                        {TOOL_LABELS[t] || t}</button>
                ))}
            </div></div>
    );
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            <div style={card}>
                <div style={{ display: "flex", gap: "8px" }}>
                    <input style={{ ...field, width: "64px", textAlign: "center", fontSize: "20px" }} value={form.emoji} onChange={e => set("emoji", e.target.value)} aria-label="Emoji" />
                    <input style={field} value={form.name} onChange={e => set("name", e.target.value)} placeholder="Bot name" />
                </div>
                <input style={{ ...field, marginTop: "8px" }} value={form.about} onChange={e => set("about", e.target.value)} placeholder="One line about it" />
                <div style={{ ...hint, margin: "10px 0 4px" }}>Instructions: who it serves, how it talks, what it knows and must not do</div>
                <textarea style={{ ...field, minHeight: "160px" }} value={form.instructions} onChange={e => set("instructions", e.target.value)} />
                <input style={{ ...field, marginTop: "8px" }} value={form.greeting} onChange={e => set("greeting", e.target.value)} placeholder="Greeting (its first message)" />
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginTop: "8px" }}>
                    <span style={hint}>Model</span>
                    <ModelPicker token={headers.Authorization.slice(7)} value={form.model} onChange={v => set("model", v)} storageKey={`semblance_bot_model_${bot.id}`} />
                </div>
            </div>
            <div style={card}>
                <div style={{ fontWeight: 700 }}>What it can use</div>
                {group("Public (safe for anyone, incl. WhatsApp)", tools.public)}
                {group("Your own data (only you in the app, or trusted WhatsApp numbers)", tools.private)}
                {group("App only", tools.app_only)}
            </div>
            <div style={card}>
                <div style={{ fontWeight: 700 }}>WhatsApp {w.connected ? `· on ${w.display_number || w.phone_number_id}` : ""}</div>
                {!w.connected && <div style={hint}>From Meta → your app → WhatsApp → API setup: the Phone number ID and a permanent access token (System User). App secret: App settings → Basic.</div>}
                <input style={{ ...field, marginTop: "8px" }} value={wa.phone_number_id} onChange={e => setWa({ ...wa, phone_number_id: e.target.value })} placeholder="Phone number ID" />
                <input style={{ ...field, marginTop: "8px" }} type="password" value={wa.token} onChange={e => setWa({ ...wa, token: e.target.value })} placeholder={w.connected ? "Access token (saved; type to replace)" : "Access token"} />
                <input style={{ ...field, marginTop: "8px" }} type="password" value={wa.app_secret} onChange={e => setWa({ ...wa, app_secret: e.target.value })} placeholder={w.connected ? "App secret (saved; type to replace)" : "App secret"} />
                <input style={{ ...field, marginTop: "8px" }} value={wa.trusted} onChange={e => setWa({ ...wa, trusted: e.target.value })} placeholder="Trusted numbers (e.g. 27821234567), may use your data" />
                <div style={{ display: "flex", gap: "8px", marginTop: "8px", flexWrap: "wrap" }}>
                    <button style={primary} onClick={connect} disabled={saving || !wa.phone_number_id}>{w.connected ? "Update WhatsApp" : "Connect WhatsApp"}</button>
                    {w.connected && <button style={btn} onClick={disconnect} disabled={saving}>Disconnect</button>}
                </div>
                {w.connected && (
                    <div style={{ ...hint, marginTop: "10px" }}>
                        In Meta → WhatsApp → Configuration → Webhook, set:<br />
                        Callback URL: <code style={{ userSelect: "all", wordBreak: "break-all" }}>{w.webhook_url}</code><br />
                        Verify token: <code style={{ userSelect: "all" }}>{w.verify_token}</code><br />
                        Then subscribe to <b>messages</b>. Strangers only get public tools; nothing that needs your approval runs on WhatsApp.
                    </div>
                )}
            </div>
            {msg && <div style={hint}>{msg}</div>}
            <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
                <button style={primary} onClick={save} disabled={saving}>Save</button>
                <button style={btn} onClick={onClose}>Back to chat</button>
                <span style={{ flex: 1 }} />
                <button style={{ ...btn, color: "var(--danger)" }} onClick={() => window.confirm(`Delete ${bot.name}?`) && onDelete()}>Delete bot</button>
            </div>
        </div>
    );
}

function BotChat({ bot, headers, onUnauthorized }) {
    const [items, setItemsState] = useState(() => loadChat(bot.id));
    const [input, setInput] = useState("");
    const [busy, setBusy] = useState(false);
    const abortRef = useRef(null);
    const endRef = useRef(null);
    const setItems = fn => setItemsState(it => { const next = fn(it); saveChat(bot.id, next); return next; });
    useEffect(() => { setItemsState(loadChat(bot.id)); }, [bot.id]);
    useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [items, busy]);

    const apply = ev => {
        if (ev.type === "text") setItems(it => [...it, { kind: "text", text: ev.text }]);
        else if (ev.type === "tool") setItems(it => [...it, { kind: "tool", id: ev.id, name: ev.name, args: ev.args }]);
        else if (ev.type === "result") setItems(it => it.map(i => (i.kind === "tool" && i.id === ev.id && i.ok === undefined ? { ...i, ok: ev.ok, output: ev.output } : i)));
        else if (ev.type === "approval") setItems(it => [...it, { kind: "approval", id: ev.id, name: ev.name, args: ev.args, summary: ev.summary, state: "pending" }]);
        else if (ev.type === "image") setItems(it => [...it, { kind: "image", id: ev.id, mime: ev.mime, base64: ev.base64 }]);
        else if (ev.type === "error") setItems(it => [...it, { kind: "error", text: ev.text }]);
    };
    const send = async () => {
        const message = input.trim();
        if (!message || busy) return;
        const history = items.filter(i => i.kind === "user" || i.kind === "text")
            .map(i => ({ role: i.kind === "user" ? "user" : "assistant", content: i.text })).slice(-20);
        setItems(it => [...it, { kind: "user", text: message }]);
        setInput(""); setBusy(true);
        abortRef.current = new AbortController();
        try {
            const r = await runStream(`/bots/${bot.id}/chat`, { headers, signal: abortRef.current.signal,
                body: { message, history, chat_id: `bot-${bot.id}` }, onEvent: apply });
            if (r.status === 401) { onUnauthorized(); return; }
            if (r.error) throw new Error(r.error);
        } catch (e) { if (e.name !== "AbortError") setItems(it => [...it, { kind: "error", text: e.message }]); }
        setBusy(false);
    };
    const decide = async (id, decision) => {
        const item = items.find(i => i.kind === "approval" && i.id === id);
        let state = decision;
        if (decision === "approved" && item) {
            try {
                const r = await fetch(`${API}/cowork/execute`, { method: "POST", headers, body: JSON.stringify({ name: item.name, args: item.args, chat_id: `bot-${bot.id}` }) });
                const d = await r.json().catch(() => ({}));
                state = r.ok ? "done" : (d.detail || `Failed (${r.status})`);
            } catch (e) { state = e.message; }
        }
        setItems(it => it.map(i => (i.kind === "approval" && i.id === id ? { ...i, state } : i)));
        return state;
    };
    return (<>
        <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px 24px" }}>
            <div style={{ maxWidth: "820px", margin: "0 auto", display: "flex", flexDirection: "column", gap: "10px" }}>
                {bot.greeting && <div className="msg-assistant" dangerouslySetInnerHTML={{ __html: md(bot.greeting) }} />}
                {!items.length && <div style={{ ...hint, textAlign: "center" }}>Test {bot.name} here. It uses every tool you gave it; on WhatsApp strangers only get the public ones.</div>}
                {items.map((i, n) => (
                    i.kind === "user" ? <div key={n} className="msg-user" style={{ alignSelf: "flex-end", maxWidth: "85%", background: "var(--surface)", padding: "8px 12px", borderRadius: "14px" }}>{i.text}</div>
                    : i.kind === "text" ? <div key={n} className="msg-assistant" dangerouslySetInnerHTML={{ __html: md(i.text) }} />
                    : i.kind === "tool" ? <ToolStep key={n} item={i} />
                    : i.kind === "approval" ? <ApprovalCard key={n} item={i} onDecide={decide} />
                    : i.kind === "image" ? <img key={n} alt="" src={`data:${i.mime};base64,${i.base64}`} style={{ maxWidth: "320px", borderRadius: "12px" }} />
                    : <div key={n} className="msg-error">{i.text}</div>
                ))}
                {busy && <div style={hint}>{bot.emoji} {bot.name} is working…</div>}
                <div ref={endRef} />
            </div>
        </div>
        <div style={{ padding: "8px 16px max(12px, env(safe-area-inset-bottom))", borderTop: "1px solid var(--border)" }}>
            <div style={{ maxWidth: "820px", margin: "0 auto", display: "flex", gap: "8px", alignItems: "flex-end" }}>
                <textarea rows={1} value={input} onChange={e => setInput(e.target.value)} placeholder={`Message ${bot.name}`}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && window.matchMedia("(pointer: fine)").matches) { e.preventDefault(); send(); } }}
                    style={{ ...field, resize: "none", maxHeight: "140px" }} />
                <VoiceInput value={input} onChange={setInput} />
                {busy ? <button style={primary} onClick={() => abortRef.current?.abort()} aria-label="Stop"><StopIcon size={16} /></button>
                    : <button style={primary} onClick={send} disabled={!input.trim()} aria-label="Send"><SendIcon size={16} /></button>}
                {items.length > 0 && !busy && <button style={btn} onClick={() => setItems(() => [])} title="Clear this test chat">Clear</button>}
            </div>
        </div>
    </>);
}

// Bots tab: a BotFather for your own assistants. Describe a bot in a sentence, Sem drafts it, you tweak its
// personality and tools, test it here, and put it on a WhatsApp number.
export default function BotsPage({ token, onNavigate, onUnauthorized }) {
    const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
    const [bots, setBots] = useState(null);
    const [tools, setTools] = useState({ public: [], private: [], app_only: [] });
    const [current, setCurrent] = useState(null);
    const [editing, setEditing] = useState(false);
    const [menuOpen, setMenuOpen] = useState(false);
    const [idea, setIdea] = useState("");
    const [working, setWorking] = useState("");
    const [error, setError] = useState("");

    const load = async () => {
        const r = await fetch(`${API}/bots`, { headers });
        if (r.status === 401) { onUnauthorized(); return; }
        const d = await r.json().catch(() => ({ bots: [] }));
        setBots(d.bots || []); if (d.tools) setTools(d.tools);
    };
    useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    const bot = bots?.find(b => b.id === current) || null;

    const create = async () => {
        if (!idea.trim()) return;
        setWorking("Drafting your bot…"); setError("");
        try {
            const r = await fetch(`${API}/bots/draft`, { method: "POST", headers, body: JSON.stringify({ description: idea }) });
            const d = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(d.detail || `Failed (${r.status})`);
            const c = await fetch(`${API}/bots`, { method: "POST", headers, body: JSON.stringify(d.bot) });
            const made = await c.json().catch(() => ({}));
            if (!c.ok) throw new Error(made.detail || `Failed (${c.status})`);
            setBots(b => [made, ...(b || [])]); setCurrent(made.id); setEditing(true); setIdea("");
        } catch (e) { setError(e.message); } finally { setWorking(""); }
    };
    const saved = b => setBots(list => list.map(x => (x.id === b.id ? b : x)));
    const removeId = async (id) => {
        await fetch(`${API}/bots/${id}`, { method: "DELETE", headers });
        try { localStorage.removeItem(CHAT_KEY(id)); } catch { /* private mode */ }
        setBots(list => list.filter(x => x.id !== id));
        if (current === id) { setCurrent(null); setEditing(false); }
    };
    const remove = () => removeId(bot.id);

    return (
        <div style={{ position: "fixed", inset: 0, background: "var(--bg)", zIndex: 25, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
                <MenuButton onClick={() => setMenuOpen(true)} />
                {bot ? (<>
                    <button style={{ ...btn, padding: "4px 10px" }} onClick={() => { setCurrent(null); setEditing(false); }}>‹ Bots</button>
                    <span style={{ fontWeight: 700, color: "var(--text)", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{bot.emoji} {bot.name}</span>
                    {bot.whatsapp?.connected && <span style={hint}>· WhatsApp</span>}
                    <span style={{ flex: 1 }} />
                    <button style={btn} onClick={() => setEditing(e => !e)}>{editing ? "Chat" : "Settings"}</button>
                </>) : <span style={{ fontWeight: 700, color: "var(--text)" }}>Sem Bots</span>}
            </div>
            <TabDrawer open={menuOpen} onClose={() => setMenuOpen(false)} title="Sem Bots" current="bots" onNavigate={onNavigate}
                newLabel="+ New bot" onNew={() => { setCurrent(null); setEditing(false); }}
                chats={(bots || []).map(b => ({ id: b.id, title: `${b.emoji} ${b.name}`, updated: (b.updated || 0) * 1000 }))}
                activeId={current} onSelect={id => { setCurrent(id); setEditing(false); }} onDelete={removeId}
                subtitle={c => (bots?.find(b => b.id === c.id)?.whatsapp?.connected ? "On WhatsApp" : "")} />

            {bot && !editing && <BotChat bot={bot} headers={headers} onUnauthorized={onUnauthorized} />}
            {(!bot || editing) && (
                <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px 32px" }}>
                    <div style={{ maxWidth: "820px", margin: "0 auto", display: "flex", flexDirection: "column", gap: "14px" }}>
                        {bot && editing ? (
                            <BotEditor key={bot.id} bot={bot} tools={tools} headers={headers} onSaved={saved} onDelete={remove} onClose={() => setEditing(false)} />
                        ) : (<>
                            <div style={card}>
                                <div style={{ fontWeight: 700, fontSize: "18px" }}>Make a bot</div>
                                <div style={{ ...hint, margin: "4px 0 10px" }}>Describe it in a sentence: Sem writes its name, personality and picks its tools. You can change everything after.</div>
                                <textarea style={{ ...field, minHeight: "70px" }} value={idea} onChange={e => setIdea(e.target.value)} placeholder="e.g. A WhatsApp bot for my bakery that answers questions and takes orders" />
                                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", margin: "8px 0" }}>
                                    {IDEAS.map(s => <button key={s} className="ds-chip" onClick={() => setIdea(s)}>{s}</button>)}
                                </div>
                                <button style={primary} onClick={create} disabled={!idea.trim() || !!working}>{working || "Create bot"}</button>
                                {error && <div style={{ ...hint, color: "var(--danger)", marginTop: "6px" }}>{error}</div>}
                            </div>
                            {bots === null && <div style={hint}>Loading your bots…</div>}
                            {bots?.map(b => (
                                <button key={b.id} onClick={() => setCurrent(b.id)} style={{ ...card, textAlign: "left", cursor: "pointer", color: "var(--text)" }}>
                                    <div style={{ fontWeight: 700 }}>{b.emoji} {b.name}</div>
                                    <div style={hint}>{b.about || "No description"}{b.whatsapp?.connected ? ` · On WhatsApp ${b.whatsapp.display_number || ""}` : ""}</div>
                                </button>
                            ))}
                        </>)}
                    </div>
                </div>
            )}
        </div>
    );
}
