import { useState } from "react";

function Mark({ status }) {
    if (status === "completed") return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--ready, #3fb950)" strokeWidth="3" strokeLinecap="round" aria-label="done">
            <path d="M5 12l5 5L20 7" />
        </svg>
    );
    if (status === "in_progress") return (
        <span aria-label="in progress" style={{ width: "12px", height: "12px", borderRadius: "50%", border: "2px solid var(--accent)",
            borderTopColor: "transparent", display: "inline-block", animation: "sem-spin 0.9s linear infinite" }} />
    );
    return <span aria-label="to do" style={{ width: "12px", height: "12px", borderRadius: "50%", border: "2px solid var(--border)", display: "inline-block" }} />;
}

// The agent's task list for this chat (it keeps it current with its update_plan tool). Sits above the composer.
export default function PlanPanel({ plan, busy, onClear }) {
    const [open, setOpen] = useState(true);
    if (!plan?.length) return null;
    const done = plan.filter(t => t.status === "completed").length;
    const current = plan.find(t => t.status === "in_progress");
    return (
        <div style={{ border: "1px solid var(--border)", borderRadius: "14px", background: "var(--surface)", margin: "0 0 8px", overflow: "hidden" }}>
            <style>{"@keyframes sem-spin { to { transform: rotate(360deg); } }"}</style>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "8px 12px" }}>
                <button onClick={() => setOpen(o => !o)} aria-expanded={open}
                    style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: "8px", background: "none", border: "none",
                             padding: 0, cursor: "pointer", color: "var(--text)", textAlign: "left" }}>
                    <span style={{ fontSize: "12px", fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase", color: "var(--text-muted)" }}>Plan</span>
                    <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>{done}/{plan.length}</span>
                    {!open && current && <span style={{ fontSize: "13px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>· {current.title}</span>}
                    <span style={{ marginLeft: "auto", color: "var(--text-muted)", fontSize: "12px" }}>{open ? "▾" : "▸"}</span>
                </button>
                {!busy && onClear && (
                    <button onClick={onClear} title="Clear the plan" aria-label="Clear the plan"
                        style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: "16px", padding: "0 2px" }}>×</button>
                )}
            </div>
            {open && (
                <ol style={{ listStyle: "none", margin: 0, padding: "0 12px 10px", display: "flex", flexDirection: "column", gap: "6px", maxHeight: "30vh", overflowY: "auto" }}>
                    {plan.map((t, i) => (
                        <li key={i} style={{ display: "flex", alignItems: "flex-start", gap: "8px", fontSize: "13px", lineHeight: 1.4 }}>
                            <span style={{ flexShrink: 0, marginTop: "2px", display: "inline-flex" }}><Mark status={t.status} /></span>
                            <span style={{ color: t.status === "completed" ? "var(--text-muted)" : "var(--text)",
                                           textDecoration: t.status === "completed" ? "line-through" : "none",
                                           fontWeight: t.status === "in_progress" ? 600 : 400 }}>{t.title}</span>
                        </li>
                    ))}
                </ol>
            )}
        </div>
    );
}
