import { useRef, useState } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { copyToClipboard } from "../utils/clipboard";
import { downloadAllAsZip, downloadText, extractCodeBlocks, filenameFor } from "../utils/codeBlocks";

const API = import.meta.env.VITE_API_URL || "";

// Message rendering and per-message actions shared by the main chat and every tab.
function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// Fenced code blocks render as "code cards" — a header (language + Copy/
// Download) above the code — instead of marked's plain <pre><code>, so a
// reply with code doesn't force copying the whole message just to grab one
// snippet. A fresh renderer per call resets the per-message snippet
// counter (snippet-1.py, snippet-2.js, ...), keeping it in sync with
// extractCodeBlocks' same top-to-bottom order used for the zip download.
function buildRenderer() {
    const renderer = new marked.Renderer();
    let index = 0;
    renderer.code = ({ text, lang }) => {
        const filename = filenameFor(lang, index++);
        const langLabel = (lang || "text").split(/\s+/)[0] || "text";
        return (
            `<div class="code-card">`
            + `<div class="code-card-header">`
            + `<span class="code-card-lang">${escapeHtml(langLabel)}</span>`
            + `<span class="code-card-actions">`
            + `<button type="button" class="code-card-btn" data-action="copy">Copy</button>`
            + `<button type="button" class="code-card-btn" data-action="download" data-filename="${escapeHtml(filename)}">Download</button>`
            + `</span></div>`
            + `<pre><code>${escapeHtml(text)}</code></pre>`
            + `</div>`
        );
    };
    return renderer;
}

export function renderMarkdown(text) {
    return { __html: DOMPurify.sanitize(marked.parse(text, { breaks: true, renderer: buildRenderer() })) };
}

// Event delegation, not a per-card React handler — the code cards are raw
// HTML from dangerouslySetInnerHTML, so there's nowhere to attach a real
// onClick inside them. One listener on the message's outer div catches
// every card's button clicks instead.
export function handleCodeCardClick(e) {
    const btn = e.target.closest(".code-card-btn");
    if (!btn) return;
    const codeEl = btn.closest(".code-card")?.querySelector("pre code");
    if (!codeEl) return;
    const text = codeEl.textContent;

    if (btn.dataset.action === "copy") {
        copyToClipboard(text);
        const original = btn.textContent;
        btn.textContent = "Copied";
        setTimeout(() => { btn.textContent = original; }, 1200);
    } else if (btn.dataset.action === "download") {
        downloadText(btn.dataset.filename || "snippet.txt", text);
    }
}

export function DownloadAllButton({ content }) {
    const blocks = extractCodeBlocks(content);
    if (blocks.length < 2) return null;
    return (
        <button
            onClick={() => downloadAllAsZip(blocks)}
            style={{
                display: "flex", alignItems: "center", gap: "4px", background: "none",
                border: "1px solid var(--border)", borderRadius: "999px", padding: "4px 10px",
                fontSize: "11px", color: "var(--text-muted)", cursor: "pointer",
            }}
        >
            Download all ({blocks.length} files, .zip)
        </button>
    );
}

function CopyIcon() {
    return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="9" width="13" height="13" rx="2" />
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
    );
}

function CheckIcon() {
    return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
        </svg>
    );
}

