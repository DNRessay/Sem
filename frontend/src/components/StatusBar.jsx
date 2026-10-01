import { useEffect, useState } from "react";
import { ActivityIcon, MenuIcon, ReceiptIcon } from "./Icons";

const API = import.meta.env.VITE_API_URL || "";

export const iconBtn = {
    position: "relative", background: "none", border: "none", cursor: "pointer", padding: "6px",
    color: "var(--text-muted)", display: "inline-flex", alignItems: "center", justifyContent: "center", borderRadius: "8px",
};

function rand(bill) {
    return bill.zar != null
        ? `R${bill.zar.toLocaleString("en-ZA", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
        : `$${bill.usd.toFixed(2)}`;
}

// This month's AWS bill: a receipt icon; tap for the amount (free CloudWatch estimate, refreshed every 6 hours).
export function CostButton({ token }) {
    const [bill, setBill] = useState(null);
    const [open, setOpen] = useState(false);
    useEffect(() => {
        if (!token) return;
        fetch(`${API}/settings/aws-cost`, { headers: { Authorization: `Bearer ${token}` } })
            .then(r => (r.ok ? r.json() : null)).then(setBill).catch(() => {});
    }, [token]);
    if (!bill) return null;
    return (
        <span style={{ position: "relative" }}>
            <button onClick={() => setOpen(o => !o)} aria-label="AWS bill this month" title="AWS bill this month" style={iconBtn}>
                <ReceiptIcon size={18} />
            </button>
            {open && (
                <>
                    <div onClick={() => setOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 30 }} />
                    <div style={{ position: "absolute", right: 0, top: "100%", zIndex: 31, minWidth: "200px", background: "var(--surface)",
                                  border: "1px solid var(--border)", borderRadius: "12px", padding: "10px 12px", boxShadow: "0 8px 24px rgba(0,0,0,0.18)" }}>
                        <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>AWS this month (estimate)</div>
                        {bill.ok
                            ? <div style={{ fontSize: "20px", fontWeight: 700, color: "var(--gold-text)" }}>{rand(bill)}</div>
                            : <div style={{ fontSize: "12px", color: "var(--text)" }}>{bill.error}</div>}
                        {bill.ok && bill.zar != null && <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>${bill.usd.toFixed(2)} at R{bill.rate.toFixed(2)}/$</div>}
                    </div>
                </>
            )}
        </span>
    );
}

// The activity feed button: gold while Sem is working, red dot after an error.
export function ActivityButton({ onFeed, hasError, busy }) {
    if (!onFeed) return null;
    return (
        <button onClick={onFeed} aria-label={hasError ? "Activity (has an error)" : "Activity"} title="Activity"
            style={{ ...iconBtn, color: busy ? "var(--gold)" : "var(--text-muted)" }}>
            <ActivityIcon size={18} />
            {hasError && <span style={{ position: "absolute", top: "4px", right: "4px", width: "7px", height: "7px", borderRadius: "50%", background: "var(--danger)", border: "1.5px solid var(--bg)" }} />}
        </button>
    );
}

// Right side of every tab's header: bill + activity.
export function HeaderStatus({ token, onFeed, hasError, busy }) {
    return (
        <span style={{ display: "inline-flex", alignItems: "center" }}>
            <CostButton token={token} />
            <ActivityButton onFeed={onFeed} hasError={hasError} busy={busy} />
        </span>
    );
}

export default function StatusBar({ sessionId, title, streaming, onMenu, onTitleClick, onFeed, hasError, token }) {
    return (
        <div style={{ display: "flex", flexDirection: "column", background: "var(--bg)", borderBottom: "1px solid var(--border)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "8px 8px 2px" }}>
                <button onClick={onMenu} aria-label="Menu" style={{ ...iconBtn, color: "var(--text)" }}><MenuIcon size={20} /></button>
                <span style={{ color: "var(--text)", fontWeight: "700", fontSize: "15px" }}>SEMBLANCE</span>
                <span style={{ flex: 1 }} />
                <HeaderStatus token={token} onFeed={onFeed} hasError={hasError} busy={streaming} />
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
