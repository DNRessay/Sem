export default function StatusBar({ sessionId, title, streaming, onMenu, onTitleClick }) {
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
                <span style={{ background: "var(--surface)", borderRadius: "999px", padding: "2px 9px", fontSize: "11px" }}>v9</span>
                <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "6px", color: streaming ? "var(--accent)" : "var(--ready)", fontWeight: "600", whiteSpace: "nowrap" }}>
                    <span style={{ width: "6px", height: "6px", borderRadius: "50%", background: "currentColor", display: "inline-block" }} />
                    {streaming ? "thinking" : "ready"}
                </span>
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
