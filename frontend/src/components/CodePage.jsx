import { useEffect, useRef, useState } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import ModelPicker, { loadModel } from "./ModelPicker";
import { readEvents } from "../utils/sse";
import { RepoPicker } from "./AttachMenu";
import { AUTO_COMPACT_AT, ContextRing, compactItems, useContextBudget, ModeMenu, AssistantText, AttachedChips, CLEAR_COMMAND, ChatMenu, ConnectorsSheet, HELP_COMMAND, NEW_COMMAND, PlusMenu, SuggestModel, errorClass, helpText, parseSlash, readTextFiles, withAttachments } from "./MessageKit";
import { ApprovalCard } from "./CoworkPage";
import { HeaderStatus, iconBtn } from "./StatusBar";
import { CloseIcon, CodeIcon, PlusIcon, SendIcon, StopIcon } from "./Icons";
import AgentFeedPanel from "./AgentFeedPanel";
import useAgentFeed from "../hooks/useAgentFeed";
import VoiceInput from "./VoiceInput";
import TabDrawer, { HandoffCard, MenuButton } from "./TabDrawer";
import useTabChats from "../hooks/useTabChats";

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

export function md(text) {
    return { __html: DOMPurify.sanitize(marked.parse(text || "", { breaks: true })) };
}

function loadState() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || {}; } catch { return {}; }
}

function toolSummary(name, args) {
    if (name === "bash") return args.command;
    if (name === "aws") return `${args.service} ${args.operation}`;
    if (name === "grep") return args.pattern;
    return args.path ?? args.query ?? args.url ?? args.term ?? args.to ?? args.title ?? args.prompt ?? args.summary ?? args.file_id ?? "";
}

// File edits show as a diff (red removed, green added) with +N −M, built from the tool's own arguments.
function editDiff(item) {
    const a = item.args || {};
    if (item.name === "edit_file" && typeof a.old === "string" && typeof a.new === "string") {
        const removed = a.old.split("\n"), added = a.new.split("\n");
        return { lines: [...removed.map(t => ["-", t]), ...added.map(t => ["+", t])], plus: added.length, minus: removed.length };
    }
    if (item.name === "write_file" && typeof a.content === "string") {
        const added = a.content.split("\n");
        return { lines: added.map(t => ["+", t]), plus: added.length, minus: 0 };
    }
    return null;
}

