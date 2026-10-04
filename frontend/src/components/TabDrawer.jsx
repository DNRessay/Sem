import { CloseIcon, GearIcon, MenuIcon, TAB_ICONS } from "./Icons";

// The side menu for Code, Co-work, Design and Finance: same shape as the main
// chat's Drawer, titled for the tab, with that tab's own chat history.
const TABS = [
    { view: "chat", label: "Chat" },
    { view: "code", label: "Code" },
    { view: "cowork", label: "Co-work" },
    { view: "design", label: "Design" },
    { view: "finance", label: "Finance" },
    { view: "bots", label: "Bots" },
];

const navBtn = {
    width: "100%", textAlign: "left", padding: "10px 14px", marginTop: "8px", borderRadius: "10px",
    border: "1px solid var(--border)", background: "var(--surface)", color: "var(--text)",
    fontSize: "14px", fontWeight: "600", cursor: "pointer",
};

function timeAgo(ms) {
    const diff = (Date.now() - ms) / 1000;
    if (diff < 60) return "just now";
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
}

const TAB_NAMES = { chat: "Chat", code: "Code", cowork: "Co-work", design: "Design", finance: "Finance", bots: "Bots" };

// "Continue in another tab" button, shown when an agent hands work off.
export function HandoffCard({ tab, task, onHandoff }) {
    if (!onHandoff || !TAB_NAMES[tab]) return null;
    return (
        <div style={{ margin: "8px 0", padding: "10px 12px", border: "1px solid var(--border)", borderRadius: "12px", background: "var(--surface)" }}>
            <div style={{ fontSize: "12px", color: "var(--text-muted)", marginBottom: "6px", whiteSpace: "pre-wrap", maxHeight: "6em", overflow: "hidden" }}>{task}</div>
            <button className="btn-primary" onClick={() => onHandoff(tab, task)} style={{
                padding: "7px 12px", borderRadius: "10px", border: "none", background: "var(--accent)",
                color: "var(--accent-contrast)", fontSize: "13px", fontWeight: 600, cursor: "pointer",
            }}>Open in {TAB_NAMES[tab]} →</button>
        </div>
    );
}

export function MenuButton({ onClick }) {
    return (
        <button onClick={onClick} aria-label="Menu" style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text)", padding: "6px", display: "inline-flex" }}><MenuIcon size={20} /></button>
    );
}

export default function TabDrawer({ open, onClose, title, current, onNavigate, onNew, newLabel = "+ New chat",
                                    chats, activeId, onSelect, onDelete, subtitle, disabled }) {
    const go = view => { onClose(); onNavigate(view); };
    return (
        <>
            <div onClick={onClose} style={{
                position: "fixed", inset: 0, background: "rgba(0,0,0,0.25)", opacity: open ? 1 : 0,
                pointerEvents: open ? "auto" : "none", transition: "opacity 0.2s ease", zIndex: 40,
            }} />
            <div style={{
                position: "fixed", top: 0, left: 0, bottom: 0, width: "82%", maxWidth: "320px", background: "var(--bg)",
                borderRight: "1px solid var(--border)", transform: open ? "translateX(0)" : "translateX(-100%)",
                transition: "transform 0.2s ease", zIndex: 41, display: "flex", flexDirection: "column",
            }}>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                    <span style={{ fontWeight: "700", color: "var(--text)" }}>{title}</span>
                    <button onClick={onClose} aria-label="Close menu" style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", display: "inline-flex", padding: "4px" }}><CloseIcon size={18} /></button>
                </div>

                <div style={{ padding: "4px 16px 12px" }}>
                    <button onClick={() => { onNew(); onClose(); }} disabled={disabled} style={navBtn}>{newLabel}</button>
                    {TABS.filter(t => t.view !== current).map(t => (
                        <button key={t.view} onClick={() => go(t.view)} style={{ ...navBtn, display: "flex", alignItems: "center", gap: "10px" }}>
                            {(() => { const Icon = TAB_ICONS[t.view]; return <Icon size={16} />; })()} {t.label}
                        </button>
                    ))}
                </div>

                <div style={{ flex: 1, overflowY: "auto", padding: "0 16px" }}>
                    <div style={{ color: "var(--text-muted)", fontSize: "11px", fontWeight: "600", letterSpacing: "1px", margin: "8px 0" }}>HISTORY</div>
                    {[...chats].sort((a, b) => b.updated - a.updated).map(c => (
                        <div key={c.id} onClick={() => { onSelect(c.id); onClose(); }} style={{
                            display: "flex", alignItems: "center", gap: "6px", cursor: "pointer", borderRadius: "8px",
                            padding: "8px", marginBottom: "2px", background: c.id === activeId ? "var(--surface)" : "none",
                            boxShadow: c.id === activeId ? "inset 3px 0 0 var(--gold)" : "none",
                        }}>
                            <div style={{ minWidth: 0, flex: 1 }}>
                                <div style={{ color: "var(--text)", fontSize: "13px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                    {c.title || "New chat"}
                                </div>
                                <div style={{ color: "var(--text-muted)", fontSize: "11px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                    {[subtitle?.(c), timeAgo(c.updated)].filter(Boolean).join(" · ")}
                                </div>
                            </div>
                            <button
                                onClick={e => { e.stopPropagation(); if (window.confirm(`Delete "${c.title || "New chat"}"?`)) onDelete(c.id); }}
                                disabled={disabled && c.id === activeId} aria-label="Delete chat"
                                style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", fontSize: "14px", padding: "4px" }}
                            ><CloseIcon size={14} /></button>
                        </div>
                    ))}
                </div>

                <button onClick={() => go("settings")} style={{
                    padding: "12px 16px", background: "none", border: "none", borderTop: "1px solid var(--border)",
                    width: "100%", cursor: "pointer", textAlign: "left", fontSize: "13px", color: "var(--text)",
                display: "flex", alignItems: "center", gap: "10px" }}><GearIcon size={16} /> Settings &amp; MCP</button>
            </div>
        </>
    );
}
