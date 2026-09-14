import { useState, useEffect } from "react";

const API = import.meta.env.VITE_API_URL || "";

const COLORS = {
    kairos: "#181818", general: "#8e8e8c", plan: "#b8860b",
    explore: "#3a9b5c", dream: "#a855c9", swarm: "#5b5bc9",
};

export default function AgentFeed({ sessionId = "default", token }) {
    const [events, setEvents] = useState([]);

    useEffect(() => {
        const interval = setInterval(async () => {
            try {
                const r = await fetch(`${API}/status/${sessionId}`, {
                    headers: token ? { Authorization: `Bearer ${token}` } : {},
                });
                const data = await r.json();
                // /status returns only the single most recent event, not a
                // list of new-since-last-poll — polling every 3s means most
                // polls see the same event as last time. Without this check
                // it got appended again on every single poll, flooding the
                // feed with duplicates of one real event.
                if (data.event) {
                    setEvents(e => {
                        const latest = e[0];
                        const isSame = latest && latest.ts === data.event.ts
                            && latest.agent === data.event.agent && latest.action === data.event.action;
                        return isSame ? e : [data.event, ...e].slice(0, 50);
                    });
                }
            } catch {}
        }, 3000);
        return () => clearInterval(interval);
    }, [sessionId, token]);

    return (
        <div style={{ fontSize: "11px" }}>
            {events.length === 0 ? (
                <div style={{ color: "var(--border)" }}>No activity yet</div>
            ) : events.map((e, i) => (
                <div key={i} style={{ color: COLORS[e.agent] || "var(--text-muted)", marginBottom: "6px", lineHeight: "1.4" }}>
                    <span style={{ opacity: 0.5 }}>{new Date(e.ts * 1000).toLocaleTimeString()} </span>
                    <span style={{ fontWeight: "700" }}>{e.agent}</span>
                    <div style={{ opacity: 0.7, paddingLeft: "8px" }}>{e.action}</div>
                </div>
            ))}
        </div>
    );
}
