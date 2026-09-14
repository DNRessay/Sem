import { useState, useEffect } from "react";

const API = import.meta.env.VITE_API_URL || "";

export default function SkillsPanel({ token }) {
    const [skills, setSkills] = useState([]);
    const [name, setName] = useState("");
    const [triggers, setTriggers] = useState("");
    const [content, setContent] = useState("");
    const [busy, setBusy] = useState(false);

    const authHeaders = { Authorization: `Bearer ${token}` };

    const load = () => {
        fetch(`${API}/skills`, { headers: authHeaders })
            .then(r => r.json())
            .then(d => setSkills(d.skills || []))
            .catch(() => {});
    };

    useEffect(load, []);

    const addSkill = async () => {
        if (!name.trim() || !content.trim() || busy) return;
        setBusy(true);
        try {
            await fetch(`${API}/skills`, {
                method: "POST",
                headers: { "Content-Type": "application/json", ...authHeaders },
                body: JSON.stringify({ name: name.trim(), triggers, content: content.trim() }),
            });
            setName(""); setTriggers(""); setContent("");
            load();
        } finally {
            setBusy(false);
        }
    };

    const removeSkill = async (id) => {
        await fetch(`${API}/skills/${id}`, { method: "DELETE", headers: authHeaders });
        load();
    };

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
            {skills.length === 0 && (
                <div style={{ color: "var(--text-muted)", fontSize: "12px" }}>No skills yet</div>
            )}
            {skills.map(s => (
                <div key={s.id} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "6px", border: "1px solid var(--border)", borderRadius: "8px", padding: "6px 8px" }}>
                    <div style={{ minWidth: 0 }}>
                        <div style={{ fontSize: "12px", color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</div>
                        <div style={{ fontSize: "10px", color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {(s.triggers || []).join(", ")}
                        </div>
                    </div>
                    <button onClick={() => removeSkill(s.id)} aria-label={`Delete ${s.name}`} style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: "13px", flexShrink: 0 }}>✕</button>
                </div>
            ))}

            <input value={name} onChange={e => setName(e.target.value)} placeholder="Skill name"
                style={fieldStyle} />
            <input value={triggers} onChange={e => setTriggers(e.target.value)} placeholder="trigger words, comma separated"
                style={fieldStyle} />
            <textarea value={content} onChange={e => setContent(e.target.value)} placeholder="Instructions to inject when triggered"
                rows={3} style={{ ...fieldStyle, resize: "vertical", fontFamily: "inherit" }} />
            <button onClick={addSkill} disabled={busy} style={{ padding: "8px", borderRadius: "8px", border: "none", background: "var(--accent)", color: "var(--accent-contrast)", fontSize: "13px", fontWeight: "600", cursor: "pointer" }}>
                {busy ? "Saving…" : "Add skill"}
            </button>
        </div>
    );
}

const fieldStyle = {
    width: "100%", boxSizing: "border-box", background: "var(--bg)", border: "1px solid var(--border)",
    borderRadius: "8px", padding: "8px 10px", color: "var(--text)", fontSize: "13px", outline: "none",
};
