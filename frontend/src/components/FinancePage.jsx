import { useEffect, useRef, useState } from "react";
import VoiceMode, { VoiceModeButton } from "./VoiceMode";
import { TabWorking } from "./Working";
import ModelPicker, { loadModel } from "./ModelPicker";
import { ToolStep, md } from "./CodePage";
import { readEvents } from "../utils/sse";
import { AUTO_COMPACT_AT, ContextRing, compactItems, useContextBudget, AssistantText, AttachedChips, QueuedMessages, turnReplies, useSendQueue, CLEAR_COMMAND, ChatMenu, ConnectorsSheet, HELP_COMMAND, NEW_COMMAND, PlusMenu, SuggestModel, errorClass, helpText, parseSlash, readTextFiles, withAttachments } from "./MessageKit";
import { HeaderStatus } from "./StatusBar";
import { SendIcon, StopIcon } from "./Icons";
import AgentFeedPanel from "./AgentFeedPanel";
import useAgentFeed from "../hooks/useAgentFeed";
import VoiceInput from "./VoiceInput";
import TabDrawer, { HandoffCard, MenuButton } from "./TabDrawer";
import useTabChats from "../hooks/useTabChats";

const API = import.meta.env.VITE_API_URL || "";
const STORE_KEY = "semblance_finance_chats";
const OLD_KEY = "semblance_finance_items";

const btn = {
    padding: "8px 12px", borderRadius: "10px", border: "1px solid var(--border)", background: "var(--surface)",
    color: "var(--text)", fontSize: "13px", fontWeight: 600, cursor: "pointer",
};
const field = {
    width: "100%", padding: "9px 11px", borderRadius: "10px", border: "1px solid var(--border)",
    background: "var(--surface)", color: "var(--text)", fontSize: "14px", boxSizing: "border-box",
};
const SUGGESTIONS = [
    "What's my net worth and how did it move this month?",
    "Am I beating the Satrix 40?",
    "Where did my money go last month?",
    "Which dividends are coming up?",
    "How are the rand and the JSE doing today?",
];

function loadItems() {
    try { return JSON.parse(localStorage.getItem(OLD_KEY)) || []; } catch { return []; }
}

function Connect({ headers, onConnected }) {
    const [url, setUrl] = useState("");
    const [key, setKey] = useState("");
    const [msg, setMsg] = useState("");
    const [busy, setBusy] = useState(false);
    const connect = async () => {
        setBusy(true); setMsg("Connecting…");
        const r = await fetch(`${API}/finance/connect`, { method: "POST", headers, body: JSON.stringify({ url, key }) });
        const d = await r.json().catch(() => ({}));
        setBusy(false);
        if (!r.ok) { setMsg(d.detail || `Failed (${r.status})`); return; }
        onConnected();
    };
    return (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            <div style={{ fontSize: "14px", color: "var(--text-muted)", lineHeight: 1.5 }}>
                Connect C-Lab to ask about your portfolio, spending, property and markets. In C-Lab open
                <b> Profile → Connect apps</b>, create a key, and paste the address and key here. Sem can only read — it can't change anything in C-Lab.
            </div>
            <input value={url} onChange={e => setUrl(e.target.value)} placeholder="C-Lab address, e.g. https://….lambda-url.eu-west-1.on.aws/mcp" style={field} />
            <input value={key} onChange={e => setKey(e.target.value)} placeholder="clab_… key" type="password" style={field} />
            <button className="btn-primary" onClick={connect} disabled={busy || !url || !key} style={{ ...btn, alignSelf: "flex-start", background: "var(--accent)", color: "var(--accent-contrast)", border: "none" }}>Connect C-Lab</button>
            {msg && <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>{msg}</div>}
        </div>
    );
}

