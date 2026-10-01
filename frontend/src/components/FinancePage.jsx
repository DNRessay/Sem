import { useEffect, useRef, useState } from "react";
import ModelPicker, { loadModel } from "./ModelPicker";
import { ToolStep, md } from "./CodePage";
import { readEvents } from "../utils/sse";

const API = import.meta.env.VITE_API_URL || "";
const STORE_KEY = "semblance_finance_items";

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
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || []; } catch { return []; }
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
            <button onClick={connect} disabled={busy || !url || !key} style={{ ...btn, alignSelf: "flex-start", background: "var(--accent)", color: "var(--accent-contrast)", border: "none" }}>Connect C-Lab</button>
            {msg && <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>{msg}</div>}
        </div>
    );
}

// Finance tab: ask about your own money. Answers come from C-Lab over MCP
// (read-only), with web search for outside context.
export default function FinancePage({ token, onBack, onUnauthorized }) {
    const [status, setStatus] = useState(null);
    const [items, setItems] = useState(loadItems);
    const [input, setInput] = useState("");
    const [busy, setBusy] = useState(false);
    const [model, setModel] = useState(() => loadModel("semblance_finance_model"));
    const abortRef = useRef(null);
    const endRef = useRef(null);
    const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

    const refresh = () => fetch(`${API}/finance/status`, { headers })
        .then(r => { if (r.status === 401) onUnauthorized(); return r.json(); })
        .then(setStatus).catch(() => setStatus({ connected: false }));
    useEffect(() => { refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    useEffect(() => { try { localStorage.setItem(STORE_KEY, JSON.stringify(items.slice(-200))); } catch {} }, [items]);
    useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [items, busy]);

    const run = async (message) => {
        if (!message.trim() || busy) return;
        const history = items.filter(i => i.kind === "user" || i.kind === "text")
            .map(i => ({ role: i.kind === "user" ? "user" : "assistant", content: i.text })).slice(-20);
        setItems(it => [...it, { kind: "user", text: message }]);
        setInput(""); setBusy(true);
        abortRef.current = new AbortController();
        try {
            const res = await fetch(`${API}/finance/run`, {
                method: "POST", headers, signal: abortRef.current.signal, body: JSON.stringify({ message, history, model }),
            });
            if (res.status === 401) { onUnauthorized(); return; }
            if (!res.ok || !res.body) throw new Error((await res.json().catch(() => ({}))).detail || `Request failed: ${res.status}`);
            await readEvents(res, (ev) => {
                if (ev.type === "text") setItems(it => [...it, { kind: "text", text: ev.text }]);
                else if (ev.type === "tool") setItems(it => [...it, { kind: "tool", id: ev.id, name: ev.name.replace("mcp__clab__", "c-lab: "), args: ev.args }]);
                else if (ev.type === "result") setItems(it => it.map(i => (i.kind === "tool" && i.id === ev.id && i.ok === undefined ? { ...i, ok: ev.ok, output: ev.output } : i)));
                else if (ev.type === "error") setItems(it => [...it, { kind: "error", text: ev.text }]);
            });
        } catch (e) {
            if (e.name !== "AbortError") setItems(it => [...it, { kind: "error", text: e.message }]);
        }
        setBusy(false);
    };

    return (
        <div style={{ position: "fixed", inset: 0, background: "var(--bg)", zIndex: 25, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                <button onClick={onBack} aria-label="Back" style={{ background: "none", border: "none", cursor: "pointer", fontSize: "18px", color: "var(--text)" }}>←</button>
                <span style={{ fontWeight: 700, color: "var(--text)", flex: 1 }}>Finance</span>
                {status?.connected && <span style={{ fontSize: "11px", color: "var(--ready)" }}>● C-Lab connected</span>}
                {status?.connected && <button onClick={() => setItems([])} disabled={busy} style={{ ...btn, fontSize: "12px", padding: "6px 10px" }}>Clear</button>}
            </div>

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
                {items.map((item, i) => {
                    if (item.kind === "tool") return <ToolStep key={i} item={item} />;
                    if (item.kind === "user") return (
                        <div key={i} style={{ margin: "12px 0 6px", display: "flex", justifyContent: "flex-end" }}>
                            <div style={{ background: "var(--surface-2)", borderRadius: "14px", padding: "8px 12px", fontSize: "14px", maxWidth: "85%", whiteSpace: "pre-wrap" }}>{item.text}</div>
                        </div>
                    );
                    if (item.kind === "error") return <div key={i} style={{ color: "var(--danger)", fontSize: "13px", margin: "6px 0" }}>{item.text}</div>;
                    return <div key={i} className="md-content" style={{ fontSize: "14px", color: "var(--text)", margin: "6px 0" }} dangerouslySetInnerHTML={md(item.text)} />;
                })}
                {busy && <div style={{ color: "var(--text-muted)", fontSize: "13px", margin: "8px 0" }}>Looking at your numbers…</div>}
                <div ref={endRef} />
            </div>

            {status?.connected && (
                <div style={{ padding: "8px 8px 20px" }}>
                    <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "20px", padding: "10px 14px 8px" }}>
                        <textarea value={input} rows={2} onChange={e => setInput(e.target.value)}
                            onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); run(input); } }}
                            placeholder="Ask about your money…"
                            style={{ width: "100%", background: "transparent", border: "none", color: "var(--text)", fontSize: "15px", outline: "none", resize: "none", fontFamily: "inherit" }} />
                        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                            <ModelPicker token={token} value={model} onChange={setModel} storageKey="semblance_finance_model" />
                            <span style={{ flex: 1 }} />
                            <button onClick={busy ? () => abortRef.current?.abort() : () => run(input)} aria-label={busy ? "Stop" : "Send"}
                                style={{ width: "32px", height: "32px", borderRadius: "50%", border: "none", cursor: "pointer",
                                    background: busy ? "var(--danger)" : "var(--accent)", color: "var(--accent-contrast)", fontSize: "15px" }}>
                                {busy ? "■" : "↑"}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
