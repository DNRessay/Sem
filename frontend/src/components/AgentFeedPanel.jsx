import AgentFeed from "./AgentFeed";

// Deliberately separate from the main history Drawer: a lighter-weight
// overlay (lower backdrop opacity, half the viewport height, anchored to
// the top-right) rather than a full-height side menu — this is a live
// activity readout you glance at, not a navigation surface, so it
// shouldn't compete with or block the chat underneath it.
export default function AgentFeedPanel({ open, onClose, sessionId, token }) {
    return (
        <>
            <div
                onClick={onClose}
                style={{
                    position: "fixed", inset: 0, background: "rgba(0,0,0,0.08)",
                    opacity: open ? 1 : 0, pointerEvents: open ? "auto" : "none",
                    transition: "opacity 0.2s ease", zIndex: 30,
                }}
            />
            <div
                style={{
                    position: "fixed", top: 0, right: 0, width: "82%", maxWidth: "320px", height: "50vh",
                    background: "var(--bg)", borderLeft: "1px solid var(--border)", borderBottom: "1px solid var(--border)",
                    borderBottomLeftRadius: "14px", boxShadow: "-4px 4px 20px rgba(0,0,0,0.15)",
                    transform: open ? "translateX(0)" : "translateX(100%)",
                    transition: "transform 0.2s ease", zIndex: 31,
                    display: "flex", flexDirection: "column", overflow: "hidden",
                }}
            >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 14px", borderBottom: "1px solid var(--border)" }}>
                    <span style={{ fontWeight: "700", fontSize: "13px", color: "var(--text)" }}>Agent Feed</span>
                    <button onClick={onClose} aria-label="Close agent feed" style={{ background: "none", border: "none", cursor: "pointer", fontSize: "16px", color: "var(--text-muted)" }}>✕</button>
                </div>
                <div style={{ flex: 1, overflowY: "auto", padding: "10px 14px" }}>
                    <AgentFeed sessionId={sessionId} token={token} />
                </div>
            </div>
        </>
    );
}
