// A tool-use marker the backend prepends only to what it *persists* for an
// assistant turn (gateway/router.py) — never to what actually streams live —
// so a reloaded/reopened session can still show which tool ran, without
// storing the full search-result dump as part of the message itself.
const MARKER_RE = /^\[\[SEMBLANCE_TOOL:(.+?)\]\]\n?/;

export function parseToolMarker(content) {
    const m = MARKER_RE.exec(content || "");
    if (!m) return { content, tool: null };
    try {
        return { content: content.slice(m[0].length), tool: JSON.parse(m[1]) };
    } catch {
        return { content, tool: null };
    }
}

// Maps raw /history turns (role/content only) into the shape ChatWindow
// renders, stripping and surfacing any tool marker on assistant turns.
export function turnsToHistory(turns) {
    return (turns || []).map(t => {
        if (t.role !== "assistant") return { role: t.role, content: t.content };
        const { content, tool } = parseToolMarker(t.content);
        return { role: t.role, content, tool };
    });
}
