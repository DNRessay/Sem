import { useState } from "react";

const API = import.meta.env.VITE_API_URL || "";

export default function Login({ onLoggedIn }) {
    const [passphrase, setPassphrase] = useState("");
    const [error, setError] = useState(null);
    const [busy, setBusy] = useState(false);

    const submit = async () => {
        if (!passphrase.trim() || busy) return;
        setBusy(true);
        setError(null);
        try {
            const res = await fetch(`${API}/auth/login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ passphrase }),
            });
            if (!res.ok) {
                const data = await res.json().catch(() => ({}));
                throw new Error(data.detail || "Incorrect passphrase");
            }
            const data = await res.json();
            onLoggedIn(data.token);
        } catch (e) {
            setError(e.message);
        } finally {
            setBusy(false);
        }
    };

    return (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", background: "var(--bg)", padding: "24px", boxSizing: "border-box" }}>
            <div style={{ width: "100%", maxWidth: "320px" }}>
                <div style={{ textAlign: "center", marginBottom: "28px" }}>
                    <div style={{ fontWeight: "700", fontSize: "20px", color: "var(--text)", letterSpacing: "1px" }}>SEMBLANCE</div>
                    <div style={{ color: "var(--text-muted)", fontSize: "13px", marginTop: "4px" }}>Enter your passphrase to continue</div>
                </div>
                <input
                    type="password"
                    value={passphrase}
                    onChange={e => setPassphrase(e.target.value)}
                    onKeyDown={e => e.key === "Enter" && submit()}
                    placeholder="Passphrase"
                    autoFocus
                    style={{ width: "100%", boxSizing: "border-box", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "10px", padding: "12px 14px", color: "var(--text)", fontSize: "15px", outline: "none" }}
                />
                {error && (
                    <div style={{ color: "var(--danger)", fontSize: "13px", marginTop: "10px" }}>{error}</div>
                )}
                <button
                    onClick={submit}
                    disabled={busy}
                    style={{ width: "100%", marginTop: "14px", padding: "12px", background: "var(--accent)", border: "none", borderRadius: "10px", color: "var(--accent-contrast)", fontSize: "15px", fontWeight: "600", cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1 }}
                >
                    {busy ? "Checking…" : "Continue"}
                </button>
            </div>
        </div>
    );
}
