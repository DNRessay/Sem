export default function StatusBar({ sessionId, streaming }) {
    return (
        <div style={{ display: "flex", alignItems: "center", gap: "12px", padding: "10px 16px", background: "var(--bg)", borderBottom: "1px solid var(--border)", fontSize: "12px", color: "var(--text-muted)" }}>
            <span style={{ color: "var(--accent)", fontWeight: "600" }}>SEMBLANCE</span>
            <span>v9</span>
            <span>·</span>
            <span>session: {sessionId}</span>
            <span>·</span>
            <span style={{ color: streaming ? "var(--accent)" : "#5fb37a" }}>
                {streaming ? "● thinking" : "● ready"}
            </span>
        </div>
    );
}
