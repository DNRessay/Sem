import { useState } from "react";

const API = import.meta.env.VITE_API_URL || "";
const field = { width: "100%", boxSizing: "border-box", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "10px", padding: "12px 14px", color: "var(--text)", fontSize: "15px", outline: "none" };
const linkBtn = { background: "none", border: "none", color: "var(--text-muted)", fontSize: "13px", cursor: "pointer", marginTop: "14px", textDecoration: "underline", padding: 0 };

// The token from a reset email link (#reset=…). Kept in the fragment so it never reaches a server log.
export function resetTokenFromUrl() {
    const m = window.location.hash.match(/^#reset=([A-Za-z0-9_-]{20,})$/);
    return m ? m[1] : "";
}

async function post(path, body) {
    const res = await fetch(`${API}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Something went wrong (${res.status})`);
    return data;
}

// Log in with the passphrase; "Forgot passphrase?" emails a reset link to an allowed address; opening that link
// lands here with #reset=… to choose a new one (which signs out every other device).
export default function Login({ onLoggedIn }) {
    const resetToken = resetTokenFromUrl();
    const [view, setView] = useState(resetToken ? "reset" : "login"); // login | forgot | sent | reset
    const [passphrase, setPassphrase] = useState("");
    const [again, setAgain] = useState("");
    const [email, setEmail] = useState("");
    const [error, setError] = useState(null);
    const [busy, setBusy] = useState(false);

    const run = async (fn) => {
        if (busy) return;
        setBusy(true); setError(null);
        try { await fn(); } catch (e) { setError(e.message); } finally { setBusy(false); }
    };
    const login = () => passphrase.trim() && run(async () => onLoggedIn((await post("/auth/login", { passphrase })).token));
    const ask = () => email.trim() && run(async () => { await post("/auth/reset/request", { email }); setView("sent"); });
    const reset = () => run(async () => {
        if (passphrase !== again) throw new Error("The two passphrases don't match");
        const { token } = await post("/auth/reset/confirm", { token: resetToken, passphrase });
        history.replaceState(null, "", window.location.pathname + window.location.search);
        onLoggedIn(token);
    });
    const go = (v) => { setView(v); setError(null); setPassphrase(""); setAgain(""); };

    const titles = {
        login: "Enter your passphrase to continue",
        forgot: "We'll email you a link to set a new passphrase",
        sent: "Check your email",
        reset: "Choose a new passphrase",
    };
    const submit = { login, forgot: ask, reset }[view];

    return (
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", height: "100%", background: "var(--bg)", padding: "24px", boxSizing: "border-box" }}>
            <div style={{ width: "100%", maxWidth: "320px", display: "flex", flexDirection: "column" }}>
                <div style={{ textAlign: "center", marginBottom: "28px" }}>
                    <div style={{ fontWeight: "700", fontSize: "20px", color: "var(--text)", letterSpacing: "1px" }}>SEMBLANCE</div>
                    <div style={{ color: "var(--text-muted)", fontSize: "13px", marginTop: "4px" }}>{titles[view]}</div>
                </div>

                {view === "login" && (
                    <input type="password" value={passphrase} onChange={e => setPassphrase(e.target.value)} onKeyDown={e => e.key === "Enter" && login()}
                        placeholder="Passphrase" autoFocus autoComplete="current-password" style={field} />
                )}
                {view === "forgot" && (
                    <input type="email" value={email} onChange={e => setEmail(e.target.value)} onKeyDown={e => e.key === "Enter" && ask()}
                        placeholder="Your email" autoFocus autoComplete="email" style={field} />
                )}
                {view === "sent" && (
                    <div style={{ color: "var(--text)", fontSize: "14px", lineHeight: 1.5, textAlign: "center" }}>
                        If that address is allowed, a reset link is on its way. It works once, for 30 minutes.
                    </div>
                )}
                {view === "reset" && (
                    <>
                        <input type="password" value={passphrase} onChange={e => setPassphrase(e.target.value)} placeholder="New passphrase (12+ characters)"
                            autoFocus autoComplete="new-password" style={field} />
                        <input type="password" value={again} onChange={e => setAgain(e.target.value)} onKeyDown={e => e.key === "Enter" && reset()}
                            placeholder="Same again" autoComplete="new-password" style={{ ...field, marginTop: "10px" }} />
                    </>
                )}

                {error && <div style={{ color: "var(--danger)", fontSize: "13px", marginTop: "10px" }}>{error}</div>}

                {submit && (
                    <button onClick={submit} disabled={busy} className="btn-primary"
                        style={{ width: "100%", marginTop: "14px", padding: "12px", background: "var(--accent)", border: "none", borderRadius: "10px", color: "var(--accent-contrast)", fontSize: "15px", fontWeight: "600", cursor: busy ? "default" : "pointer", opacity: busy ? 0.6 : 1 }}>
                        {busy ? "Working…" : { login: "Continue", forgot: "Send reset link", reset: "Set passphrase" }[view]}
                    </button>
                )}
                {view === "login" && <button onClick={() => go("forgot")} style={linkBtn}>Forgot passphrase?</button>}
                {view !== "login" && <button onClick={() => { history.replaceState(null, "", window.location.pathname); go("login"); }} style={linkBtn}>Back to log in</button>}
            </div>
        </div>
    );
}
