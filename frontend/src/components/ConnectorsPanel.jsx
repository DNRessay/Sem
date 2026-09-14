import { useState, useEffect, useRef } from "react";

const API = import.meta.env.VITE_API_URL || "";
const PROVIDERS = ["github", "gitlab"];

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

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: "10px" }}>
            {PROVIDERS.map(provider => {
                const isConnected = connected.includes(provider);
                return (
                    <div key={provider} style={{ border: "1px solid var(--border)", borderRadius: "8px", padding: "8px 10px" }}>
                        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                            <span style={{ fontSize: "13px", color: "var(--text)", textTransform: "capitalize" }}>{provider}</span>
                            <span style={{ fontSize: "11px", color: isConnected ? "var(--accent)" : "var(--text-muted)" }}>
                                {isConnected ? "Connected" : "Not connected"}
                            </span>
                        </div>
                        {isConnected ? (
                            <button onClick={() => disconnect(provider)} disabled={busy === provider}
                                style={{ marginTop: "6px", fontSize: "12px", background: "none", border: "none", color: "var(--danger)", cursor: "pointer", padding: 0 }}>
                                {busy === provider ? "Removing…" : "Disconnect"}
                            </button>
                        ) : (
                            <div style={{ marginTop: "6px" }}>
                                <button onClick={() => connectViaOAuth(provider)} disabled={busy === provider}
                                    style={{ width: "100%", fontSize: "12px", fontWeight: "600", background: "var(--accent)", color: "var(--accent-contrast)", border: "none", borderRadius: "6px", padding: "8px 10px", cursor: "pointer" }}>
                                    {busy === provider ? "Opening…" : `Connect ${provider}`}
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
            })}
        </div>
    );
}
