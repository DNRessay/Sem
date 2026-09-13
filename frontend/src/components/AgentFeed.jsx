import { useState, useEffect } from "react";

const API = import.meta.env.VITE_API_URL || "";

const COLORS = {
    kairos: "#181818", general: "#8e8e8c", plan: "#b8860b",
    explore: "#3a9b5c", dream: "#a855c9", swarm: "#5b5bc9",
};

export default function AgentFeed({ sessionId = "default" }) {
    const [events, setEvents] = useState([]);

    useEffect(() => {
        const interval = setInterval(async () => {
            try {
                const r = await fetch(`${API}/status/${sessionId}`);
                const data = await r.json();
                if (data.event) setEvents(e => [data.event, ...e].slice(0, 50));
            } catch {}
        }, 3000);
        return () => clearInterval(interval);
    }, [sessionId]);

    return (
        <div style={{ background: "var(--bg)", borderLeft: "1px solid var(--border)", width: "220px", overflowY: "auto", padding: "12px", fontSize: "11px" }}>
            <div style={{ color: "var(--text-muted)", letterSpacing: "1px", marginBottom: "10px", fontWeight: "600" }}>AGENT FEED</div>
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
