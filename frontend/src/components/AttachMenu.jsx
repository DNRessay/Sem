import { useState, useRef, useEffect } from "react";

const API = import.meta.env.VITE_API_URL || "";
const TEXT_EXT = /\.(txt|md|mdx|py|js|jsx|ts|tsx|mjs|cjs|json|jsonc|csv|tsv|log|ya?ml|html?|css|scss|sass|less|sql|sh|bash|zsh|env|toml|ini|cfg|conf|xml|svg|graphql|gql|proto|rs|go|java|kt|kts|c|h|cpp|cc|hpp|cs|rb|php|swift|dart|lua|r|jl|vue|svelte|diff|patch|lock|gitignore|editorconfig)$/i;
const BARE_TEXT_NAMES = /^(dockerfile|makefile|license|readme|procfile|jenkinsfile|vagrantfile)$/i;
const IMAGE_EXT = /\.(png|jpe?g|gif|webp)$/i;
const DOC_EXT = /\.(pdf|docx)$/i;
const MAX_BINARY_BYTES = 4 * 1024 * 1024; // Lambda Function URL request body caps around 6MB; base64 adds ~33%
const MIME_BY_EXT = {
    pdf: "application/pdf",
    docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    png: "image/png", jpg: "image/jpeg", jpeg: "image/jpeg", gif: "image/gif", webp: "image/webp",
};

function extOf(name) {
    return (name.split(".").pop() || "").toLowerCase();
}

async function readAsBase64(file) {
    const buf = await file.arrayBuffer();
    const bytes = new Uint8Array(buf);
    let binary = "";
    const chunk = 0x8000;
    for (let i = 0; i < bytes.length; i += chunk) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
    }
    return btoa(binary);
}

export function UploadIcon() {
    return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="17 8 12 3 7 8" />
            <line x1="12" y1="3" x2="12" y2="15" />
        </svg>
    );
}

export function GitHubIcon() {
    return (
        <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path fillRule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
        </svg>
    );
}

export function GitLabIcon() {
    return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
            <path d="M22.65 14.39L12 22.13 1.35 14.39a.84.84 0 0 1-.3-.94l1.22-3.78L4.71 2.16a.42.42 0 0 1 .8 0l2.44 7.51h8.1l2.44-7.51a.42.42 0 0 1 .8 0l2.44 7.51 1.22 3.78a.84.84 0 0 1-.3.94z" />
        </svg>
    );
}

export function ImageIcon() {
    return (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="3" width="18" height="18" rx="2" />
            <circle cx="8.5" cy="8.5" r="1.5" />
            <path d="M21 15l-5-5L5 21" />
        </svg>
    );
}

export function AttachFileIcon() {
    return (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
        </svg>
    );
}

function FolderIcon() {
    return (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z" />
        </svg>
    );
}

function FileIcon() {
    return (
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
        </svg>
    );
}

function RepoPicker({ repos, value, onChange }) {
    const [open, setOpen] = useState(false);
    const [query, setQuery] = useState("");
    const filtered = query.trim()
        ? repos.filter(r => r.full_name.toLowerCase().includes(query.trim().toLowerCase()))
        : repos;

    if (!open) {
        return (
            <button
                onClick={() => setOpen(true)}
                style={{
                    ...inputStyle, display: "flex", alignItems: "center", justifyContent: "space-between",
                    cursor: "pointer", textAlign: "left",
                }}
            >
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {value || "Select a repository"}
                </span>
                <span style={{ fontSize: "10px", color: "var(--text-muted)", flexShrink: 0, marginLeft: "6px" }}>▾</span>
            </button>
        );
    }

    return (
        <div style={{ border: "1px solid var(--border)", borderRadius: "8px", overflow: "hidden" }}>
            <input
                autoFocus
                value={query}
                onChange={e => setQuery(e.target.value)}
                onBlur={() => setTimeout(() => setOpen(false), 150)} // let the click below land first
                placeholder="Search repositories…"
                style={{ ...inputStyle, border: "none", borderRadius: 0, borderBottom: "1px solid var(--border)" }}
            />
            <div style={{ maxHeight: "160px", overflowY: "auto" }}>
                {filtered.length === 0 && (
                    <div style={{ padding: "8px 10px", fontSize: "12px", color: "var(--text-muted)" }}>No matches</div>
                )}
                {filtered.map(r => (
                    <button
                        key={r.full_name}
                        onMouseDown={e => e.preventDefault()} // survive the input's onBlur firing first
                        onClick={() => { onChange(r.full_name); setOpen(false); setQuery(""); }}
                        style={{
                            display: "block", width: "100%", textAlign: "left", padding: "8px 10px",
                            background: r.full_name === value ? "var(--bg)" : "none", border: "none",
                            color: "var(--text)", fontSize: "13px", cursor: "pointer",
                        }}
                    >
                        {r.full_name}{r.private ? " (private)" : ""}
                    </button>
                ))}
            </div>
        </div>
    );
}

