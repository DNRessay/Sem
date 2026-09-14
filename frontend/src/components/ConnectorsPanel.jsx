import { useState, useEffect, useRef } from "react";

const API = import.meta.env.VITE_API_URL || "";

// "real" providers have a working OAuth/token flow on the backend
// (gateway/connectors.py's _PROVIDERS) — the rest are listed so the
// directory shows what's coming, same as AttachMenu's "Deep research"
// row, but nothing happens when you click them yet: wiring Google
// Calendar/Drive needs real OAuth app credentials registered with Google
// first, a separate setup step from anything this panel can do alone.
const PROVIDERS = [
    { id: "github", label: "GitHub", real: true },
    { id: "gitlab", label: "GitLab", real: true },
    { id: "google-calendar", label: "Google Calendar", real: false },
    { id: "google-drive", label: "Google Drive", real: false },
];

export default function ConnectorsPanel({ token }) {
    const [connected, setConnected] = useState([]);
    const [tokens, setTokens] = useState({ github: "", gitlab: "" });
    const [showManual, setShowManual] = useState({ github: false, gitlab: false });
    const [oauthError, setOauthError] = useState({});
    const [busy, setBusy] = useState(null);
    const loadRef = useRef(() => {});

    const authHeaders = { Authorization: `Bearer ${token}` };

    const load = () => {
        fetch(`${API}/connectors`, { headers: authHeaders })
            .then(r => r.json())
            .then(d => setConnected(d.connectors || []))
            .catch(() => {});
    };
    loadRef.current = load;

    useEffect(() => {
        load();
        // Connecting happens in a new tab (the provider's own consent
        // screen); re-check as soon as the user comes back to this one
        // rather than making them manually refresh to see "Connected".
        const onFocus = () => loadRef.current();
        window.addEventListener("focus", onFocus);
        return () => window.removeEventListener("focus", onFocus);
    }, []);

    const connectViaOAuth = async (provider) => {
        setBusy(provider);
        setOauthError(e => ({ ...e, [provider]: null }));
        try {
            const res = await fetch(`${API}/connectors/${provider}/authorize`, { headers: authHeaders });
            const data = await res.json().catch(() => ({}));
            if (!res.ok) {
                setOauthError(e => ({ ...e, [provider]: data.detail || "OAuth isn't set up for this provider yet" }));
                setShowManual(s => ({ ...s, [provider]: true }));
                return;
            }
            window.open(data.url, "_blank", "noopener");
        } finally {
            setBusy(null);
        }
    };

    const save = async (provider) => {
        const value = tokens[provider].trim();
        if (!value) return;
        setBusy(provider);
        try {
            await fetch(`${API}/connectors/${provider}`, {
                method: "POST",
                headers: { "Content-Type": "application/json", ...authHeaders },
                body: JSON.stringify({ token: value }),
            });
            setTokens(t => ({ ...t, [provider]: "" }));
            load();
        } finally {
            setBusy(null);
        }
    };

    const disconnect = async (provider) => {
        setBusy(provider);
        try {
            await fetch(`${API}/connectors/${provider}`, { method: "DELETE", headers: authHeaders });
            load();
        } finally {
            setBusy(null);
        }
    };

    const connectedReal = PROVIDERS.filter(p => p.real && connected.includes(p.id));
    const available = PROVIDERS.filter(p => !(p.real && connected.includes(p.id)));

    const renderCard = (p) => {
        const provider = p.id;
        const isConnected = connected.includes(provider);
        return (
            <div key={provider} style={{ border: "1px solid var(--border)", borderRadius: "8px", padding: "8px 10px" }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span style={{ fontSize: "13px", color: p.real ? "var(--text)" : "var(--text-muted)" }}>{p.label}</span>
                    {p.real ? (
                        <span style={{ fontSize: "11px", color: isConnected ? "var(--accent)" : "var(--text-muted)" }}>
                            {isConnected ? "Connected" : "Not connected"}
                        </span>
                    ) : (
                        <span style={{ fontSize: "10px", color: "var(--text-muted)", border: "1px solid var(--border)", borderRadius: "999px", padding: "1px 6px" }}>Soon</span>
                    )}
                </div>
                {!p.real ? null : isConnected ? (
                    <button onClick={() => disconnect(provider)} disabled={busy === provider}
                        style={{ marginTop: "6px", fontSize: "12px", background: "none", border: "none", color: "var(--danger)", cursor: "pointer", padding: 0 }}>
                        {busy === provider ? "Removing…" : "Disconnect"}
                    </button>
                ) : (
                    <div style={{ marginTop: "6px" }}>
                        <button onClick={() => connectViaOAuth(provider)} disabled={busy === provider}
                            style={{ width: "100%", fontSize: "12px", fontWeight: "600", background: "var(--accent)", color: "var(--accent-contrast)", border: "none", borderRadius: "6px", padding: "8px 10px", cursor: "pointer" }}>
                            {busy === provider ? "Opening…" : `Connect ${p.label}`}
                        </button>
                        {oauthError[provider] && (
                            <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "6px" }}>{oauthError[provider]}</div>
                        )}
                        {!showManual[provider] ? (
                            <button onClick={() => setShowManual(s => ({ ...s, [provider]: true }))}
                                style={{ marginTop: "6px", fontSize: "11px", background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", padding: 0, textDecoration: "underline" }}>
                                or paste a token instead
                            </button>
                        ) : (
                            <div style={{ display: "flex", gap: "6px", marginTop: "6px" }}>
                                <input
                                    type="password"
                                    value={tokens[provider]}
                                    onChange={e => setTokens(t => ({ ...t, [provider]: e.target.value }))}
                                    placeholder={provider === "github" ? "ghp_..." : "glpat-..."}
                                    style={{ flex: 1, minWidth: 0, background: "var(--bg)", border: "1px solid var(--border)", borderRadius: "6px", padding: "6px 8px", color: "var(--text)", fontSize: "12px", outline: "none" }}
                                />
                                <button onClick={() => save(provider)} disabled={busy === provider}
                                    style={{ fontSize: "12px", background: "var(--accent)", color: "var(--accent-contrast)", border: "none", borderRadius: "6px", padding: "6px 10px", cursor: "pointer" }}>
                                    {busy === provider ? "…" : "Save"}
                                </button>
                            </div>
                        )}
                    </div>
                )}
            </div>
        );
    };

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
            {connectedReal.length > 0 && (
                <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                    <div style={{ fontSize: "10px", fontWeight: "600", letterSpacing: "1px", color: "var(--text-muted)" }}>CONNECTED</div>
                    {connectedReal.map(renderCard)}
                </div>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
                <div style={{ fontSize: "10px", fontWeight: "600", letterSpacing: "1px", color: "var(--text-muted)" }}>AVAILABLE TO CONNECT</div>
                {available.map(renderCard)}
            </div>
        </div>
    );
}
