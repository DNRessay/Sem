import { useState, useEffect } from "react";

const API = import.meta.env.VITE_API_URL || "";

export default function SkillsPanel({ token }) {
    const [skills, setSkills] = useState([]);

    const authHeaders = { Authorization: `Bearer ${token}` };

    const load = () => {
        fetch(`${API}/skills`, { headers: authHeaders })
            .then(r => r.json())
            .then(d => setSkills(d.skills || []))
            .catch(() => {});
    };

    useEffect(load, []);

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
                        <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                            <span style={{ fontSize: "12px", color: "var(--text)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{s.name}</span>
                            {s.source === "repo" && (
                                <span style={{ fontSize: "9px", color: "var(--text-muted)", border: "1px solid var(--border)", borderRadius: "999px", padding: "0 5px", flexShrink: 0 }}>from repo</span>
                            )}
                        </div>
                        {s.description && (
                            <div style={{ fontSize: "10px", color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {s.description}
                            </div>
                        )}
                        <div style={{ fontSize: "10px", color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            triggers: {(s.triggers || []).join(", ") || "(none)"}
                        </div>
                    </div>
                    {s.source === "repo" ? (
                        <span title="Edit skills/*.md in the repo and redeploy to change this — editing or deleting it here won't stick"
                            style={{ fontSize: "10px", color: "var(--text-muted)", flexShrink: 0 }}>
                            🔒
                        </span>
                    ) : (
                        <button onClick={() => removeSkill(s.id)} aria-label={`Delete ${s.name}`} style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: "13px", flexShrink: 0 }}>✕</button>
                    )}
                </div>
            ))}

            <div style={{ fontSize: "11px", color: "var(--text-muted)", lineHeight: "1.4" }}>
                New skills are added via <code>skills/*.md</code> in the repo — see <code>skills/README.md</code> for the format.
            </div>
        </div>
    );
}
