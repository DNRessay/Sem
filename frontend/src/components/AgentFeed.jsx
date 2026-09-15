const COLORS = {
    kairos: "#181818", general: "#8e8e8c", plan: "#b8860b",
    explore: "#3a9b5c", dream: "#a855c9", swarm: "#5b5bc9",
};

// Purely presentational — polling lives in hooks/useAgentFeed so StatusBar's
// error dot and this list share one poller instead of two.
export default function AgentFeed({ events }) {
    return (
        <div style={{ fontSize: "11px" }}>
            {events.length === 0 ? (
                <div style={{ color: "var(--border)" }}>No activity yet</div>
            ) : events.map((e, i) => {
                const action = e.action || "";
                const blocked = action.startsWith("blocked:");
                // The ok:/blocked: prefix is just for filtering server-side —
                // color + the error badge already say which one this is, so
                // strip it from what's actually shown.
                const detail = action.replace(/^(ok|blocked):/, "");
                return (
                    <div key={e.id ?? i} style={{ color: blocked ? "#c0392b" : (COLORS[e.agent] || "var(--text-muted)"), marginBottom: "6px", lineHeight: "1.4" }}>
                        <span style={{ opacity: 0.5 }}>{new Date(e.ts * 1000).toLocaleTimeString()} </span>
                        <span style={{ fontWeight: "700" }}>{e.agent}</span>
                        {blocked && <span style={{ marginLeft: "6px", fontSize: "10px", fontWeight: "700" }}>⚠ error</span>}
                        <div style={{ opacity: 0.7, paddingLeft: "8px" }}>{detail}</div>
                    </div>
                );
            })}
        </div>
    );
}
