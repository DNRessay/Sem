import { useState } from "react";
import { exportChatPdf } from "../utils/exportChatPdf";

const API = import.meta.env.VITE_API_URL || "";

const menuItemStyle = {
    display: "block", width: "100%", textAlign: "left", padding: "9px 12px",
    background: "none", border: "none", cursor: "pointer", fontSize: "13px", color: "var(--text)",
};

// Shared "⋮" per-session menu (rename / export PDF / delete) used by both
// Drawer's 5-item recent list and AllChatsPage's full list, so the
// behavior and API calls only exist in one place.
export default function SessionMenu({ session, token, onRenamed, onDeleted, onLogout }) {
    const [open, setOpen] = useState(false);
    const [busy, setBusy] = useState(false);
    const authHeaders = { Authorization: `Bearer ${token}` };
    const label = session.title || session.preview || session.session_id;

    const handleRename = async (e) => {
        e.stopPropagation();
        setOpen(false);
        const next = window.prompt("Rename chat", label);
        if (!next || !next.trim()) return;
        try {
            const r = await fetch(`${API}/sessions/${session.session_id}`, {
                method: "PATCH",
                headers: { ...authHeaders, "Content-Type": "application/json" },
                body: JSON.stringify({ title: next.trim() }),
            });
            if (r.status === 401) { onLogout(); return; }
            const data = await r.json();
            onRenamed(session.session_id, data.title);
        } catch {}
    };

    const handleDelete = async (e) => {
        e.stopPropagation();
        setOpen(false);
        if (!window.confirm(`Delete "${label}"? This can't be undone.`)) return;
        try {
            const r = await fetch(`${API}/sessions/${session.session_id}`, { method: "DELETE", headers: authHeaders });
            if (r.status === 401) { onLogout(); return; }
            onDeleted(session.session_id);
        } catch {}
    };

    const handleExport = async (e) => {
        e.stopPropagation();
        setOpen(false);
        setBusy(true);
        try {
            const r = await fetch(`${API}/history/${session.session_id}`, { headers: authHeaders });
            if (r.status === 401) { onLogout(); return; }
            const data = await r.json();
            await exportChatPdf(data.title || label, data.turns || []);
        } catch {} finally {
            setBusy(false);
        }
    };

    return (
        <div style={{ position: "relative" }} onClick={(e) => e.stopPropagation()}>
            <button
                onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
                aria-label="Chat options"
                disabled={busy}
                style={{ background: "none", border: "none", cursor: busy ? "default" : "pointer", color: "var(--text-muted)", fontSize: "16px", padding: "2px 6px" }}
            >
                {busy ? "…" : "⋮"}
            </button>
            {open && (
                <>
                    <div onClick={() => setOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 40 }} />
                    <div
                        style={{
                            position: "absolute", right: 0, top: "100%", marginTop: "4px",
                            background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "8px",
                            boxShadow: "0 4px 16px rgba(0,0,0,0.15)", zIndex: 41, minWidth: "140px", overflow: "hidden",
                        }}
                    >
                        <button onClick={handleRename} style={menuItemStyle}>Rename</button>
                        <button onClick={handleExport} style={menuItemStyle}>Export as PDF</button>
                        <button onClick={handleDelete} style={{ ...menuItemStyle, color: "#d33" }}>Delete</button>
                    </div>
                </>
            )}
        </div>
    );
}
