import { useState, useRef } from "react";

const API = import.meta.env.VITE_API_URL || "";
const TEXT_EXT = /\.(txt|md|py|js|jsx|ts|tsx|json|csv|log|ya?ml|html?|css|sql|sh|env|toml|ini|xml)$/i;

function ClipIcon() {
    return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48" />
        </svg>
    );
}

function RepoForm({ provider, token, onAttach, onNeedConnector, onClose }) {
    const [repo, setRepo] = useState("");
    const [path, setPath] = useState("");
    const [ref, setRef] = useState("");
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState(null);

    const submit = async () => {
        if (!repo.trim() || !path.trim() || busy) return;
        setBusy(true);
        setError(null);
        try {
            const res = await fetch(`${API}/connectors/${provider}/fetch`, {
                method: "POST",
                headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({ repo: repo.trim(), path: path.trim(), ref: ref.trim() }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                if (res.status === 400 && (data.detail || "").toLowerCase().includes("no ")) {
                    onNeedConnector();
                    return;
                }
                throw new Error(data.detail || `Fetch failed (${res.status})`);
            }
            onAttach({ name: `${repo}/${path}`, content: data.content });
            onClose();
        } catch (e) {
            setError(e.message);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: "6px" }}>
            <input value={repo} onChange={e => setRepo(e.target.value)} placeholder="owner/repo"
                style={inputStyle} />
            <input value={path} onChange={e => setPath(e.target.value)} placeholder="path/to/file.py"
                style={inputStyle} />
            <input value={ref} onChange={e => setRef(e.target.value)} placeholder="branch (optional)"
                style={inputStyle} />
            {error && <div style={{ color: "var(--danger)", fontSize: "12px" }}>{error}</div>}
            <button onClick={submit} disabled={busy} style={smallButtonStyle}>
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

const smallButtonStyle = {
    padding: "8px", borderRadius: "8px", border: "none", background: "var(--accent)",
    color: "var(--accent-contrast)", fontSize: "13px", fontWeight: "600", cursor: "pointer",
};

export default function AttachMenu({ token, onAttach }) {
    const [open, setOpen] = useState(false);
    const [view, setView] = useState("menu"); // menu | github | gitlab | github-connect | gitlab-connect
    const fileInputRef = useRef(null);

    const close = () => { setOpen(false); setView("menu"); };

    const handleFiles = async (e) => {
        const files = Array.from(e.target.files || []);
        for (const file of files) {
            if (!TEXT_EXT.test(file.name)) continue; // skip binaries — these models read text, not images
            const content = await file.text();
            onAttach({ name: file.name, content });
        }
        e.target.value = "";
        close();
    };

    return (
        <div style={{ position: "relative" }}>
            <button
                onClick={() => setOpen(v => !v)}
                aria-label="Attach"
                style={{
                    width: "32px", height: "32px", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
                    background: "none", border: "1px solid var(--border)", borderRadius: "50%",
                    color: "var(--text-muted)", cursor: "pointer",
                }}
            >
                <ClipIcon />
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
                                <MenuRow label="Upload file" onClick={() => fileInputRef.current?.click()} />
                                <MenuRow label="Add from GitHub" onClick={() => setView("github")} />
                                <MenuRow label="Add from GitLab" onClick={() => setView("gitlab")} />
                            </div>
                        )}
                        {(view === "github" || view === "gitlab") && (
                            <RepoForm
                                provider={view}
                                token={token}
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

function MenuRow({ label, onClick }) {
    return (
        <button
            onClick={onClick}
            style={{
                display: "block", width: "100%", textAlign: "left", padding: "10px 14px",
                background: "none", border: "none", color: "var(--text)", fontSize: "14px", cursor: "pointer",
            }}
        >
            {label}
        </button>
    );
}
