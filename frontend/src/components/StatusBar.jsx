export default function StatusBar({ sessionId, streaming }) {
    return (
        <div style={{ display: "flex", alignItems: "center", gap: "12px", padding: "6px 16px", background: "#080f1a", borderBottom: "1px solid #1e293b", fontFamily: "monospace", fontSize: "10px", color: "#334155" }}>
            <span style={{ color: "#00f5ff", fontWeight: "700", letterSpacing: "3px" }}>SEMBLANCE</span>
            <span>v9</span>
            <span>·</span>
            <span>session: {sessionId}</span>
            <span>·</span>
            <span style={{ color: streaming ? "#f97316" : "#10b981" }}>
                {streaming ? "● streaming" : "● ready"}
            </span>
        </div>
    );
}