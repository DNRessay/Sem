import { useState, useEffect } from "react";
import AgentFeed from "./AgentFeed";
import ConnectorsPanel from "./ConnectorsPanel";
import SkillsPanel from "./SkillsPanel";

const API = import.meta.env.VITE_API_URL || "";

function timeAgo(unixSeconds) {
    const diff = Date.now() / 1000 - unixSeconds;
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

export default function Drawer({ open, onClose, currentSessionId, onNewChat, onOpenSession, token, onLogout }) {
    const [sessions, setSessions] = useState([]);
    const [loading, setLoading] = useState(false);
    const [showFeed, setShowFeed] = useState(false);
    const [showConnectors, setShowConnectors] = useState(false);
    const [showSkills, setShowSkills] = useState(false);

    const authHeaders = { Authorization: `Bearer ${token}` };

    useEffect(() => {
        if (!open) return;
        setLoading(true);
        fetch(`${API}/sessions`, { headers: authHeaders })
            .then(r => {
                if (r.status === 401) { onLogout(); return { sessions: [] }; }
                return r.json();
            })
            .then(data => setSessions(data.sessions || []))
            .catch(() => setSessions([]))
            .finally(() => setLoading(false));
    }, [open]);

    const openSession = async (id) => {
        try {
            const r = await fetch(`${API}/history/${id}`, { headers: authHeaders });
            if (r.status === 401) { onLogout(); return; }
            const data = await r.json();
            onOpenSession(id, data.turns || [], data.title);
        } catch {
            onOpenSession(id, [], "");
        }
    };

    return (
        <>
            <div
                onClick={onClose}
                style={{
                    position: "fixed", inset: 0, background: "rgba(0,0,0,0.25)",
                    opacity: open ? 1 : 0, pointerEvents: open ? "auto" : "none",
                    transition: "opacity 0.2s ease", zIndex: 20,
                }}
            />
            <div
                style={{
                    position: "fixed", top: 0, left: 0, bottom: 0, width: "82%", maxWidth: "320px",
                    background: "var(--bg)", borderRight: "1px solid var(--border)",
                    transform: open ? "translateX(0)" : "translateX(-100%)",
                    transition: "transform 0.2s ease", zIndex: 21,
                    display: "flex", flexDirection: "column",
                }}
            >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                    <span style={{ fontWeight: "700", color: "var(--text)" }}>SEMBLANCE</span>
                    <button onClick={onClose} aria-label="Close menu" style={{ background: "none", border: "none", cursor: "pointer", fontSize: "18px", color: "var(--text-muted)" }}>✕</button>
                </div>

                <div style={{ padding: "12px 16px" }}>
                    <button
                        onClick={onNewChat}
                        style={{ width: "100%", textAlign: "left", padding: "10px 14px", borderRadius: "10px", border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)", fontSize: "14px", fontWeight: "600", cursor: "pointer" }}
                    >
                        + New chat
                    </button>
                </div>

                <div style={{ flex: 1, overflowY: "auto", padding: "0 16px" }}>
                    <div style={{ color: "var(--text-muted)", fontSize: "11px", fontWeight: "600", letterSpacing: "1px", margin: "8px 0" }}>HISTORY</div>
                    {loading && <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>Loading…</div>}
                    {!loading && sessions.length === 0 && (
                        <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>No past chats yet</div>
                    )}
                    {sessions.map(s => (
                        <button
                            key={s.session_id}
                            onClick={() => openSession(s.session_id)}
                            style={{
                                display: "block", width: "100%", textAlign: "left", background: s.session_id === currentSessionId ? "var(--surface)" : "none",
                                border: "none", borderRadius: "8px", padding: "8px 8px", marginBottom: "2px", cursor: "pointer",
                            }}
                        >
                            <div style={{ color: "var(--text)", fontSize: "13px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {s.title || s.preview || s.session_id}
                            </div>
                            <div style={{ color: "var(--text-muted)", fontSize: "11px" }}>{timeAgo(s.last_at)}</div>
                        </button>
                    ))}

                    <button
                        onClick={() => setShowFeed(v => !v)}
                        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", background: "none", border: "none", color: "var(--text-muted)", fontSize: "11px", fontWeight: "600", letterSpacing: "1px", margin: "16px 0 8px", padding: 0, cursor: "pointer" }}
                    >
                        AGENT FEED <span>{showFeed ? "▾" : "▸"}</span>
                    </button>
                    {showFeed && <AgentFeed sessionId={currentSessionId} token={token} />}

                    <button
                        onClick={() => setShowConnectors(v => !v)}
                        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", background: "none", border: "none", color: "var(--text-muted)", fontSize: "11px", fontWeight: "600", letterSpacing: "1px", margin: "16px 0 8px", padding: 0, cursor: "pointer" }}
                    >
                        CONNECTORS <span>{showConnectors ? "▾" : "▸"}</span>
                    </button>
                    {showConnectors && <ConnectorsPanel token={token} />}

                    <button
                        onClick={() => setShowSkills(v => !v)}
                        style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%", background: "none", border: "none", color: "var(--text-muted)", fontSize: "11px", fontWeight: "600", letterSpacing: "1px", margin: "16px 0 8px", padding: 0, cursor: "pointer" }}
                    >
                        SKILLS <span>{showSkills ? "▾" : "▸"}</span>
                    </button>
                    {showSkills && <SkillsPanel token={token} />}
                </div>

                <button
                    onClick={onLogout}
                    style={{ borderTop: "1px solid var(--border)", padding: "12px 16px", display: "flex", alignItems: "center", gap: "10px", background: "none", border: "none", borderTopWidth: "1px", borderTopStyle: "solid", borderTopColor: "var(--border)", width: "100%", cursor: "pointer", textAlign: "left" }}
                >
                    <div style={{ width: "28px", height: "28px", borderRadius: "50%", background: "var(--surface-2)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "13px", color: "var(--text-muted)" }}>
                        👤
                    </div>
                    <div style={{ fontSize: "13px", color: "var(--text)" }}>Log out</div>
                </button>
            </div>
        </>
    );
}
