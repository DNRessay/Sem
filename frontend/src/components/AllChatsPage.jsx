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

const DATE_FILTERS = {
    all: { label: "All time", seconds: null },
    today: { label: "Today", seconds: 86400 },
    week: { label: "Last 7 days", seconds: 7 * 86400 },
    month: { label: "Last 30 days", seconds: 30 * 86400 },
};

function matchesDateFilter(session, filterKey) {
    const window = DATE_FILTERS[filterKey].seconds;
    if (window === null) return true;
    return Date.now() / 1000 - session.last_at <= window;
}

// Full-screen view, not a new drawer — reached from Drawer's "View all
// chats" once the sidebar's own list is capped to 5 recent ones.
export default function AllChatsPage({ token, currentSessionId, onOpenSession, onBack, onLogout, onSessionRenamed, onSessionDeleted }) {
    const [sessions, setSessions] = useState([]);
    const [loading, setLoading] = useState(true);
    const [search, setSearch] = useState("");
    const [dateFilter, setDateFilter] = useState("all");
    const authHeaders = { Authorization: `Bearer ${token}` };

    const query = search.trim().toLowerCase();
    const filteredSessions = sessions.filter((s) => {
        if (!matchesDateFilter(s, dateFilter)) return false;
        if (!query) return true;
        const haystack = `${s.title || ""} ${s.preview || ""}`.toLowerCase();
        return haystack.includes(query);
    });

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
            <div style={{ padding: "12px 16px 8px", display: "flex", gap: "8px" }}>
                <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    placeholder="Search chats…"
                    style={{
                        flex: 1, minWidth: 0, padding: "9px 12px", borderRadius: "10px", border: "1px solid var(--border)",
                        background: "var(--surface)", color: "var(--text)", fontSize: "13px",
                    }}
                />
                <select
                    value={dateFilter}
                    onChange={(e) => setDateFilter(e.target.value)}
                    style={{
                        padding: "9px 8px", borderRadius: "10px", border: "1px solid var(--border)",
                        background: "var(--surface)", color: "var(--text)", fontSize: "13px",
                    }}
                >
                    {Object.entries(DATE_FILTERS).map(([key, { label }]) => (
                        <option key={key} value={key}>{label}</option>
                    ))}
                </select>
            </div>
            <div style={{ flex: 1, overflowY: "auto", padding: "0 16px 8px" }}>
                {loading && <div style={{ color: "var(--text-muted)", fontSize: "13px", padding: "8px 0" }}>Loading…</div>}
                {!loading && sessions.length === 0 && (
                    <div style={{ color: "var(--text-muted)", fontSize: "13px", padding: "8px 0" }}>No past chats yet</div>
                )}
                {!loading && sessions.length > 0 && filteredSessions.length === 0 && (
                    <div style={{ color: "var(--text-muted)", fontSize: "13px", padding: "8px 0" }}>No chats match your search/filter</div>
                )}
                {filteredSessions.map((s) => (
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