// Finance tab: ask about your own money. Answers come from C-Lab over MCP
// (read-only), with web search for outside context.
export default function FinancePage({ token, onNavigate, onUnauthorized, handoff, onHandoff }) {
    const [status, setStatus] = useState(null);
    const { chats, chat, updateChat, newChat, selectChat, deleteChat } = useTabChats(STORE_KEY, {
        blank: () => ({ items: [] }),
        legacy: () => { const items = loadItems(); return { items, title: items.find(i => i.kind === "user")?.text.slice(0, 60) || "" }; },
        persist: c => ({ ...c, items: (c.items || []).slice(-200) }),
    });
    const items = chat.items;
    const setItems = fn => updateChat(chat.id, x => ({ items: fn(x.items) }));
    const [menuOpen, setMenuOpen] = useState(false);
    // The activity icon shows this chat's own log (tools, MCP calls, models, errors).
    const feed = useAgentFeed(`finance:${chat.id}`, token);
    const [feedOpen, setFeedOpen] = useState(false);
    const [input, setInput] = useState("");
    const [files, setFiles] = useState([]);
    const [connectorsOpen, setConnectorsOpen] = useState(false);
    const COMMANDS = [
        { name: "networth", help: "Net worth and how it moved" },
        { name: "spending", help: "Where the money went last month" },
        NEW_COMMAND, CLEAR_COMMAND, HELP_COMMAND,
    ];
    const takenHandoff = useRef(0);
    useEffect(() => {
        if (handoff?.view !== "finance" || takenHandoff.current === handoff.at) return;
        takenHandoff.current = handoff.at;
        newChat(); setInput(handoff.task);
    }, [handoff]); // eslint-disable-line react-hooks/exhaustive-deps
    const [busy, setBusy] = useState(false);
    const liveFrom = useRef(Infinity);
    const [voiceOn, setVoiceOn] = useState(false);
    const [tokens, setTokens] = useState(0);
    useEffect(() => { liveFrom.current = Infinity; }, [chat.id]);
    const [model, setModel] = useState(() => loadModel("semblance_finance_model"));
    const budget = useContextBudget(items, model, token);
    const [compacting, setCompacting] = useState(false);
    // Older messages become one summary; runs by itself before a message when the ring passes 80%.
    const compactNow = async () => {
        setCompacting(true);
        try {
            const next = await compactItems(items, model, headers);
            if (next) updateChat(chat.id, () => ({ items: next }));
            return next;
        } catch (e) {
            setItems(it => [...it, { kind: "error", text: e.message }]);
            return null;
        } finally { setCompacting(false); }
    };
    const abortRef = useRef(null);
    const endRef = useRef(null);
    const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

    const refresh = () => fetch(`${API}/finance/status`, { headers })
        .then(r => { if (r.status === 401) onUnauthorized(); return r.json(); })
        .then(setStatus).catch(() => setStatus({ connected: false }));
    useEffect(() => { refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [items, busy]);

    const runCommand = (name, rest = "") => {
        if (name === "help") return setItems(it => [...it, { kind: "text", text: helpText(COMMANDS) }]);
        if (name === "new") return newChat();
        if (name === "clear") return setItems(() => []);
        if (name === "networth") return run("What's my net worth and how did it move this month?");
        if (name === "spending") return run("Where did my money go last month?");
    };
    const addFiles = async (list) => {
        const { added, error } = await readTextFiles(list);
        setFiles(x => [...x, ...added].slice(0, 8));
        if (error) setItems(it => [...it, { kind: "error", text: error }]);
    };
    const transcript = items.filter(i => i.kind === "user" || i.kind === "text")
        .map(i => ({ role: i.kind === "user" ? "user" : "assistant", text: i.text }));

    const run = async (message, useModel = model) => {
        if (!message.trim() || busy) return;
        liveFrom.current = items.length;
        setTokens(0);
        const slash = parseSlash(message, COMMANDS);
        if (slash) { setInput(""); return runCommand(slash.cmd.name, slash.rest); }
        const sent = withAttachments(message, files);
        const attached = files.map(f => f.name);
        setFiles([]);
        const chatId = chat.id;
        const add = fn => updateChat(chatId, x => ({ items: fn(x.items) }));
        if (!items.length) updateChat(chatId, () => ({ title: message.slice(0, 60) }));
        let base = items;
        if (budget.pct >= AUTO_COMPACT_AT && !compacting) base = (await compactNow()) || items;
        const history = base.filter(i => i.kind === "user" || i.kind === "text")
            .map(i => ({ role: i.kind === "user" ? "user" : "assistant", content: i.text })).slice(-20);
        add(it => [...it, { kind: "user", text: attached.length ? `${message}\nAttached: ${attached.join(", ")}` : message }]);
        setInput(""); setBusy(true);
        abortRef.current = new AbortController();
        try {
            const res = await fetch(`${API}/finance/run`, {
                method: "POST", headers, signal: abortRef.current.signal, body: JSON.stringify({ message: sent, history, model: useModel, chat_id: chatId }),
            });
            if (res.status === 401) { onUnauthorized(); return; }
            if (!res.ok || !res.body) throw new Error((await res.json().catch(() => ({}))).detail || `Request failed: ${res.status}`);
            await readEvents(res, (ev) => {
                if (ev.type === "usage") setTokens(ev.tokens);
                else if (ev.type === "text") add(it => [...it, { kind: "text", text: ev.text }]);
                else if (ev.type === "tool") add(it => [...it, { kind: "tool", id: ev.id, name: ev.name.replace("mcp__clab__", "c-lab: "), args: ev.args }]);
                else if (ev.type === "result") add(it => it.map(i => (i.kind === "tool" && i.id === ev.id && i.ok === undefined ? { ...i, ok: ev.ok, output: ev.output } : i)));
                else if (ev.type === "handoff") add(it => [...it, { kind: "handoff", tab: ev.tab, task: ev.task }]);
                else if (ev.type === "error") add(it => [...it, { kind: "error", text: ev.text, suggest: ev.suggest, retry: message }]);
            });
        } catch (e) {
            if (e.name !== "AbortError") add(it => [...it, { kind: "error", text: e.message }]);
        }
        setBusy(false);
    };
    const { queue, enqueue, remove: unqueue } = useSendQueue(busy, (m) => run(m));
    const submit = () => {
        if (!busy) return run(input);
        enqueue(input);
        setInput("");
    };

    return (
        <div style={{ position: "fixed", inset: 0, background: "var(--bg)", zIndex: 25, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                <MenuButton onClick={() => setMenuOpen(true)} />
                <span style={{ fontWeight: 700, color: "var(--text)", flex: 1 }}>Sem Finance</span>
                <HeaderStatus token={token} onFeed={() => { setFeedOpen(true); feed.acknowledgeErrors(); }} hasError={feed.hasError} busy={busy} />
                <ChatMenu title={chat.title || "Sem Finance"} messages={transcript} />
                {status?.connected && <span title="C-Lab connected" style={{ width: "7px", height: "7px", borderRadius: "50%", background: "var(--ready)", display: "inline-block" }} />}
            </div>

            <AgentFeedPanel open={feedOpen} onClose={() => setFeedOpen(false)} events={feed.events}
                title={`Activity · ${chat.title || "New chat"}`} />
            <TabDrawer open={menuOpen} onClose={() => setMenuOpen(false)} title="Sem Finance" current="finance"
                onNavigate={onNavigate} onNew={() => newChat()} chats={chats} activeId={chat.id} disabled={busy}
                onSelect={selectChat} onDelete={deleteChat} />

            <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>
                {status === null && <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>Checking C-Lab…</div>}
                {status && !status.connected && (
                    <>
                        {status.error && <div style={{ color: "var(--danger)", fontSize: "12px", marginBottom: "8px" }}>C-Lab didn't answer: {status.error}</div>}
                        <Connect headers={headers} onConnected={refresh} />
                    </>
                )}
                {status?.connected && items.length === 0 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                        {SUGGESTIONS.map(s => <button key={s} onClick={() => run(s)} style={{ ...btn, textAlign: "left", fontWeight: 400 }}>{s}</button>)}
                        <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>A tracker, not financial advice.</div>
                    </div>
                )}
                {(() => { const replies = turnReplies(items, busy); return items.map((item, i) => {
                    if (item.kind === "tool") return <ToolStep key={i} item={item} />;
                    if (item.kind === "user") return (
                        <div key={i} style={{ margin: "12px 0 6px", display: "flex", justifyContent: "flex-end" }}>
                            <div style={{ background: "var(--surface-2)", borderRadius: "14px", padding: "8px 12px", fontSize: "14px", maxWidth: "85%", whiteSpace: "pre-wrap" }}>{item.text}</div>
                        </div>
                    );
                    if (item.kind === "handoff") return <HandoffCard key={i} tab={item.tab} task={item.task} onHandoff={onHandoff} />;
                    if (item.kind === "error") return (
                        <div key={i}>
                            <div className={errorClass(item.text)}>{item.text}</div>
                            <SuggestModel suggest={item.suggest} onSwitch={id => { setModel(id); run(item.retry, id); }} />
                        </div>
                    );
                    return <AssistantText key={i} text={item.text} token={token} copyText={replies.get(i)} animate={i >= liveFrom.current} />;
                }); })()}
                <TabWorking tokens={tokens} active={busy} status="Looking at your numbers…" />
                {compacting && <div style={{ color: "var(--text-muted)", fontSize: "13px", margin: "8px 0" }}>Compacting the conversation…</div>}
                <div ref={endRef} />
            </div>

            {status?.connected && (
                <div style={{ padding: "8px 8px 20px" }}>
                    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "20px", padding: "10px 14px 8px" }}>
                        <QueuedMessages queue={queue} onRemove={unqueue} />
                    <AttachedChips files={files} setFiles={setFiles} />
                    <textarea value={input} rows={2} onChange={e => setInput(e.target.value)}
                            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
                            placeholder="Type / for commands"
                            style={{ width: "100%", background: "transparent", border: "none", color: "var(--text)", fontSize: "15px", outline: "none", resize: "none", fontFamily: "inherit" }} />
                        <div style={{ display: "flex", alignItems: "center", gap: "6px", minWidth: 0 }}>
                        <PlusMenu commands={COMMANDS} onCommand={c => (c.arg ? setInput(`/${c.name} `) : runCommand(c.name))}
                            onFiles={addFiles} onConnectors={() => setConnectorsOpen(true)} disabled={!!busy} />
                        <VoiceInput value={input} onChange={setInput} />
                        <VoiceModeButton onClick={() => setVoiceOn(true)} />
                            <ModelPicker token={token} value={model} onChange={setModel} storageKey="semblance_finance_model" />
                            <span style={{ flex: 1 }} />
                        <ContextRing budget={budget} onCompact={compactNow} busy={!!busy || compacting} />
                            <button onClick={busy && !input.trim() ? () => abortRef.current?.abort() : submit} aria-label={busy ? (input.trim() ? "Queue message" : "Stop") : "Send"} className={busy && !input.trim() ? "" : "btn-gold"}
                                style={{ width: "32px", height: "32px", borderRadius: "50%", border: "none", cursor: "pointer", display: "inline-flex", alignItems: "center", justifyContent: "center",
                                    background: busy && !input.trim() ? "var(--danger)" : "var(--accent)", color: "var(--accent-contrast)", fontSize: "15px" }}>
                                {busy && !input.trim() ? <StopIcon size={14} /> : <SendIcon size={16} />}
                            </button>
                        </div>
                    </div>
                </div>
            )}
            {voiceOn && <VoiceMode token={token} busy={!!busy} send={m => run(m)} onClose={() => setVoiceOn(false)}
                lastReply={[...turnReplies(items, busy).values()].pop() || ""} />}
            {connectorsOpen && <ConnectorsSheet token={token} onClose={() => setConnectorsOpen(false)} />}
        </div>
    );
}
