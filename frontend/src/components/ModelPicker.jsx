import { useEffect, useState } from "react";

const API = import.meta.env.VITE_API_URL || "";
const HF_CUSTOM = "__hf_custom__";

export function loadModel(key) {
    try { return localStorage.getItem(key) || "auto"; } catch { return "auto"; }
}

// Free models first ("Auto" walks them on rate limits), then paid ones.
// Hugging Face accepts any model it hosts, typed as owner/model.
export default function ModelPicker({ token, value, onChange, storageKey }) {
    const [models, setModels] = useState([{ id: "auto", label: "Auto (free models)", free: true }]);

    useEffect(() => {
        fetch(`${API}/models`, { headers: { Authorization: `Bearer ${token}` } })
            .then(r => (r.ok ? r.json() : { models: [] }))
            .then(d => { if (d.models?.length) setModels(d.models); })
            .catch(() => {});
    }, [token]);

    const pick = (id) => {
        let next = id;
        if (id === HF_CUSTOM) {
            const repo = window.prompt("Hugging Face model id (owner/model)", value.startsWith("hf:") ? value.slice(3) : "");
            if (!repo?.trim()) return;
            next = `hf:${repo.trim()}`;
        }
        onChange(next);
        try { localStorage.setItem(storageKey, next); } catch {}
    };

    const hasHf = models.some(m => m.id === "huggingface");
    const free = models.filter(m => m.free);
    const paid = models.filter(m => !m.free);
    return (
        <select
            value={value} onChange={e => pick(e.target.value)} aria-label="Model"
            style={{ border: "1px solid var(--border)", borderRadius: "999px", padding: "5px 8px", fontSize: "12px",
                color: "var(--text-muted)", background: "transparent", maxWidth: "130px", minWidth: 0, flexShrink: 1 }}
        >
            <optgroup label="Free">{free.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}</optgroup>
            {(paid.length > 0 || hasHf) && (
                <optgroup label="Paid">
                    {paid.map(m => <option key={m.id} value={m.id}>{m.label}</option>)}
                    {hasHf && <option value={HF_CUSTOM}>Hugging Face model…</option>}
                </optgroup>
            )}
            {value.startsWith("hf:") && <option value={value}>{value.slice(3)}</option>}
            {!value.startsWith("hf:") && !models.some(m => m.id === value) && <option value={value}>{value}</option>}
        </select>
    );
}
