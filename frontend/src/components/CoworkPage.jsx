import { useEffect, useRef, useState } from "react";
import VoiceMode, { VoiceModeButton } from "./VoiceMode";
import { TabWorking } from "./Working";
import ModelPicker, { loadModel } from "./ModelPicker";
import { ToolStep, md } from "./CodePage";
import { runStream, useResumeRun } from "../utils/runs";
import { AUTO_COMPACT_AT, ContextRing, compactItems, useContextBudget, AssistantText, AttachedChips, QueuedMessages, turnReplies, useSendQueue, CLEAR_COMMAND, ChatMenu, ConnectorsSheet, HELP_COMMAND, NEW_COMMAND, PlusMenu, SuggestModel, errorClass, helpText, parseSlash, readTextFiles, withAttachments } from "./MessageKit";
import { HeaderStatus } from "./StatusBar";
import { SendIcon, StopIcon } from "./Icons";
import AgentFeedPanel from "./AgentFeedPanel";
import useAgentFeed from "../hooks/useAgentFeed";
import VoiceInput from "./VoiceInput";
import TabDrawer, { HandoffCard, MenuButton } from "./TabDrawer";
import useTabChats from "../hooks/useTabChats";

const API = import.meta.env.VITE_API_URL || "";
const STORE_KEY = "semblance_cowork_chats";
const OLD_KEY = "semblance_cowork_items";

const btn = {
    padding: "7px 12px", borderRadius: "10px", border: "1px solid var(--border)", background: "var(--surface)",
    color: "var(--text)", fontSize: "12px", fontWeight: 600, cursor: "pointer",
};

const SUGGESTIONS = [
    "Research my top 3 competitors and save a comparison note to Drive",
    "What's on my calendar this week? Flag anything that clashes",
    "Summarise unread emails from the last 2 days",
    "Make a square promo image for a weekend special",
];

function loadItems() {
    try { return JSON.parse(localStorage.getItem(OLD_KEY)) || []; } catch { return []; }
}

export function ApprovalCard({ item, onDecide }) {
    const [state, setState] = useState(item.state || "pending");
    const decide = async (approve) => {
        if (!approve) { setState("dismissed"); onDecide(item.id, "dismissed"); return; }
        setState("running");
        const result = await onDecide(item.id, "approved");
        setState(result);
    };
    const a = item.args || {};
    return (
        <div style={{ border: "1px solid var(--border)", borderRadius: "12px", padding: "10px 12px", margin: "8px 0", background: "var(--surface)" }}>
            <div style={{ fontSize: "13px", fontWeight: 600, color: "var(--text)" }}>{item.summary}</div>
            {item.name === "gmail_send" && (
                <pre style={{ whiteSpace: "pre-wrap", fontSize: "12px", color: "var(--text-muted)", margin: "6px 0", fontFamily: "inherit" }}>{a.body}</pre>
            )}
            {state === "pending" && (
                <div style={{ display: "flex", gap: "8px", marginTop: "6px" }}>
                    <button className="btn-primary" onClick={() => decide(true)} style={btn}>Approve</button>
                    <button onClick={() => decide(false)} style={btn}>Dismiss</button>
                </div>
            )}
            {state !== "pending" && (
                <div style={{ fontSize: "12px", marginTop: "6px", color: state === "done" ? "var(--ready)" : state === "running" ? "var(--text-muted)" : "var(--danger)" }}>
                    {state === "done" ? "Done" : state === "running" ? "Working…" : state === "dismissed" ? "Dismissed" : state}
                </div>
            )}
        </div>
    );
}