function RepoForm({ provider, token, sessionId, onAttach, onNeedConnector, onClose }) {
    const [repos, setRepos] = useState(null); // null = still loading
    const [loadError, setLoadError] = useState(null);
    const [repo, setRepo] = useState("");
    const [branch, setBranch] = useState("");
    const [branches, setBranches] = useState([]);
    const [dirPath, setDirPath] = useState(""); // folder currently being browsed, "" = root
    const [entries, setEntries] = useState([]);
    const [entriesLoading, setEntriesLoading] = useState(false);
    const [selected, setSelected] = useState(""); // chosen file path
    const [busy, setBusy] = useState(false);
    const [repoBusy, setRepoBusy] = useState(false);
    const [error, setError] = useState(null);

    useEffect(() => {
        let cancelled = false;
        (async () => {
            try {
                const res = await fetch(`${API}/connectors/${provider}/repos`, {
                    headers: { Authorization: `Bearer ${token}` },
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) {
                    if (res.status === 400 && (data.detail || "").toLowerCase().includes("no ")) {
                        onNeedConnector();
                        return;
                    }
                    throw new Error(data.detail || `Couldn't load repos (${res.status})`);
                }
                if (cancelled) return;
                const list = data.repos || [];
                setRepos(list);
                if (list.length > 0) setRepo(list[0].full_name);
            } catch (e) {
                if (!cancelled) setLoadError(e.message);
            }
        })();
        return () => { cancelled = true; };
    }, [provider, token]);

    // Picking a different repo resets the browser back to its root and
    // reloads that repo's branches, defaulting to its actual default branch
    // instead of leaving the user to type one from memory.
    useEffect(() => {
        if (!repo) return;
        let cancelled = false;
        setDirPath("");
        setSelected("");
        setEntries([]);
        setError(null);
        const defaultBranch = repos?.find(r => r.full_name === repo)?.default_branch || "";
        setBranch(defaultBranch);
        (async () => {
            try {
                const res = await fetch(`${API}/connectors/${provider}/branches?repo=${encodeURIComponent(repo)}`, {
                    headers: { Authorization: `Bearer ${token}` },
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) return;
                if (cancelled) return;
                const list = data.branches || [];
                setBranches(list);
                if (!defaultBranch && list.length > 0) setBranch(list[0]);
            } catch {
                // Branch dropdown is a convenience, not required — the tree/
                // fetch calls below fall back to the provider's own default
                // ref when branch is left empty.
            }
        })();
        return () => { cancelled = true; };
    }, [repo]);

    // Every folder navigation (or a branch switch) reloads the current
    // directory's listing.
    useEffect(() => {
        if (!repo) return;
        let cancelled = false;
        setEntriesLoading(true);
        (async () => {
            try {
                const params = new URLSearchParams({ repo, path: dirPath });
                if (branch) params.set("ref", branch);
                const res = await fetch(`${API}/connectors/${provider}/tree?${params}`, {
                    headers: { Authorization: `Bearer ${token}` },
                });
                const data = await res.json().catch(() => ({}));
                if (!res.ok) throw new Error(data.detail || `Couldn't load folder (${res.status})`);
                if (cancelled) return;
                setEntries(data.entries || []);
            } catch (e) {
                if (!cancelled) { setEntries([]); setError(e.message); }
            } finally {
                if (!cancelled) setEntriesLoading(false);
            }
        })();
        return () => { cancelled = true; };
    }, [provider, repo, branch, dirPath]);

    const crumbs = dirPath ? dirPath.split("/") : [];

    const submitRepo = async () => {
        if (repoBusy) return;
        if (!repo) { setError("Pick a repository first"); return; }
        setRepoBusy(true);
        setError(null);
        try {
            const res = await fetch(`${API}/connectors/${provider}/fetch-repo`, {
                method: "POST",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({ repo, ref: branch, session_id: sessionId }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                if (res.status === 400 && (data.detail || "").toLowerCase().includes("no ")) {
                    onNeedConnector();
                    return;
                }
                throw new Error(data.detail || `Fetch failed (${res.status})`);
            }
            onAttach({ name: repo, content: data.content, source: provider });
            onClose();
        } catch (e) {
            setError(e.message);
        } finally {
            setRepoBusy(false);
        }
    };

    const submit = async () => {
        if (busy) return;
        if (!repo) { setError("Pick a repository first"); return; }
        if (!selected) { setError("Pick a file first"); return; }
        setBusy(true);
        setError(null);
        try {
            const res = await fetch(`${API}/connectors/${provider}/fetch`, {
                method: "POST",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({ repo, path: selected, ref: branch }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                if (res.status === 400 && (data.detail || "").toLowerCase().includes("no ")) {
                    onNeedConnector();
                    return;
                }
                throw new Error(data.detail || `Fetch failed (${res.status})`);
            }
            onAttach({ name: `${repo}/${selected}`, content: data.content, source: provider });
            onClose();
        } catch (e) {
            setError(e.message);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: "6px", width: "260px", maxWidth: "80vw" }}>
            {repos === null && !loadError && (
                <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>Loading repos…</div>
            )}
            {loadError && <div style={{ color: "var(--danger)", fontSize: "12px" }}>{loadError}</div>}
            {repos?.length === 0 && (
                <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>No repos found on this account.</div>
            )}
            {repos?.length > 0 && (
                <>
                    <RepoPicker repos={repos} value={repo} onChange={setRepo} />
                    {branches.length > 0 && (
                        <select value={branch} onChange={e => setBranch(e.target.value)} style={inputStyle}>
                            {branches.map(b => <option key={b} value={b}>{b}</option>)}
                        </select>
                    )}
                    <button onClick={submitRepo} disabled={repoBusy} style={smallButtonStyle}>
                        {repoBusy ? "Adding repo…" : `Add ${repo}`}
                    </button>
                    <div style={{ fontSize: "11px", color: "var(--text-muted)", textAlign: "center" }}>or pick a single file</div>
                    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: "2px", fontSize: "11px", color: "var(--text-muted)" }}>
                        <button onClick={() => setDirPath("")} style={crumbStyle}>{repo.split("/")[1] || repo}</button>
                        {crumbs.map((c, i) => (
                            <span key={i} style={{ display: "flex", alignItems: "center", gap: "2px" }}>
                                <span>/</span>
                                <button onClick={() => setDirPath(crumbs.slice(0, i + 1).join("/"))} style={crumbStyle}>{c}</button>
                            </span>
                        ))}
                    </div>
                    <div style={{ border: "1px solid var(--border)", borderRadius: "8px", maxHeight: "170px", overflowY: "auto" }}>
                        {entriesLoading && (
                            <div style={{ padding: "8px 10px", fontSize: "12px", color: "var(--text-muted)" }}>Loading…</div>
                        )}
                        {!entriesLoading && entries.length === 0 && (
                            <div style={{ padding: "8px 10px", fontSize: "12px", color: "var(--text-muted)" }}>Empty folder</div>
                        )}
                        {!entriesLoading && entries.map(entry => (
                            <button
                                key={entry.path}
                                onClick={() => entry.type === "dir" ? setDirPath(entry.path) : setSelected(entry.path)}
                                style={{
                                    display: "flex", alignItems: "center", gap: "6px", width: "100%", textAlign: "left",
                                    padding: "6px 10px", background: entry.path === selected ? "var(--bg)" : "none",
                                    border: "none", color: "var(--text)", fontSize: "13px", cursor: "pointer",
                                }}
                            >
                                <span style={{ display: "flex", color: "var(--text-muted)", flexShrink: 0 }}>
                                    {entry.type === "dir" ? <FolderIcon /> : <FileIcon />}
                                </span>
                                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{entry.name}</span>
                            </button>
                        ))}
                    </div>
                    {selected && (
                        <div style={{ fontSize: "12px", color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            Selected: {selected}
                        </div>
                    )}
                </>
            )}
            {error && <div style={{ color: "var(--danger)", fontSize: "12px" }}>{error}</div>}
            <button onClick={submit} disabled={busy || !selected} style={smallButtonStyle}>
                {busy ? "Fetching…" : "Fetch file"}
            </button>
        </div>
    );
}

function ConnectorTokenForm({ provider, token, onSaved }) {
    const [value, setValue] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);
    const [manual, setManual] = useState(false);

    const connectViaOAuth = async () => {
        setBusy(true);
        setError(null);
        try {
            const res = await fetch(`${API}/connectors/${provider}/authorize`, {
                headers: { Authorization: `Bearer ${token}` },
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                setError(data.detail || "OAuth isn't set up for this provider yet");
                setManual(true);
                return;
            }
            window.open(data.url, "_blank", "noopener");
        } finally {
            setBusy(false);
        }
    };

    const save = async () => {
        if (!value.trim() || busy) return;
        setBusy(true);
        setError(null);
        try {
            const res = await fetch(`${API}/connectors/${provider}`, {
                method: "POST",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({ token: value.trim() }),
            });
            if (!res.ok) throw new Error(`Save failed (${res.status})`);
            onSaved();
        } catch (e) {
            setError(e.message);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: "6px" }}>
            <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>
                No {provider} connector yet.
            </div>
            {!manual ? (
                <>
                    <button onClick={connectViaOAuth} disabled={busy} style={smallButtonStyle}>
                        {busy ? "Opening…" : `Connect ${provider}`}
                    </button>
                    {error && <div style={{ color: "var(--text-muted)", fontSize: "12px" }}>{error}</div>}
                    <button onClick={() => setManual(true)}
                        style={{ background: "none", border: "none", color: "var(--text-muted)", fontSize: "11px", cursor: "pointer", padding: 0, textDecoration: "underline" }}>
                        or paste a token instead
                    </button>
                </>
            ) : (
                <>
                    <input value={value} onChange={e => setValue(e.target.value)} type="password"
                        placeholder={provider === "github" ? "ghp_..." : "glpat-..."} style={inputStyle} />
                    {error && <div style={{ color: "var(--danger)", fontSize: "12px" }}>{error}</div>}
                    <button onClick={save} disabled={busy} style={smallButtonStyle}>
                        {busy ? "Saving…" : "Save token"}
                    </button>
                </>
            )}
        </div>
    );
}

const inputStyle = {
    width: "100%", boxSizing: "border-box", background: "var(--bg)", border: "1px solid var(--border)",
    borderRadius: "8px", padding: "8px 10px", color: "var(--text)", fontSize: "13px", outline: "none",
};

const crumbStyle = {
    background: "none", border: "none", color: "var(--text-muted)", fontSize: "11px",
    cursor: "pointer", padding: 0, textDecoration: "underline",
};

const smallButtonStyle = {
    padding: "8px", borderRadius: "8px", border: "none", background: "var(--accent)",
    color: "var(--accent-contrast)", fontSize: "13px", fontWeight: "600", cursor: "pointer",
};

export default function AttachMenu({ token, sessionId, onAttach }) {
    const [open, setOpen] = useState(false);
    const [view, setView] = useState("menu"); // menu | github | gitlab | github-connect | gitlab-connect
    const [fileError, setFileError] = useState(null);
    const fileInputRef = useRef(null);

    const close = () => { setOpen(false); setView("menu"); setFileError(null); };

    const handleFiles = async (e) => {
        const files = Array.from(e.target.files || []);
        const skipped = [];
        for (const file of files) {
            const isText = TEXT_EXT.test(file.name) || BARE_TEXT_NAMES.test(file.name);
            const isBinary = IMAGE_EXT.test(file.name) || DOC_EXT.test(file.name);
            if (isText) {
                const content = await file.text();
                onAttach({ name: file.name, content, source: "file" });
            } else if (isBinary) {
                if (file.size > MAX_BINARY_BYTES) {
                    skipped.push(`${file.name} (too large — 4MB max)`);
                    continue;
                }
                const base64 = await readAsBase64(file);
                const mime = file.type || MIME_BY_EXT[extOf(file.name)] || "application/octet-stream";
                onAttach({ name: file.name, base64, mime, source: "file" });
            } else {
                skipped.push(file.name);
            }
        }
        e.target.value = "";
        if (skipped.length > 0) {
            setFileError(`Can't attach ${skipped.join(", ")} — unsupported file type.`);
        } else {
            close();
        }
    };

    return (
        <div style={{ position: "relative" }}>
            <button
                onClick={() => setOpen(v => !v)}
                aria-label="Add"
                style={{
                    width: "32px", height: "32px", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
                    background: "none", border: "1px solid var(--border)", borderRadius: "50%",
                    color: "var(--text-muted)", cursor: "pointer", fontSize: "17px", lineHeight: 1,
                }}
            >
                +
            </button>

            {open && (
                <>
                    <div onClick={close} style={{ position: "fixed", inset: 0, zIndex: 29 }} />
                    <div style={{
                        position: "absolute", bottom: "40px", left: 0, minWidth: "220px",
                        background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "12px",
                        boxShadow: "0 4px 16px rgba(0,0,0,0.15)", zIndex: 30, overflow: "hidden",
                    }}>
                        {view === "menu" && (
                            <div style={{ display: "flex", flexDirection: "column" }}>
                                <input ref={fileInputRef} type="file" multiple hidden onChange={handleFiles} />
                                <MenuRow icon={<UploadIcon />} label="Upload file" onClick={() => { setFileError(null); fileInputRef.current?.click(); }} />
                                <MenuRow icon={<GitHubIcon />} label="Add from GitHub" onClick={() => setView("github")} />
                                <MenuRow icon={<GitLabIcon />} label="Add from GitLab" onClick={() => setView("gitlab")} />
                                {fileError && (
                                    <div style={{ padding: "0 14px 10px", fontSize: "11px", color: "var(--danger)", lineHeight: "1.4" }}>
                                        {fileError}
                                    </div>
                                )}
                            </div>
                        )}
                        {(view === "github" || view === "gitlab") && (
                            <RepoForm
                                provider={view}
                                token={token}
                                sessionId={sessionId}
                                onAttach={onAttach}
                                onNeedConnector={() => setView(`${view}-connect`)}
                                onClose={close}
                            />
                        )}
                        {(view === "github-connect" || view === "gitlab-connect") && (
                            <ConnectorTokenForm
                                provider={view.replace("-connect", "")}
                                token={token}
                                onSaved={() => setView(view.replace("-connect", ""))}
                            />
                        )}
                    </div>
                </>
            )}
        </div>
    );
}

function MenuRow({ icon, label, onClick }) {
    return (
        <button
            onClick={onClick}
            style={{
                display: "flex", alignItems: "center", gap: "10px", width: "100%", textAlign: "left", padding: "10px 14px",
                background: "none", border: "none", color: "var(--text)", fontSize: "14px", cursor: "pointer",
            }}
        >
            <span style={{ display: "flex", color: "var(--text-muted)" }}>{icon}</span>
            {label}
        </button>
    );
}
