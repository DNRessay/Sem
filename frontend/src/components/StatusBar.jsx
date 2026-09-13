export default function StatusBar({ sessionId, streaming }) {
    return (
        <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "12px 16px", background: "var(--bg)", borderBottom: "1px solid var(--border)", fontSize: "12px", color: "var(--text-muted)" }}>
            <span style={{ color: "var(--text)", fontWeight: "700" }}>SEMBLANCE</span>
            <span style={{ background: "var(--surface)", borderRadius: "999px", padding: "2px 9px", fontSize: "11px" }}>v9</span>
            <span>·</span>
            <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>session: {sessionId}</span>
            <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "6px", color: streaming ? "var(--accent)" : "var(--ready)", fontWeight: "600", whiteSpace: "nowrap" }}>
                <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "currentColor", display: "inline-block" }} />
                {streaming ? "thinking" : "ready"}
            </span>
        </div>
    );
}
