import { useEffect, useState } from "react";
import SessionMenu from "./SessionMenu";

const API = import.meta.env.VITE_API_URL || "";

function timeAgo(unixSeconds) {
    const diff = Date.now() / 1000 - unixSeconds;
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

// Full-screen view, not a new drawer — reached from Drawer's "View all
// chats" once the sidebar's own list is capped to 5 recent ones.
export default function AllChatsPage({ token, currentSessionId, onOpenSession, onBack, onLogout, onSessionRenamed, onSessionDeleted }) {
    const [sessions, setSessions] = useState([]);
    const [loading, setLoading] = useState(true);
    const authHeaders = { Authorization: `Bearer ${token}` };

    useEffect(() => {
        setLoading(true);
        fetch(`${API}/sessions`, { headers: authHeaders })
            .then((r) => {
                if (r.status === 401) { onLogout(); return { sessions: [] }; }
                return r.json();
            })
            .then((data) => setSessions(data.sessions || []))
            .catch(() => setSessions([]))
            .finally(() => setLoading(false));
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

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

    const handleRenamed = (id, title) => {
        setSessions((s) => s.map((x) => (x.session_id === id ? { ...x, title } : x)));
        onSessionRenamed(id, title);
    };

    const handleDeleted = (id) => {
        setSessions((s) => s.filter((x) => x.session_id !== id));
        onSessionDeleted(id);
    };

    return (
        <div style={{ position: "fixed", inset: 0, background: "var(--bg)", zIndex: 25, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                <button onClick={onBack} aria-label="Back" style={{ background: "none", border: "none", cursor: "pointer", fontSize: "18px", color: "var(--text)" }}>←</button>
                <span style={{ fontWeight: "700", color: "var(--text)" }}>All chats</span>
            </div>
            <div style={{ flex: 1, overflowY: "auto", padding: "8px 16px" }}>
                {loading && <div style={{ color: "var(--text-muted)", fontSize: "13px", padding: "8px 0" }}>Loading…</div>}
                {!loading && sessions.length === 0 && (
                    <div style={{ color: "var(--text-muted)", fontSize: "13px", padding: "8px 0" }}>No past chats yet</div>
                )}
                {sessions.map((s) => (
                    <div
                        key={s.session_id}
                        onClick={() => openSession(s.session_id)}
                        style={{
                            display: "flex", alignItems: "center", justifyContent: "space-between",
                            background: s.session_id === currentSessionId ? "var(--surface)" : "none",
                            borderRadius: "8px", padding: "10px 8px", marginBottom: "2px", cursor: "pointer",
                        }}
                    >
                        <div style={{ minWidth: 0, flex: 1 }}>
                            <div style={{ color: "var(--text)", fontSize: "14px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {s.title || s.preview || s.session_id}
                            </div>
                            <div style={{ color: "var(--text-muted)", fontSize: "11px" }}>{timeAgo(s.last_at)}</div>
                        </div>
                        <SessionMenu session={s} token={token} onRenamed={handleRenamed} onDeleted={handleDeleted} onLogout={onLogout} />
                    </div>
                ))}
            </div>
        </div>
    );
}
