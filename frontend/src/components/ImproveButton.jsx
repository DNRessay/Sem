import { useState } from "react";

const API = import.meta.env.VITE_API_URL || "";

// ✨ Improve: rewrites the rough idea in a composer into the detailed prompt that tool works best with (the way the
// storyboard does for videos). The result lands in the box to edit before sending; ↶ puts the original back.
export default function ImproveButton({ headers, kind, text, setText, brief, extra, model, onLyrics, disabled, onError }) {
    const [busy, setBusy] = useState(false);
    const [before, setBefore] = useState(null);
    const run = async () => {
        setBusy(true);
        try {
            const r = await fetch(`${API}/design/improve`, { method: "POST", headers, body: JSON.stringify({ kind, text, brief, extra, model }) });
            const d = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : `Failed (${r.status})`);
            setBefore(text);
            setText(d.text);
            if (d.lyrics && onLyrics) onLyrics(d.lyrics);
        } catch (e) { onError?.(e.message); } finally { setBusy(false); }
    };
    return (<>
        {before !== null && !busy && (
            <button className="ds-chip" onClick={() => { setText(before); setBefore(null); }} title="Put my words back">↶</button>
        )}
        <button className="ds-chip" onClick={run} disabled={busy || disabled || !text.trim()}
            title="Turn my idea into a detailed prompt (you can edit it before sending)">
            {busy ? <span className="ds-spin" /> : "✨"} Improve
        </button>
    </>);
}