// Full-screen Co-work tab: an assistant that does the work (research, email,
// calendar, Drive notes, images) instead of only advising. Anything that
// leaves SEMBLANCE — sending email, adding events — waits for Approve.
export default function CoworkPage({ token, onNavigate, onUnauthorized, handoff, onHandoff }) {
    const { chats, chat, updateChat, newChat, selectChat, deleteChat } = useTabChats(STORE_KEY, {
        blank: () => ({ items: [] }),
        legacy: () => { const items = loadItems(); return { items, title: items.find(i => i.kind === "user")?.text.slice(0, 60) || "" }; },
        persist: c => ({ ...c, items: (c.items || []).filter(i => i.kind !== "image").slice(-200) }),
    });
    const items = chat.items;
    const setItems = fn => updateChat(chat.id, x => ({ items: fn(x.items) }));
    const [menuOpen, setMenuOpen] = useState(false);
    // The activity icon shows this chat's own log (tools, MCP calls, models, errors).
    const feed = useAgentFeed(`cowork:${chat.id}`, token);
    const [feedOpen, setFeedOpen] = useState(false);
    const [input, setInput] = useState("");
    const [files, setFiles] = useState([]);
    const [connectorsOpen, setConnectorsOpen] = useState(false);
    const COMMANDS = [
        { name: "research", arg: "question", help: "Research a question on the web with sources" },
        { name: "remind", arg: "what and when", help: "Set a reminder" },
        NEW_COMMAND, CLEAR_COMMAND, HELP_COMMAND,
    ];
    const takenHandoff = useRef(0);
    useEffect(() => {
        if (handoff?.view !== "cowork" || takenHandoff.current === handoff.at) return;
        takenHandoff.current = handoff.at;
        newChat(); setInput(handoff.task);
    }, [handoff]); // eslint-disable-line react-hooks/exhaustive-deps
    const [busy, setBusy] = useState(false);
    const liveFrom = useRef(Infinity);
    const [voiceOn, setVoiceOn] = useState(false);
    const [tokens, setTokens] = useState(0);
    useEffect(() => { liveFrom.current = Infinity; }, [chat.id]);
    const [model, setModel] = useState(() => loadModel("semblance_cowork_model"));
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

    useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [items, busy]);

    const runCommand = (name, rest = "") => {
        if (name === "help") return setItems(it => [...it, { kind: "text", text: helpText(COMMANDS) }]);
        if (name === "new") return newChat();
        if (name === "clear") return setItems(() => []);
        if (name === "research") return run(`Research this thoroughly on the web, read the best sources and answer with links: ${rest}`);
        if (name === "remind") return run(`Set a reminder: ${rest}`);
    };
    const addFiles = async (list) => {
        const { added, error } = await readTextFiles(list);
        setFiles(x => [...x, ...added].slice(0, 8));
        if (error) setItems(it => [...it, { kind: "error", text: error }]);
    };
    const transcript = items.filter(i => i.kind === "user" || i.kind === "text")
        .map(i => ({ role: i.kind === "user" ? "user" : "assistant", text: i.text }));

    const applyEvent = (chatId, ev, retry = "") => {
        const add = fn => updateChat(chatId, x => ({ items: fn(x.items) }));
        if (ev.type === "usage") setTokens(ev.tokens);
        else if (ev.type === "text") add(it => [...it, { kind: "text", text: ev.text }]);
        else if (ev.type === "tool") add(it => [...it, { kind: "tool", id: ev.id, name: ev.name, args: ev.args }]);
        else if (ev.type === "result") add(it => it.map(i => (i.kind === "tool" && i.id === ev.id && i.ok === undefined ? { ...i, ok: ev.ok, output: ev.output } : i)));
        else if (ev.type === "approval") add(it => [...it, { kind: "approval", id: ev.id, name: ev.name, args: ev.args, summary: ev.summary, state: "pending" }]);
        else if (ev.type === "image") add(it => [...it, { kind: "image", id: ev.id, mime: ev.mime, base64: ev.base64, prompt: ev.prompt }]);
        else if (ev.type === "handoff") add(it => [...it, { kind: "handoff", tab: ev.tab, task: ev.task }]);
        else if (ev.type === "error") add(it => [...it, { kind: "error", text: ev.text, suggest: ev.suggest, retry }]);
    };
    // A run still going when the page was closed or reloaded: pick it back up.
    useResumeRun(chat.id, chat.pendingRun, {
        headers, apply: ev => applyEvent(chat.id, ev),
        onStart: () => setBusy(true),
        onSeq: seq => updateChat(chat.id, c => ({ pendingRun: c.pendingRun && { ...c.pendingRun, seq } })),
        done: () => { updateChat(chat.id, () => ({ pendingRun: null })); setBusy(false); },
    });

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
            const r = await runStream("/cowork/run", {
                headers, signal: abortRef.current.signal, body: { message: sent, history, model: useModel, chat_id: chatId },
                onEvent: ev => applyEvent(chatId, ev, message),
                onRun: (id, seq) => updateChat(chatId, () => ({ pendingRun: { id, seq } })),
            });
            if (r.status === 401) { onUnauthorized(); return; }
            if (r.error) throw new Error(r.error);
        } catch (e) {
            if (e.name !== "AbortError") add(it => [...it, { kind: "error", text: e.message }]);
        } finally {
            updateChat(chatId, () => ({ pendingRun: null }));
        }
        setBusy(false);
    };
    const { queue, enqueue, remove: unqueue } = useSendQueue(busy, (m) => run(m));
    const submit = () => {
        if (!busy) return run(input);
        enqueue(input);
        setInput("");
    };

    const decide = async (id, decision) => {
        const item = items.find(i => i.kind === "approval" && i.id === id);
        let state = decision;
        if (decision === "approved" && item) {
            try {
                const r = await fetch(`${API}/cowork/execute`, { method: "POST", headers, body: JSON.stringify({ name: item.name, args: item.args, chat_id: chat.id }) });
                const d = await r.json().catch(() => ({}));
                state = r.ok ? "done" : (d.detail || `Failed (${r.status})`);
            } catch (e) { state = e.message; }
        }
        setItems(it => it.map(i => (i.kind === "approval" && i.id === id ? { ...i, state } : i)));
        return state;
    };

    return (
        <div style={{ position: "fixed", inset: 0, background: "var(--bg)", zIndex: 25, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                <MenuButton onClick={() => setMenuOpen(true)} />
                <span style={{ fontWeight: 700, color: "var(--text)", flex: 1 }}>Sem Co-work</span>
                <HeaderStatus token={token} onFeed={() => { setFeedOpen(true); feed.acknowledgeErrors(); }} hasError={feed.hasError} busy={busy} />
                <ChatMenu title={chat.title || "Sem Co-work"} messages={transcript} />
            </div>

            <AgentFeedPanel open={feedOpen} onClose={() => setFeedOpen(false)} events={feed.events}
                title={`Activity · ${chat.title || "New chat"}`} />
            <TabDrawer open={menuOpen} onClose={() => setMenuOpen(false)} title="Sem Co-work" current="cowork"
                onNavigate={onNavigate} onNew={() => newChat()} chats={chats} activeId={chat.id} disabled={busy}
                onSelect={selectChat} onDelete={deleteChat} />

            <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>
                {items.length === 0 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                        <div style={{ color: "var(--text-muted)", fontSize: "14px", lineHeight: 1.5 }}>
                            Hand over a task and Sem does it: researches, reads your email and calendar, writes Drive notes,
                            makes images. Sending email or adding events always waits for your Approve.
                        </div>
                        {SUGGESTIONS.map(s => (
                            <button key={s} onClick={() => run(s)} style={{ ...btn, textAlign: "left", fontWeight: 400 }}>{s}</button>
                        ))}
                    </div>
                )}
                {(() => { const replies = turnReplies(items, busy); return items.map((item, i) => {
                    if (item.kind === "tool") return <ToolStep key={i} item={item} />;
                    if (item.kind === "approval") return <ApprovalCard key={`${item.id}-${i}`} item={item} onDecide={decide} />;
                    if (item.kind === "image") return (
                        <figure key={i} style={{ margin: "8px 0" }}>
                            <img src={`data:${item.mime};base64,${item.base64}`} alt={item.prompt} style={{ maxWidth: "100%", borderRadius: "12px", border: "1px solid var(--border)" }} />
                            <figcaption style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", color: "var(--text-muted)", marginTop: "4px" }}>
                                <span>{item.prompt}</span>
                                <a href={`data:${item.mime};base64,${item.base64}`} download="semblance-image.png" style={{ color: "var(--text)" }}>Download</a>
                            </figcaption>
                        </figure>
                    );
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
                <TabWorking tokens={tokens} active={busy} />
                {compacting && <div style={{ color: "var(--text-muted)", fontSize: "13px", margin: "8px 0" }}>Compacting the conversation…</div>}
                <div ref={endRef} />
            </div>

            <div style={{ padding: "8px 8px 20px" }}>
                <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "20px", padding: "10px 14px 8px" }}>
                    <QueuedMessages queue={queue} onRemove={unqueue} />
                    <AttachedChips files={files} setFiles={setFiles} />
                    <textarea
                        value={input} rows={2}
                        onChange={e => setInput(e.target.value)}
                        onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); } }}
                        placeholder="Type / for commands"
                        style={{ width: "100%", background: "transparent", border: "none", color: "var(--text)", fontSize: "15px", outline: "none", resize: "none", fontFamily: "inherit" }}
                    />
                    <div style={{ display: "flex", alignItems: "center", gap: "6px", minWidth: 0 }}>
                        <PlusMenu commands={COMMANDS} onCommand={c => (c.arg ? setInput(`/${c.name} `) : runCommand(c.name))}
                            onFiles={addFiles} onConnectors={() => setConnectorsOpen(true)} disabled={!!busy} />
                        <VoiceInput value={input} onChange={setInput} />
                        <VoiceModeButton onClick={() => setVoiceOn(true)} />
                        <ModelPicker token={token} value={model} onChange={setModel} storageKey="semblance_cowork_model" />
                        <span style={{ flex: 1 }} />
                        <ContextRing budget={budget} onCompact={compactNow} busy={!!busy || compacting} />
                        <button
                            onClick={busy && !input.trim() ? () => abortRef.current?.abort() : submit}
                            aria-label={busy ? (input.trim() ? "Queue message" : "Stop") : "Send"} className={busy && !input.trim() ? "" : "btn-gold"}
                            style={{ width: "32px", height: "32px", borderRadius: "50%", border: "none", cursor: "pointer", display: "inline-flex", alignItems: "center", justifyContent: "center",
                                background: busy && !input.trim() ? "var(--danger)" : "var(--accent)", color: "var(--accent-contrast)", fontSize: "15px" }}
                        >{busy && !input.trim() ? <StopIcon size={14} /> : <SendIcon size={16} />}</button>
                    </div>
                </div>
            </div>
            {voiceOn && <VoiceMode token={token} busy={!!busy} send={m => run(m)} onClose={() => setVoiceOn(false)}
                lastReply={[...turnReplies(items, busy).values()].pop() || ""} />}
            {connectorsOpen && <ConnectorsSheet token={token} onClose={() => setConnectorsOpen(false)} />}
        </div>
    );
}
