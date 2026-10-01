import { useEffect, useState } from "react";

const API = import.meta.env.VITE_API_URL || "";

// This month's AWS bill in rand (free CloudWatch estimate, refreshed every 6 hours server-side).
export function AwsCost({ token }) {
    const [bill, setBill] = useState(null);
    useEffect(() => {
        if (!token) return;
        fetch(`${API}/settings/aws-cost`, { headers: { Authorization: `Bearer ${token}` } })
            .then(r => (r.ok ? r.json() : null)).then(setBill).catch(() => {});
    }, [token]);
    if (!bill?.ok) return null;
    const amount = bill.zar != null
        ? `R${bill.zar.toLocaleString("en-ZA", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
        : `$${bill.usd.toFixed(2)}`;
    return (
        <span title="AWS bill so far this month (estimate)" style={{ color: "var(--gold-text)", fontWeight: 600, whiteSpace: "nowrap" }}>
            AWS {amount}
        </span>
    );
}

// The bill and the ⚡ activity feed, for the Code / Co-work / Design / Finance headers.
export function HeaderStatus({ token, onFeed, hasError }) {
    return (
        <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontSize: "12px" }}>
            <AwsCost token={token} />
            {onFeed && (
                <button onClick={onFeed} aria-label="Agent activity feed" title="Agent activity feed"
                    style={{ position: "relative", background: "none", border: "none", cursor: "pointer", padding: "4px 0", color: "var(--text-muted)", fontSize: "16px", lineHeight: 1 }}>
                    ⚡
                    {hasError && <span style={{ position: "absolute", top: "1px", right: "-2px", width: "7px", height: "7px", borderRadius: "50%", background: "#e33", border: "1.5px solid var(--bg)" }} />}
                </button>
            )}
        </span>
    );
}

export default function StatusBar({ sessionId, title, streaming, onMenu, onTitleClick, onFeed, hasError, token }) {
    return (
        <div style={{ display: "flex", flexDirection: "column", background: "var(--bg)", borderBottom: "1px solid var(--border)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "10px 12px 4px", fontSize: "12px", color: "var(--text-muted)" }}>
                <button
                    onClick={onMenu}
                    aria-label="Menu"
                    style={{ background: "none", border: "none", cursor: "pointer", padding: "6px", color: "var(--text)", fontSize: "18px", lineHeight: 1 }}
                >
                    ☰
                </button>
                <span style={{ color: "var(--text)", fontWeight: "700" }}>SEMBLANCE</span>
                <span style={{ background: "var(--surface)", borderRadius: "999px", padding: "2px 9px", fontSize: "11px" }}>v1</span>
                <span style={{ marginLeft: "auto" }}><AwsCost token={token} /></span>
                <span style={{ display: "flex", alignItems: "center", gap: "6px", color: streaming ? "var(--accent)" : "var(--ready)", fontWeight: "600", whiteSpace: "nowrap" }}>
                    <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "currentColor", display: "inline-block" }} />
                    {streaming ? "thinking" : "ready"}
                </span>
                <button
                    onClick={onFeed}
                    aria-label={hasError ? "Agent activity feed (has an error)" : "Agent activity feed"}
                    title={hasError ? "Agent activity feed — an action hit an error" : "Agent activity feed"}
                    style={{ position: "relative", background: "none", border: "none", cursor: "pointer", padding: "6px 0 6px 2px", color: "var(--text-muted)", fontSize: "16px", lineHeight: 1 }}
                >
                    ⚡
                    {hasError && (
                        <span
                            style={{
                                position: "absolute", top: "3px", right: "-1px", width: "7px", height: "7px",
                                borderRadius: "50%", background: "#e33", border: "1.5px solid var(--bg)",
                            }}
                        />
                    )}
                </button>
            </div>
            <button
                onClick={onTitleClick}
                title="Start a new chat"
                style={{
                    background: "none", border: "none", cursor: "pointer", textAlign: "left",
                    padding: "0 12px 8px 44px", margin: 0, fontSize: "12px", color: "var(--text-muted)",
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}
            >
                {title || sessionId}
            </button>
        </div>
    );
}