// Reads a reply aloud with Gemini's TTS (/media/speech). Strips markdown
// and code blocks first — nobody wants a code listing read out.
export function SpeakButton({ text, token }) {
    const [state, setState] = useState("idle"); // idle | loading | playing
    const audioRef = useRef(null);

    const toggle = async () => {
        if (state === "playing") { audioRef.current?.pause(); setState("idle"); return; }
        if (state === "loading") return;
        const plain = text.replace(/```[\s\S]*?```/g, " (code omitted) ").replace(/[#*_`>|\[\]]/g, "").trim();
        if (!plain) return;
        setState("loading");
        try {
            const r = await fetch(`${API}/media/speech`, {
                method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({ text: plain }),
            });
            if (!r.ok) throw new Error();
            const d = await r.json();
            const audio = new Audio(`data:${d.mime};base64,${d.base64}`);
            audioRef.current = audio;
            audio.onended = () => setState("idle");
            await audio.play();
            setState("playing");
        } catch { setState("idle"); }
    };

    return (
        <button onClick={toggle} aria-label={state === "playing" ? "Stop reading" : "Read aloud"} title="Read aloud (Gemini voice)"
            style={{ width: "26px", height: "26px", display: "flex", alignItems: "center", justifyContent: "center",
                background: "none", border: "none", borderRadius: "6px", color: "var(--text-muted)", cursor: "pointer", fontSize: "13px" }}>
            {state === "loading" ? "…" : state === "playing" ? "■" : "🔊"}
        </button>
    );
}

export function CopyButton({ text }) {
    const [copied, setCopied] = useState(false);

    const handleCopy = async () => {
        await copyToClipboard(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
    };

    return (
        <button
            onClick={handleCopy}
            aria-label={copied ? "Copied" : "Copy"}
            title={copied ? "Copied" : "Copy"}
            style={{
                width: "26px", height: "26px", display: "flex", alignItems: "center", justifyContent: "center",
                background: "none", border: "none", borderRadius: "6px",
                color: copied ? "var(--accent)" : "var(--text-muted)", cursor: "pointer",
            }}
        >
            {copied ? <CheckIcon /> : <CopyIcon />}
        </button>
    );
}


const pill = {
    display: "flex", alignItems: "center", gap: "4px", background: "none", border: "1px solid var(--border)",
    borderRadius: "999px", padding: "4px 10px", fontSize: "11px", color: "var(--text-muted)", cursor: "pointer",
};

// An assistant reply in any tab: markdown with code cards, then copy / read aloud / download-all.
export function AssistantText({ text, token }) {
    return (
        <div style={{ margin: "6px 0" }}>
            <div className="md-content" style={{ fontSize: "14px", color: "var(--text)" }}
                onClick={handleCodeCardClick} dangerouslySetInnerHTML={renderMarkdown(text)} />
            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                <CopyButton text={text} />
                {token && <SpeakButton text={text} token={token} />}
                <DownloadAllButton content={text} />
            </div>
        </div>
    );
}

// "Free models are out — use <cheapest paid> for this?" Never switches on its own.
export function SuggestModel({ suggest, onSwitch }) {
    if (!suggest) return null;
    return (
        <button onClick={() => onSwitch(suggest.id)} style={{ ...pill, margin: "6px 0", color: "var(--text)", fontWeight: 600 }}>
            Use {suggest.label} (paid) and retry
        </button>
    );
}

function allArtifacts(messages) {
    const out = [];
    messages.filter(m => m.role === "assistant").forEach(m => extractCodeBlocks(m.text || "").forEach(b => out.push(b)));
    return out;
}

export function exportChat(title, messages) {
    const stamp = new Date().toISOString().slice(0, 16).replace(/[:T]/g, "-");
    const body = messages.map(m => `### ${m.role === "user" ? "You" : "Sem"}\n\n${m.text}`).join("\n\n");
    downloadText(`${(title || "chat").replace(/[^\w-]+/g, "-").slice(0, 40)}-${stamp}.md`, `# ${title || "Chat"}\n\n${body}\n`);
}

function ArtifactsDrawer({ open, onClose, artifacts }) {
    return (
        <>
            <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.25)", opacity: open ? 1 : 0, pointerEvents: open ? "auto" : "none", transition: "opacity 0.2s", zIndex: 42 }} />
            <div style={{ position: "fixed", top: 0, right: 0, bottom: 0, width: "90%", maxWidth: "420px", background: "var(--bg)", borderLeft: "1px solid var(--border)", transform: open ? "translateX(0)" : "translateX(100%)", transition: "transform 0.2s", zIndex: 43, display: "flex", flexDirection: "column" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "8px", padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                    <span style={{ fontWeight: 700, flex: 1 }}>Artifacts ({artifacts.length})</span>
                    {artifacts.length > 0 && <button onClick={() => downloadAllAsZip(artifacts)} style={pill}>Download all (.zip)</button>}
                    <button onClick={onClose} aria-label="Close artifacts" style={{ background: "none", border: "none", cursor: "pointer", fontSize: "18px", color: "var(--text-muted)" }}>✕</button>
                </div>
                <div style={{ flex: 1, overflowY: "auto", padding: "8px 16px" }}>
                    {!artifacts.length && <div style={{ color: "var(--text-muted)", fontSize: "13px" }}>No code or files in this chat yet.</div>}
                    {artifacts.map((a, i) => {
                        const name = filenameFor(a.lang, i);
                        return (
                            <details key={i} style={{ border: "1px solid var(--border)", borderRadius: "10px", margin: "8px 0", background: "var(--surface)" }}>
                                <summary style={{ cursor: "pointer", padding: "8px 10px", fontSize: "13px", display: "flex", gap: "8px", alignItems: "center" }}>
                                    <span style={{ flex: 1, fontFamily: "ui-monospace, monospace" }}>{name}</span>
                                    <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>{a.code.split("\n").length} lines</span>
                                </summary>
                                <div style={{ display: "flex", gap: "6px", padding: "0 10px 6px" }}>
                                    <button onClick={() => copyToClipboard(a.code)} style={pill}>Copy</button>
                                    <button onClick={() => downloadText(name, a.code)} style={pill}>Download</button>
                                </div>
                                <pre style={{ margin: 0, padding: "8px 10px", fontSize: "11px", maxHeight: "280px", overflow: "auto", borderTop: "1px solid var(--border)", whiteSpace: "pre" }}>{a.code}</pre>
                            </details>
                        );
                    })}
                </div>
            </div>
        </>
    );
}

// The ⋯ menu on top of every chat: artifacts drawer, download all, export.
export function ChatMenu({ title, messages }) {
    const [open, setOpen] = useState(false);
    const [drawer, setDrawer] = useState(false);
    const artifacts = allArtifacts(messages);
    const item = { display: "block", width: "100%", textAlign: "left", padding: "10px 14px", background: "none", border: "none", color: "var(--text)", fontSize: "13px", cursor: "pointer" };
    return (
        <div style={{ position: "relative" }}>
            <button onClick={() => setOpen(o => !o)} aria-label="Chat options" style={{ background: "none", border: "none", cursor: "pointer", fontSize: "20px", color: "var(--text)", padding: "0 6px" }}>⋯</button>
            {open && (
                <>
                    <div onClick={() => setOpen(false)} style={{ position: "fixed", inset: 0, zIndex: 30 }} />
                    <div style={{ position: "absolute", right: 0, top: "100%", zIndex: 31, minWidth: "220px", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "12px", boxShadow: "0 8px 24px rgba(0,0,0,0.18)", overflow: "hidden" }}>
                        <button style={item} onClick={() => { setOpen(false); setDrawer(true); }}>Artifacts ({artifacts.length})</button>
                        <button style={{ ...item, opacity: artifacts.length ? 1 : 0.5 }} disabled={!artifacts.length} onClick={() => { setOpen(false); downloadAllAsZip(artifacts); }}>Download all artifacts (.zip)</button>
                        <button style={{ ...item, opacity: messages.length ? 1 : 0.5 }} disabled={!messages.length} onClick={() => { setOpen(false); exportChat(title, messages); }}>Export chat (.md)</button>
                    </div>
                </>
            )}
            <ArtifactsDrawer open={drawer} onClose={() => setDrawer(false)} artifacts={artifacts} />
        </div>
    );
}

const MAX_ATTACH_BYTES = 200 * 1024;

// "+" attach for the tabs: text/code files are read here and sent with the message.
export function AttachButton({ files, setFiles, disabled }) {
    const [error, setError] = useState("");
    const add = async (list) => {
        setError("");
        const added = [];
        for (const f of list) {
            if (f.size > MAX_ATTACH_BYTES) { setError(`${f.name} is over 200 KB — attach a smaller file or the relevant part`); continue; }
            const text = await f.text();
            if (/\u0000/.test(text.slice(0, 2000))) { setError(`${f.name} isn't a text file`); continue; }
            added.push({ name: f.name, text });
        }
        setFiles(x => [...x, ...added].slice(0, 8));
    };
    return (
        <>
            <label title="Attach files" style={{ width: "30px", height: "30px", borderRadius: "50%", border: "1px solid var(--border)", display: "inline-flex", alignItems: "center", justifyContent: "center", cursor: disabled ? "default" : "pointer", color: "var(--text-muted)", fontSize: "18px", flexShrink: 0, opacity: disabled ? 0.5 : 1 }}>
                +
                <input type="file" multiple disabled={disabled} style={{ display: "none" }} onChange={e => { add([...e.target.files]); e.target.value = ""; }} />
            </label>
            {error && <span style={{ fontSize: "11px", color: "var(--danger)" }}>{error}</span>}
        </>
    );
}

export function AttachedChips({ files, setFiles }) {
    if (!files.length) return null;
    return (
        <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", marginBottom: "6px" }}>
            {files.map((f, i) => (
                <span key={i} style={{ display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "11px", color: "var(--text-muted)", border: "1px solid var(--border)", borderRadius: "6px", padding: "2px 6px" }}>
                    📄 {f.name}
                    <button onClick={() => setFiles(x => x.filter((_, j) => j !== i))} aria-label={`Remove ${f.name}`} style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text-muted)", padding: 0 }}>✕</button>
                </span>
            ))}
        </div>
    );
}

export function withAttachments(message, files) {
    if (!files.length) return message;
    return `${message}\n\n` + files.map(f => `Attached file \`${f.name}\`:\n\`\`\`\n${f.text}\n\`\`\``).join("\n\n");
}

// Colour coding for problems: limits/overloads amber (wait or switch model), everything else red.
export function errorClass(text = "") {
    return /limit|rate|quota|429|credits|overload|high demand|503|time limit|try again/i.test(text) ? "msg-warning" : "msg-error";
}
