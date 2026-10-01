import { useEffect, useRef, useState } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import ModelPicker, { loadModel } from "./ModelPicker";

const API = import.meta.env.VITE_API_URL || "";
const STORE_KEY = "semblance_code_state";

const btn = {
    padding: "7px 12px", borderRadius: "10px", border: "1px solid var(--border)", background: "var(--surface)",
    color: "var(--text)", fontSize: "12px", fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap",
};
const field = {
    padding: "8px 10px", borderRadius: "10px", border: "1px solid var(--border)", background: "var(--surface)",
    color: "var(--text)", fontSize: "13px", minWidth: 0,
};

function md(text) {
    return { __html: DOMPurify.sanitize(marked.parse(text || "", { breaks: true })) };
}

function loadState() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; } catch { return {}; }
}

function saveState(state) {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(state)); } catch {}
}

function toolSummary(name, args) {
    if (name === "bash") return args.command;
    if (name === "aws") return `${args.service} ${args.operation}`;
    if (name === "grep") return args.pattern;
    return args.path ?? "";
}

function ToolStep({ item }) {
    const status = item.ok === undefined ? "…" : item.ok ? "✓" : "✗";
    const color = item.ok === false ? "var(--danger)" : item.ok ? "var(--ready)" : "var(--text-muted)";
    return (
        <details style={{ margin: "4px 0", fontSize: "12px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "8px", padding: "6px 10px" }}>
            <summary style={{ cursor: "pointer", fontFamily: "ui-monospace, monospace", color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                <span style={{ color }}>{status}</span> {item.name} <span style={{ color: "var(--text-muted)" }}>{toolSummary(item.name, item.args)}</span>
            </summary>
            {item.output && (
                <pre style={{ margin: "6px 0 0", whiteSpace: "pre-wrap", wordBreak: "break-word", maxHeight: "260px", overflow: "auto", color: "var(--text-muted)" }}>{item.output}</pre>
            )}
        </details>
    );
}

function Automations({ token, provider, repo, onUnauthorized }) {
    const [items, setItems] = useState([]);
    const [prompt, setPrompt] = useState("");
    const [every, setEvery] = useState("daily");
    const [openPr, setOpenPr] = useState(true);
    const [error, setError] = useState("");
    const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

    const refresh = () => fetch(`${API}/code/automations`, { headers })
        .then(r => { if (r.status === 401) onUnauthorized(); return r.json(); })
        .then(d => setItems(d.automations || []))
        .catch(() => {});

    useEffect(() => { refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const create = async () => {
        setError("");
        const r = await fetch(`${API}/code/automations`, {
            method: "POST", headers, body: JSON.stringify({ provider, repo, prompt, every, open_pr: openPr }),
        });
        if (!r.ok) { setError((await r.json()).detail || "Couldn't save"); return; }
        setPrompt("");
        refresh();
    };
    const toggle = async (a) => {
        await fetch(`${API}/code/automations/${a.id}`, { method: "PATCH", headers, body: JSON.stringify({ enabled: !a.enabled }) });
        refresh();
    };
    const remove = async (a) => {
        await fetch(`${API}/code/automations/${a.id}`, { method: "DELETE", headers });
        refresh();
    };

    return (
        <div style={{ padding: "10px 16px", borderBottom: "1px solid var(--border)", display: "flex", flexDirection: "column", gap: "8px" }}>
            <div style={{ fontSize: "11px", fontWeight: 600, letterSpacing: "1px", color: "var(--text-muted)" }}>AUTOMATIONS · {repo}</div>
            <textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={2}
                placeholder="e.g. Update outdated dependencies and make sure the tests still pass" style={{ ...field, resize: "vertical" }} />
            <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
                <select value={every} onChange={e => setEvery(e.target.value)} style={field}>
                    <option value="hourly">Hourly</option>
                    <option value="daily">Daily</option>
                    <option value="weekly">Weekly</option>
                </select>
                <label style={{ fontSize: "12px", color: "var(--text)", display: "flex", gap: "4px", alignItems: "center" }}>
                    <input type="checkbox" checked={openPr} onChange={e => setOpenPr(e.target.checked)} /> Open a PR with changes
                </label>
                <button onClick={create} disabled={!prompt.trim()} style={btn}>Schedule</button>
            </div>
            {error && <div style={{ color: "var(--danger)", fontSize: "12px" }}>{error}</div>}
            {items.filter(a => a.repo === repo && a.provider === provider).map(a => (
                <div key={a.id} style={{ border: "1px solid var(--border)", borderRadius: "8px", padding: "8px 10px", fontSize: "12px" }}>
                    <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
                        <span style={{ flex: 1, color: "var(--text)" }}>{a.prompt}</span>
                        <button onClick={() => toggle(a)} style={btn}>{a.enabled ? "Pause" : "Resume"}</button>
                        <button onClick={() => remove(a)} style={{ ...btn, color: "var(--danger)" }}>Delete</button>
                    </div>
                    <div style={{ color: "var(--text-muted)", marginTop: "4px" }}>
                        Every {a.every_seconds >= 604800 ? "week" : a.every_seconds >= 86400 ? "day" : "hour"}
                        {a.last_result ? ` · ${a.last_result.slice(0, 200)}` : " · not run yet"}
                    </div>
                </div>
            ))}
        </div>
    );
}

// Full-screen Code tab: a coding agent working in a clone of one repo on
// Modal. Nothing reaches the repo until "Open PR" (or an automation) does.
export default function CodePage({ token, onBack, onUnauthorized }) {
    const saved = loadState();
    const [provider, setProvider] = useState(saved.provider || "github");
    const [repo, setRepo] = useState(saved.repo || "");
    const [repos, setRepos] = useState([]);
    const [opened, setOpened] = useState(null);
    const [items, setItems] = useState(saved.items || []);
    const [input, setInput] = useState("");
    const [mode, setMode] = useState("act");
    const [model, setModel] = useState(() => loadModel("semblance_code_model"));
    const [busy, setBusy] = useState("");
    const [notice, setNotice] = useState("");
    const [showAutomations, setShowAutomations] = useState(false);
    const abortRef = useRef(null);
    const endRef = useRef(null);
    const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

    useEffect(() => { saveState({ provider, repo, items: items.slice(-200) }); }, [provider, repo, items]);
    useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [items, busy]);
    useEffect(() => {
        fetch(`${API}/connectors/${provider}/repos`, { headers })
            .then(r => (r.ok ? r.json() : { repos: [] }))
            .then(d => setRepos(d.repos || []))
            .catch(() => setRepos([]));
    }, [provider]); // eslint-disable-line react-hooks/exhaustive-deps

    const post = async (path, body) => {
        const r = await fetch(`${API}${path}`, { method: "POST", headers, body: JSON.stringify({ provider, repo, ...body }) });
        if (r.status === 401) { onUnauthorized(); throw new Error("Session expired"); }
        const data = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(data.detail || `Request failed: ${r.status}`);
        return data;
    };

    const openRepo = async () => {
        setBusy("Cloning…"); setNotice("");
        try {
            const data = await post("/code/open", {});
            setOpened({ repo, provider, canOpenPr: data.can_open_pr });
            setNotice(`${data.action === "pulled" ? "Updated" : "Cloned"} ${repo} — ${data.entries.length} entries at the root.`);
        } catch (e) { setNotice(e.message); }
        setBusy("");
    };

    const history = () => items
        .filter(i => i.kind === "user" || i.kind === "text")
        .map(i => ({ role: i.kind === "user" ? "user" : "assistant", content: i.text }))
        .slice(-20);

    const run = async (message, runMode = mode) => {
        if (!message.trim() || busy) return;
        const prior = history();
        setItems(it => [...it, { kind: "user", text: message, mode: runMode }]);
        setInput(""); setBusy(runMode === "plan" ? "Planning…" : "Working…"); setNotice("");
        abortRef.current = new AbortController();
        try {
            const res = await fetch(`${API}/code/run`, {
                method: "POST", headers, signal: abortRef.current.signal,
                body: JSON.stringify({ provider, repo, message, history: prior, mode: runMode, model }),
            });
            if (res.status === 401) { onUnauthorized(); return; }
            if (!res.ok || !res.body) throw new Error(`Request failed: ${res.status}`);
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";
            const handle = (line) => {
                if (!line.startsWith("data: ") || line === "data: [DONE]") return;
                let ev;
                try { ev = JSON.parse(line.slice(6)); } catch { return; }
                if (ev.type === "text") setItems(it => [...it, { kind: "text", text: ev.text, mode: runMode }]);
                else if (ev.type === "tool") setItems(it => [...it, { kind: "tool", id: ev.id, name: ev.name, args: ev.args }]);
                else if (ev.type === "result") setItems(it => it.map(i => (i.kind === "tool" && i.id === ev.id && i.ok === undefined ? { ...i, ok: ev.ok, output: ev.output } : i)));
                else if (ev.type === "error") setItems(it => [...it, { kind: "error", text: ev.text }]);
            };
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop() ?? "";
                lines.forEach(handle);
            }
            if (buffer) handle(buffer);
        } catch (e) {
            if (e.name !== "AbortError") setItems(it => [...it, { kind: "error", text: e.message }]);
        }
        setBusy("");
    };

    const showChanges = async () => {
        try {
            const d = await post("/code/changes", {});
            setNotice(d.files.length || d.deleted.length
                ? `Changed: ${d.files.join(", ")}${d.deleted.length ? ` · deleted: ${d.deleted.join(", ")}` : ""}`
                : "No changes yet.");
        } catch (e) { setNotice(e.message); }
    };

    const openPr = async () => {
        const title = window.prompt("Pull request title", items.filter(i => i.kind === "user").slice(-1)[0]?.text.slice(0, 70) || "Changes from Sem Code");
        if (!title) return;
        setBusy("Opening PR…");
        try {
            const d = await post("/code/pr", { title, body: items.filter(i => i.kind === "text").slice(-1)[0]?.text || "" });
            setItems(it => [...it, { kind: "text", text: `Opened [pull request](${d.url}) from \`${d.branch}\` with ${d.files.length} file(s).` }]);
        } catch (e) { setNotice(e.message); }
        setBusy("");
    };

    const discard = async () => {
        if (!window.confirm("Discard all uncommitted changes in the workspace?")) return;
        try { await post("/code/discard", {}); setNotice("Workspace reset to the last pulled state."); } catch (e) { setNotice(e.message); }
    };

    const lastIsPlan = !busy && items.length > 0 && items[items.length - 1].kind === "text" && items[items.length - 1].mode === "plan";
    const ready = opened && opened.repo === repo && opened.provider === provider;

    return (
        <div style={{ position: "fixed", inset: 0, background: "var(--bg)", zIndex: 25, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "12px 16px", borderBottom: "1px solid var(--border)", flexWrap: "wrap" }}>
                <button onClick={onBack} aria-label="Back" style={{ background: "none", border: "none", cursor: "pointer", fontSize: "18px", color: "var(--text)" }}>←</button>
                <span style={{ fontWeight: 700, color: "var(--text)" }}>Code</span>
                <select value={provider} onChange={e => { setProvider(e.target.value); setOpened(null); }} style={field}>
                    <option value="github">GitHub</option>
                    <option value="gitlab">GitLab</option>
                </select>
                <input list="code-repos" value={repo} onChange={e => { setRepo(e.target.value.trim()); setOpened(null); }}
                    placeholder="owner/repo" style={{ ...field, flex: 1, minWidth: "140px" }} />
                <datalist id="code-repos">{repos.map(r => <option key={r.full_name} value={r.full_name} />)}</datalist>
                <button onClick={openRepo} disabled={!repo || !!busy} style={btn}>{ready ? "Pull" : "Open"}</button>
            </div>

            {ready && (
                <div style={{ display: "flex", gap: "6px", padding: "8px 16px", borderBottom: "1px solid var(--border)", overflowX: "auto" }}>
                    <button onClick={showChanges} style={btn}>Changes</button>
                    <button onClick={openPr} disabled={!opened.canOpenPr || !!busy} title={opened.canOpenPr ? "" : `Connect ${provider} to open PRs`} style={btn}>Open PR</button>
                    <button onClick={discard} disabled={!!busy} style={btn}>Discard</button>
                    <button onClick={() => setShowAutomations(s => !s)} style={btn}>Automations</button>
                    <button onClick={() => setItems([])} disabled={!!busy} style={btn}>Clear</button>
                </div>
            )}
            {ready && showAutomations && <Automations token={token} provider={provider} repo={repo} onUnauthorized={onUnauthorized} />}
            {notice && <div style={{ padding: "8px 16px", fontSize: "12px", color: "var(--text-muted)", borderBottom: "1px solid var(--border)" }}>{notice}</div>}

            <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>
                {!ready && (
                    <div style={{ color: "var(--text-muted)", fontSize: "14px", lineHeight: 1.5 }}>
                        Pick a repo and press Open. Sem Code works in its own copy on Modal: it reads, edits and runs commands there,
                        and nothing reaches your repo until you press Open PR. Use Plan first for bigger changes.
                    </div>
                )}
                {items.map((item, i) => {
                    if (item.kind === "tool") return <ToolStep key={i} item={item} />;
                    if (item.kind === "user") return (
                        <div key={i} style={{ margin: "12px 0 6px", display: "flex", justifyContent: "flex-end" }}>
                            <div style={{ background: "var(--surface-2)", borderRadius: "14px", padding: "8px 12px", fontSize: "14px", maxWidth: "85%", whiteSpace: "pre-wrap" }}>
                                {item.mode === "plan" && <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>PLAN · </span>}{item.text}
                            </div>
                        </div>
                    );
                    if (item.kind === "error") return <div key={i} style={{ color: "var(--danger)", fontSize: "13px", margin: "6px 0" }}>{item.text}</div>;
                    return <div key={i} className="md-content" style={{ fontSize: "14px", color: "var(--text)", margin: "6px 0" }} dangerouslySetInnerHTML={md(item.text)} />;
                })}
                {busy && <div style={{ color: "var(--text-muted)", fontSize: "13px", margin: "8px 0" }}>{busy}</div>}
                {lastIsPlan && (
                    <button onClick={() => run("Go ahead and implement the plan above.", "act")} style={{ ...btn, margin: "8px 0", background: "var(--accent)", color: "var(--accent-contrast)" }}>
                        Approve plan &amp; run
                    </button>
                )}
                <div ref={endRef} />
            </div>

            <div style={{ padding: "8px 8px 20px" }}>
                <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "20px", padding: "10px 14px 8px" }}>
                    <textarea
                        value={input} rows={2} disabled={!ready}
                        onChange={e => setInput(e.target.value)}
                        onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); run(input); } }}
                        placeholder={ready ? "What should I build or fix?" : "Open a repo first"}
                        style={{ width: "100%", background: "transparent", border: "none", color: "var(--text)", fontSize: "15px", outline: "none", resize: "none", fontFamily: "inherit" }}
                    />
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <div style={{ display: "flex", border: "1px solid var(--border)", borderRadius: "999px", overflow: "hidden" }}>
                            {["plan", "act"].map(m => (
                                <button key={m} onClick={() => setMode(m)} style={{
                                    padding: "5px 12px", border: "none", fontSize: "12px", cursor: "pointer",
                                    background: mode === m ? "var(--accent)" : "transparent",
                                    color: mode === m ? "var(--accent-contrast)" : "var(--text-muted)",
                                }}>{m === "plan" ? "Plan" : "Act"}</button>
                            ))}
                        </div>
                        <ModelPicker token={token} value={model} onChange={setModel} storageKey="semblance_code_model" />
                        <span style={{ flex: 1 }} />
                        <button
                            onClick={busy && abortRef.current ? () => abortRef.current.abort() : () => run(input)}
                            disabled={!ready}
                            aria-label={busy ? "Stop" : "Send"}
                            style={{ width: "32px", height: "32px", borderRadius: "50%", border: "none", cursor: "pointer",
                                background: busy ? "var(--danger)" : "var(--accent)", color: "var(--accent-contrast)", fontSize: "15px" }}
                        >{busy ? "■" : "↑"}</button>
                    </div>
                </div>
            </div>
        </div>
    );
}
