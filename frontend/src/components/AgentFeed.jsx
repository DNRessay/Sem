import { useState, useEffect } from "react";

const API = import.meta.env.VITE_API_URL || "";

const COLORS = {
    kairos: "#f97316", general: "#06b6d4", plan: "#ffd700",
    explore: "#10b981", dream: "#e879f9", swarm: "#a78bfa",
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
        <div style={{ background: "#050a0f", borderLeft: "1px solid #1e293b", width: "220px", overflowY: "auto", padding: "12px", fontFamily: "monospace", fontSize: "11px" }}>
            <div style={{ color: "#334155", letterSpacing: "2px", marginBottom: "10px" }}>AGENT FEED</div>
            {events.length === 0 ? (
                <div style={{ color: "#1e293b" }}>No activity yet</div>
            ) : events.map((e, i) => (
                <div key={i} style={{ color: COLORS[e.agent] || "#475569", marginBottom: "6px", lineHeight: "1.4" }}>
                    <span style={{ opacity: 0.5 }}>{new Date(e.ts * 1000).toLocaleTimeString()} </span>
                    <span style={{ fontWeight: "700" }}>{e.agent}</span>
                    <div style={{ opacity: 0.7, paddingLeft: "8px" }}>{e.action}</div>
                </div>
            ))}
        </div>
    );
}