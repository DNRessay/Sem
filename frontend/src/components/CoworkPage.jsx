import { useEffect, useRef, useState } from "react";
import ModelPicker, { loadModel } from "./ModelPicker";
import { ToolStep, md } from "./CodePage";
import { readEvents } from "../utils/sse";
import { AssistantText, AttachedChips, CLEAR_COMMAND, ChatMenu, ConnectorsSheet, HELP_COMMAND, NEW_COMMAND, PlusMenu, SuggestModel, errorClass, helpText, parseSlash, readTextFiles, withAttachments } from "./MessageKit";
import { HeaderStatus } from "./StatusBar";
import { SendIcon, StopIcon } from "./Icons";
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
export default function CoworkPage({ token, onNavigate, onUnauthorized, onFeed, feedError, handoff, onHandoff }) {
    const { chats, chat, updateChat, newChat, selectChat, deleteChat } = useTabChats(STORE_KEY, {
        blank: () => ({ items: [] }),
        legacy: () => { const items = loadItems(); return { items, title: items.find(i => i.kind === "user")?.text.slice(0, 60) || "" }; },
        persist: c => ({ ...c, items: (c.items || []).filter(i => i.kind !== "image").slice(-200) }),
    });
    const items = chat.items;
    const setItems = fn => updateChat(chat.id, x => ({ items: fn(x.items) }));
    const [menuOpen, setMenuOpen] = useState(false);
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
    const [model, setModel] = useState(() => loadModel("semblance_cowork_model"));
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

    const run = async (message, useModel = model) => {
        if (!message.trim() || busy) return;
        const slash = parseSlash(message, COMMANDS);
        if (slash) { setInput(""); return runCommand(slash.cmd.name, slash.rest); }
        const sent = withAttachments(message, files);
        const attached = files.map(f => f.name);
        setFiles([]);
        const chatId = chat.id;
        const add = fn => updateChat(chatId, x => ({ items: fn(x.items) }));
        if (!items.length) updateChat(chatId, () => ({ title: message.slice(0, 60) }));
        const history = items.filter(i => i.kind === "user" || i.kind === "text")
            .map(i => ({ role: i.kind === "user" ? "user" : "assistant", content: i.text })).slice(-20);
        add(it => [...it, { kind: "user", text: attached.length ? `${message}\nAttached: ${attached.join(", ")}` : message }]);
        setInput(""); setBusy(true);
        abortRef.current = new AbortController();
        try {
            const res = await fetch(`${API}/cowork/run`, {
                method: "POST", headers, signal: abortRef.current.signal,
                body: JSON.stringify({ message: sent, history, model: useModel }),
            });
            if (res.status === 401) { onUnauthorized(); return; }
            if (!res.ok || !res.body) throw new Error(`Request failed: ${res.status}`);
            await readEvents(res, (ev) => {
                if (ev.type === "text") add(it => [...it, { kind: "text", text: ev.text }]);
                else if (ev.type === "tool") add(it => [...it, { kind: "tool", id: ev.id, name: ev.name, args: ev.args }]);
                else if (ev.type === "result") add(it => it.map(i => (i.kind === "tool" && i.id === ev.id && i.ok === undefined ? { ...i, ok: ev.ok, output: ev.output } : i)));
                else if (ev.type === "approval") add(it => [...it, { kind: "approval", id: ev.id, name: ev.name, args: ev.args, summary: ev.summary, state: "pending" }]);
                else if (ev.type === "image") add(it => [...it, { kind: "image", id: ev.id, mime: ev.mime, base64: ev.base64, prompt: ev.prompt }]);
                else if (ev.type === "handoff") add(it => [...it, { kind: "handoff", tab: ev.tab, task: ev.task }]);
                else if (ev.type === "error") add(it => [...it, { kind: "error", text: ev.text, suggest: ev.suggest, retry: message }]);
            });
        } catch (e) {
            if (e.name !== "AbortError") add(it => [...it, { kind: "error", text: e.message }]);
        }
        setBusy(false);
    };

    const decide = async (id, decision) => {
        const item = items.find(i => i.kind === "approval" && i.id === id);
        let state = decision;
        if (decision === "approved" && item) {
            try {
                const r = await fetch(`${API}/cowork/execute`, { method: "POST", headers, body: JSON.stringify({ name: item.name, args: item.args }) });
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
                <HeaderStatus token={token} onFeed={onFeed} hasError={feedError} busy={busy} />
                <ChatMenu title={chat.title || "Sem Co-work"} messages={transcript} />
            </div>

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
                {items.map((item, i) => {
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
                    return <AssistantText key={i} text={item.text} token={token} />;
                })}
                {busy && <div style={{ color: "var(--text-muted)", fontSize: "13px", margin: "8px 0" }}>Working…</div>}
                <div ref={endRef} />
            </div>

            <div style={{ padding: "8px 8px 20px" }}>
                <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "20px", padding: "10px 14px 8px" }}>
                    <AttachedChips files={files} setFiles={setFiles} />
                    <textarea
                        value={input} rows={2}
                        onChange={e => setInput(e.target.value)}
                        onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); run(input); } }}
                        placeholder="What should we get done?"
                        style={{ width: "100%", background: "transparent", border: "none", color: "var(--text)", fontSize: "15px", outline: "none", resize: "none", fontFamily: "inherit" }}
                    />
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <PlusMenu commands={COMMANDS} onCommand={c => (c.arg ? setInput(`/${c.name} `) : runCommand(c.name))}
                            onFiles={addFiles} onConnectors={() => setConnectorsOpen(true)} disabled={!!busy} />
                        <ModelPicker token={token} value={model} onChange={setModel} storageKey="semblance_cowork_model" />
                        <span style={{ flex: 1 }} />
                        <button
                            onClick={busy ? () => abortRef.current?.abort() : () => run(input)}
                            aria-label={busy ? "Stop" : "Send"} className={busy ? "" : "btn-gold"}
                            style={{ width: "32px", height: "32px", borderRadius: "50%", border: "none", cursor: "pointer", display: "inline-flex", alignItems: "center", justifyContent: "center",
                                background: busy ? "var(--danger)" : "var(--accent)", color: "var(--accent-contrast)", fontSize: "15px" }}
                        >{busy ? <StopIcon size={14} /> : <SendIcon size={16} />}</button>
                    </div>
                </div>
            </div>
            {connectorsOpen && <ConnectorsSheet token={token} onClose={() => setConnectorsOpen(false)} />}
        </div>
    );
}