export function ToolStep({ item }) {
    const status = item.ok === undefined ? "…" : item.ok ? "✓" : "✗";
    const color = item.ok === false ? "var(--danger)" : item.ok ? "var(--ready)" : "var(--text-muted)";
    const diff = editDiff(item);
    return (
        <details style={{ margin: "4px 0", fontSize: "12px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "8px", padding: "6px 10px" }}>
            <summary style={{ cursor: "pointer", fontFamily: "ui-monospace, monospace", color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                <span style={{ color }}>{status}</span> {item.name} <span style={{ color: "var(--text-muted)" }}>{toolSummary(item.name, item.args)}</span>
                {diff && <> <span style={{ color: "var(--ready)" }}>+{diff.plus}</span> <span style={{ color: "var(--danger)" }}>−{diff.minus}</span></>}
            </summary>
            {diff && (
                <pre style={{ margin: "6px 0 0", maxHeight: "320px", overflow: "auto", fontSize: "11px", lineHeight: 1.45 }}>
                    {diff.lines.slice(0, 400).map(([sign, text], i) => (
                        <div key={i} style={{ whiteSpace: "pre", background: sign === "+" ? "var(--ready-bg)" : "var(--danger-bg)", color: sign === "+" ? "var(--ready)" : "var(--danger)" }}>{sign} {text}</div>
                    ))}
                    {diff.lines.length > 400 && <div style={{ color: "var(--text-muted)" }}>… {diff.lines.length - 400} more lines</div>}
                </pre>
            )}
            {item.output && !(diff && item.ok) && (
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
// Pick another repo (GitHub or GitLab) to add to this chat.
function AddRepoSheet({ token, defaultProvider, onPick, onClose }) {
    const [p, setP] = useState(defaultProvider);
    const [repos, setRepos] = useState([]);
    useEffect(() => {
        fetch(`${API}/connectors/${p}/repos`, { headers: { Authorization: `Bearer ${token}` } })
            .then(r => (r.ok ? r.json() : { repos: [] })).then(d => setRepos(d.repos || [])).catch(() => setRepos([]));
    }, [p, token]);
    return (
        <>
            <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.25)", zIndex: 44 }} />
            <div style={{ position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 45, background: "var(--bg)", borderTop: "1px solid var(--border)", borderRadius: "16px 16px 0 0", padding: "12px 16px 24px", minHeight: "50vh" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "10px" }}>
                    <span style={{ fontWeight: 700, flex: 1, color: "var(--text)" }}>Add a repo to this chat</span>
                    <select value={p} onChange={e => setP(e.target.value)} style={field}>
                        <option value="github">GitHub</option>
                        <option value="gitlab">GitLab</option>
                    </select>
                </div>
                <RepoPicker floating repos={repos} value="" placeholder="Search your repositories" onChange={r => onPick(p, r)} />
            </div>
        </>
    );
}

export default function CodePage({ token, onNavigate, onUnauthorized, handoff, onHandoff }) {
    const { chats, chat, updateChat, newChat: addChat, selectChat, deleteChat } = useTabChats(STORE_KEY, {
        blank: () => ({ provider: "github", repo: "", items: [] }),
        legacy: () => {
            const saved = loadState();
            const items = saved.items || [];
            return { provider: saved.provider || "github", repo: saved.repo || "", items,
                     title: items.find(i => i.kind === "user")?.text.slice(0, 60) || "" };
        },
        persist: c => ({ ...c, items: (c.items || []).slice(-200) }),
    });
    const { provider, repo, items } = chat;
    // One working branch per chat: every run, PR and push from this chat goes to it.
    const extraRepos = chat.extraRepos || [];
    const [addingRepo, setAddingRepo] = useState(false);
    const addRepo = async (p, r) => {
        setAddingRepo(false);
        if (!r || (p === provider && r === repo) || extraRepos.some(x => x.provider === p && x.repo === r)) return;
        setBusy(`Cloning ${r}…`);
        try {
            const res = await fetch(`${API}/code/open`, { method: "POST", headers, body: JSON.stringify({ provider: p, repo: r }) });
            const d = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(d.detail || `Couldn't open ${r} (${res.status})`);
            updateChat(chat.id, c => ({ extraRepos: [...(c.extraRepos || []), { provider: p, repo: r }] }));
            setNotice(`Added ${r} to this chat — Sem Code can read, edit and open a PR in it too.`);
        } catch (e) { setNotice(e.message); }
        setBusy("");
    };
    const removeRepo = (r) => updateChat(chat.id, c => ({ extraRepos: (c.extraRepos || []).filter(x => x.repo !== r) }));
    const owner = repo.split("/")[0];
    const repoLine = [repo, ...extraRepos.map(x => (x.repo.split("/")[0] === owner ? x.repo.split("/")[1] : x.repo))].filter(Boolean).join(", ");
    const branch = chat.branch || `sem/${(repo.split("/")[1] || "work").toLowerCase().replace(/[^a-z0-9-]/g, "-")}-${chat.id.slice(-6)}`;
    const [menuOpen, setMenuOpen] = useState(false);
    // The activity icon shows this chat's own log (tools, MCP calls, models, errors).
    const feed = useAgentFeed(`code:${chat.id}`, token);
    const [feedOpen, setFeedOpen] = useState(false);
    const [repos, setRepos] = useState([]);
    const [reposError, setReposError] = useState("");
    const [opened, setOpened] = useState(null);
    const [input, setInput] = useState("");
    const [files, setFiles] = useState([]);
    const [connectorsOpen, setConnectorsOpen] = useState(false);
    const COMMANDS = [
        { name: "plan", arg: "task", help: "Plan only — explore and propose, change nothing" },
        { name: "pr", arg: "title", help: "Commit the changes and open a pull/merge request" },
        { name: "merge", arg: "number", help: "Merge a PR/MR (asks you to approve)" },
        { name: "ci", help: "Latest CI runs, and why any failed" },
        { name: "changes", help: "What changed in the workspace" },
        NEW_COMMAND, CLEAR_COMMAND, HELP_COMMAND,
    ];
    const takenHandoff = useRef(0);
    useEffect(() => {
        if (handoff?.view !== "code" || takenHandoff.current === handoff.at) return;
        takenHandoff.current = handoff.at;
        newChat(); setInput(handoff.task);
    }, [handoff]); // eslint-disable-line react-hooks/exhaustive-deps
    const [mode, setMode] = useState(() => { try { return localStorage.getItem("semblance_code_mode") || "act"; } catch { return "act"; } });
    const pickMode = (m) => { setMode(m); try { localStorage.setItem("semblance_code_mode", m); } catch {} };
    const [model, setModel] = useState(() => loadModel("semblance_code_model"));
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
    const [busy, setBusy] = useState("");
    const [notice, setNotice] = useState("");
    const [showAutomations, setShowAutomations] = useState(false);
    const abortRef = useRef(null);
    const endRef = useRef(null);
    const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

    const setItems = (fn) => updateChat(chat.id, c => ({ items: typeof fn === "function" ? fn(c.items) : fn }));
    const newChat = (p = provider, r = repo) => { setOpened(null); setNotice(""); return addChat({ provider: p, repo: r, items: [] }); };
    // A chat belongs to one repo: picking another repo starts a new chat unless this one is still empty.
    const pickRepo = (p, r) => {
        setOpened(null);
        if (items.length) newChat(p, r);
        else updateChat(chat.id, () => ({ provider: p, repo: r }));
    };

    useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [items, busy]);
    useEffect(() => {
        setReposError("");
        fetch(`${API}/connectors/${provider}/repos`, { headers })
            .then(async r => {
                const d = await r.json().catch(() => ({}));
                if (r.status === 401) onUnauthorized();
                if (!r.ok) setReposError(d.detail || `Couldn't load ${provider} repos (${r.status})`);
                setRepos(r.ok ? d.repos || [] : []);
            })
            .catch(() => setRepos([]));
    }, [provider]); // eslint-disable-line react-hooks/exhaustive-deps

    const post = async (path, body) => {
        const r = await fetch(`${API}${path}`, { method: "POST", headers, body: JSON.stringify({ provider, repo, branch, ...body }) });
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
            return true;
        } catch (e) { setNotice(e.message); return false; } finally { setBusy(""); }
    };

    const ready = opened && opened.repo === repo && opened.provider === provider;

    const history = () => items
        .filter(i => i.kind === "user" || i.kind === "text")
        .map(i => ({ role: i.kind === "user" ? "user" : "assistant", content: i.text }))
        .slice(-20);

    const runCommand = (name, rest = "") => {
        if (name === "help") return setItems(it => [...it, { kind: "text", text: helpText(COMMANDS) }]);
        if (name === "new") return newChat();
        if (name === "clear") return setItems(() => []);
        if (name === "plan") return rest ? run(rest, "plan") : pickMode("plan");
        if (name === "pr") return run(rest ? `Open a PR titled "${rest}" with the current changes.` : "Open a PR with the current changes.", "act");
        if (name === "merge") return run(rest ? `Merge PR/MR #${rest.replace("#", "")}.` : "List the open PRs/MRs so I can pick one to merge.", "act");
        if (name === "ci") return run("Show the latest CI runs; for any failure read its logs and tell me why it failed.", "act");
        if (name === "changes") return showChanges();
    };
    const addFiles = async (list) => {
        const { added, error } = await readTextFiles(list);
        setFiles(x => [...x, ...added].slice(0, 8));
        if (error) setItems(it => [...it, { kind: "error", text: error }]);
    };
    const transcript = items.filter(i => i.kind === "user" || i.kind === "text")
        .map(i => ({ role: i.kind === "user" ? "user" : "assistant", text: i.text }));

    const run = async (message, runMode = mode, useModel = model) => {
        if (!message.trim() || busy || !repo) return;
        const slash = parseSlash(message, COMMANDS);
        if (slash) { setInput(""); return runCommand(slash.cmd.name, slash.rest); }
        const sent = withAttachments(message, files);
        const attached = files.map(f => f.name);
        setFiles([]);
        const chatId = chat.id;
        const add = (fn) => updateChat(chatId, c => ({ items: fn(c.items) }));
        let base = items;
        if (budget.pct >= AUTO_COMPACT_AT && !compacting) base = (await compactNow()) || items;
        const prior = base.filter(i => i.kind === "user" || i.kind === "text")
            .map(i => ({ role: i.kind === "user" ? "user" : "assistant", content: i.text })).slice(-20);
        add(it => [...it, { kind: "user", text: attached.length ? `${message}\nAttached: ${attached.join(", ")}` : message, mode: runMode }]);
        if (!items.length) updateChat(chatId, () => ({ title: message.slice(0, 60), branch }));
        setInput("");
        if (!ready && !(await openRepo())) return;
        setBusy(runMode === "plan" ? "Planning…" : "Working…"); setNotice("");
        abortRef.current = new AbortController();
        try {
            const res = await fetch(`${API}/code/run`, {
                method: "POST", headers, signal: abortRef.current.signal,
                body: JSON.stringify({ provider, repo, branch, chat_id: chatId, extra_repos: extraRepos.map(x => `${x.provider}:${x.repo}`), message: sent, history: prior, mode: runMode, model: useModel }),
            });
            if (res.status === 401) { onUnauthorized(); return; }
            if (!res.ok || !res.body) throw new Error(`Request failed: ${res.status}`);
            await readEvents(res, (ev) => {
                if (ev.type === "text") add(it => [...it, { kind: "text", text: ev.text, mode: runMode }]);
                else if (ev.type === "tool") add(it => [...it, { kind: "tool", id: ev.id, name: ev.name, args: ev.args }]);
                else if (ev.type === "result") add(it => it.map(i => (i.kind === "tool" && i.id === ev.id && i.ok === undefined ? { ...i, ok: ev.ok, output: ev.output } : i)));
                else if (ev.type === "approval") add(it => [...it, { kind: "approval", id: ev.id, name: ev.name, args: ev.args, summary: ev.summary, state: "pending" }]);
                else if (ev.type === "handoff") add(it => [...it, { kind: "handoff", tab: ev.tab, task: ev.task }]);
                else if (ev.type === "error") add(it => [...it, { kind: "error", text: ev.text, suggest: ev.suggest, retry: message }]);
            });
        } catch (e) {
            if (e.name !== "AbortError") add(it => [...it, { kind: "error", text: e.message }]);
        }
        setBusy("");
    };

    // Merges, pushes, workflow runs and secrets wait for this tap; the server runs exactly what it showed.
    const decide = async (id, decision) => {
        let state = decision;
        if (decision === "approved") {
            try {
                const r = await fetch(`${API}/code/execute`, { method: "POST", headers, body: JSON.stringify({ id, chat_id: chat.id }) });
                const d = await r.json().catch(() => ({}));
                state = r.ok ? "done" : (d.detail || `Failed (${r.status})`);
                if (r.ok && (d.url || d.sha || d.status)) setItems(it => [...it, { kind: "text", text: [d.status, d.url && `[Open](${d.url})`, d.sha && `commit \`${String(d.sha).slice(0, 8)}\``].filter(Boolean).join(" · ") }]);
            } catch (e) { state = e.message; }
        }
        setItems(it => it.map(i => (i.kind === "approval" && i.id === id ? { ...i, state } : i)));
        return state;
    };

    const showChanges = async () => {
        try {
            const d = await post("/code/changes", {});
            setNotice(d.files.length || d.deleted.length
                ? `Changed: ${d.files.join(", ")}${d.deleted.length ? ` · deleted: ${d.deleted.join(", ")}` : ""}${d.stat ? `\n${d.stat.trim().split("\n").slice(-1)[0]}` : ""}`
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

    const hasRepoWork = !!repo && (ready || items.length > 0);
    const codeActions = [
        { label: "New chat, same repo", onClick: () => newChat(), disabled: !!busy },
        { label: "New chat, another repo", onClick: () => newChat(provider, ""), disabled: !!busy },
        { label: "Add another repo to this chat", onClick: () => setAddingRepo(true), disabled: !repo || !!busy },
        { label: "Pull latest", onClick: openRepo, disabled: !repo || !!busy },
        { label: "Changes", onClick: showChanges, disabled: !hasRepoWork },
        { label: `Open PR on ${branch}`, onClick: openPr, disabled: !hasRepoWork || opened?.canOpenPr === false || !!busy },
        { label: "Discard changes", onClick: discard, disabled: !hasRepoWork || !!busy },
        { label: showAutomations ? "Hide automations" : "Automations", onClick: () => setShowAutomations(x => !x), disabled: !repo },
        ...(onHandoff ? [{ label: "Make ads from this", disabled: !items.length, onClick: () => {
            const done = items.filter(i => i.kind === "text").slice(-1)[0]?.text || items.filter(i => i.kind === "user").slice(-1)[0]?.text || "";
            onHandoff("design", `Make ads announcing this from ${repo}:\n${done.slice(0, 1200)}`);
        } }] : []),
    ];
    const lastIsPlan = !busy && items.length > 0 && items[items.length - 1].kind === "text" && items[items.length - 1].mode === "plan";

    return (
        <div style={{ position: "fixed", inset: 0, background: "var(--bg)", zIndex: 25, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "8px 8px 6px" }}>
                <MenuButton onClick={() => setMenuOpen(true)} />
                <span style={{ display: "flex", flexDirection: "column", minWidth: 0, flex: 1 }}>
                    <span style={{ fontWeight: 700, color: "var(--text)", fontSize: "15px" }}>Sem Code</span>
                    {repoLine && <span style={{ fontSize: "11px", color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{repoLine}</span>}
                </span>
                <HeaderStatus token={token} onFeed={() => { setFeedOpen(true); feed.acknowledgeErrors(); }} hasError={feed.hasError} busy={!!busy} />
                <button onClick={() => newChat(provider, "")} disabled={!!busy} aria-label="New chat with another repo" title="New chat with another repo" style={iconBtn}>
                    <PlusIcon size={18} />
                </button>
                <ChatMenu title={chat.title || "Sem Code"} messages={transcript} extra={codeActions} />
            </div>
            <div style={{ display: "flex", gap: "8px", padding: "0 12px 10px", borderBottom: "1px solid var(--border)" }}>
                <select value={provider} onChange={e => pickRepo(e.target.value, "")} style={field}>
                    <option value="github">GitHub</option>
                    <option value="gitlab">GitLab</option>
                </select>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <RepoPicker floating repos={repos} value={repo} placeholder="Select a repository"
                        onChange={v => pickRepo(provider, v)} />
                </div>
            </div>
            <AgentFeedPanel open={feedOpen} onClose={() => setFeedOpen(false)} events={feed.events}
                title={`Activity · ${chat.title || "New chat"}`} />
            {extraRepos.length > 0 && (
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", padding: "0 12px 8px", borderBottom: "1px solid var(--border)" }}>
                    {extraRepos.map(x => (
                        <span key={x.repo} style={{ display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "12px", border: "1px solid var(--border)", borderRadius: "999px", padding: "3px 4px 3px 10px", color: "var(--text-muted)" }}>
                            {x.repo}
                            <button onClick={() => removeRepo(x.repo)} aria-label={`Remove ${x.repo}`} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", display: "inline-flex", padding: "2px" }}><CloseIcon size={12} /></button>
                        </span>
                    ))}
                </div>
            )}
            {addingRepo && <AddRepoSheet token={token} defaultProvider={provider} onPick={addRepo} onClose={() => setAddingRepo(false)} />}
            <TabDrawer open={menuOpen} onClose={() => setMenuOpen(false)} title="Sem Code" current="code"
                onNavigate={onNavigate} onNew={() => newChat()} chats={chats} activeId={chat.id} disabled={!!busy}
                onSelect={id => { selectChat(id); setOpened(null); setNotice(""); }} onDelete={deleteChat}
                subtitle={c => [[c.repo, ...(c.extraRepos || []).map(x => x.repo.split("/")[1])].filter(Boolean).join(", ") || "no repo", c.branch].filter(Boolean).join(" · ")} />

            {repo && showAutomations && <Automations token={token} provider={provider} repo={repo} onUnauthorized={onUnauthorized} />}
            {reposError && <div style={{ padding: "8px 16px", fontSize: "12px", color: "var(--danger)", borderBottom: "1px solid var(--border)" }}>{reposError}</div>}
            {notice && <div style={{ padding: "8px 16px", fontSize: "12px", color: "var(--text-muted)", borderBottom: "1px solid var(--border)", whiteSpace: "pre-wrap" }}>{notice}</div>}

            <div style={{ flex: 1, overflowY: "auto", padding: "12px 16px" }}>
                {!items.length && (
                    <div style={{ color: "var(--text-muted)", fontSize: "14px", lineHeight: 1.5 }}>
                        Pick a repo and say what to build or fix — Sem Code opens it for you. It works in its own copy on Modal
                        (shared by every chat on that repo) and nothing reaches your repo until it opens a PR. Use Plan first for bigger changes.
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
                    if (item.kind === "approval") return <ApprovalCard key={i} item={item} onDecide={decide} />;
                    if (item.kind === "handoff") return <HandoffCard key={i} tab={item.tab} task={item.task} onHandoff={onHandoff} />;
                    if (item.kind === "error") return (
                        <div key={i}>
                            <div className={errorClass(item.text)}>{item.text}</div>
                            <SuggestModel suggest={item.suggest} onSwitch={id => { setModel(id); run(item.retry, mode, id); }} />
                        </div>
                    );
                    return <AssistantText key={i} text={item.text} token={token} />;
                })}
                {busy && <div style={{ color: "var(--text-muted)", fontSize: "13px", margin: "8px 0" }}>{busy}</div>}
                {lastIsPlan && (
                    <button className="btn-primary" onClick={() => run("Go ahead and implement the plan above.", "act")} style={{ ...btn, margin: "8px 0", background: "var(--accent)", color: "var(--accent-contrast)" }}>
                        Approve plan &amp; run
                    </button>
                )}
                {compacting && <div style={{ color: "var(--text-muted)", fontSize: "13px", margin: "8px 0" }}>Compacting the conversation…</div>}
                <div ref={endRef} />
            </div>

            <div style={{ padding: "8px 8px 20px" }}>
                <div style={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "20px", padding: "10px 14px 8px" }}>
                    <AttachedChips files={files} setFiles={setFiles} />
                    <textarea
                        value={input} rows={2} disabled={!repo}
                        onChange={e => setInput(e.target.value)}
                        onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); run(input); } }}
                        placeholder={repo ? "Type / for commands" : "Pick a repo first"}
                        style={{ width: "100%", background: "transparent", border: "none", color: "var(--text)", fontSize: "15px", outline: "none", resize: "none", fontFamily: "inherit" }}
                    />
                    <div style={{ display: "flex", alignItems: "center", gap: "6px", minWidth: 0 }}>
                        <PlusMenu commands={COMMANDS} onCommand={c => (c.arg ? setInput(`/${c.name} `) : runCommand(c.name))}
                            onFiles={addFiles} onConnectors={() => setConnectorsOpen(true)} disabled={!!busy}
                            extraItems={[{ label: "Add repo", icon: <CodeIcon size={18} />, onClick: () => setAddingRepo(true) }]} />
                        <VoiceInput value={input} onChange={setInput} />
                        <ModeMenu mode={mode} onChange={pickMode} />
                        <ModelPicker token={token} value={model} onChange={setModel} storageKey="semblance_code_model" />
                        <span style={{ flex: 1 }} />
                        <ContextRing budget={budget} onCompact={compactNow} busy={!!busy || compacting} />
                        <button
                            onClick={busy && abortRef.current ? () => abortRef.current.abort() : () => run(input)}
                            disabled={!repo}
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
