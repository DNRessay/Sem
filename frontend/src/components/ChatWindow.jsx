import { useState, useRef, useEffect } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { useStream } from "../hooks/useStream";
import VoiceInput from "./VoiceInput";
import AttachMenu from "./AttachMenu";

const API = import.meta.env.VITE_API_URL || "";
const MODEL_LABEL = "Qwen";
const THINKING_WORDS = ["Thinking", "Pondering", "Mulling it over", "Sleuthing", "Working on it", "Piecing it together"];

function renderMarkdown(text) {
    return { __html: DOMPurify.sanitize(marked.parse(text, { breaks: true })) };
}

function CopyIcon() {
    return (
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="9" width="13" height="13" rx="2" />
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
        </svg>
    );
}

function FileIcon() {
    return (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
            <polyline points="14 2 14 8 20 8" />
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

function CopyButton({ text }) {
    const [copied, setCopied] = useState(false);

    const handleCopy = async () => {
        try {
            await navigator.clipboard.writeText(text);
        } catch {
            const ta = document.createElement("textarea");
            ta.value = text;
            ta.style.position = "fixed";
            ta.style.opacity = "0";
            document.body.appendChild(ta);
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
        }
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

function ThinkingIndicator() {
    const [i, setI] = useState(0);
    const [elapsed, setElapsed] = useState(0);
    const startRef = useRef(Date.now());

    useEffect(() => {
        const wordId = setInterval(() => setI(v => (v + 1) % THINKING_WORDS.length), 1100);
        const tickId = setInterval(() => setElapsed(Math.round((Date.now() - startRef.current) / 1000)), 1000);
        return () => { clearInterval(wordId); clearInterval(tickId); };
    }, []);

    return (
        <span style={{ color: "var(--text-muted)", fontSize: "14px" }}>
            {elapsed}s · {THINKING_WORDS[i]}…
        </span>
    );
}

export default function ChatWindow({ sessionId = "default", initialHistory = [], onStreamChange, onNewChat, token, onUnauthorized }) {
    const [input, setInput] = useState("");
    const [history, setHistory] = useState(initialHistory);
    const [attachments, setAttachments] = useState([]);
    const { chunks, streaming, error, send, abort } = useStream(API, token, onUnauthorized);
    const bottomRef = useRef(null);

    const fullResponse = chunks.join("");
    const isThinking = streaming && fullResponse.length === 0;

    useEffect(() => {
        onStreamChange?.(streaming);
    }, [streaming, onStreamChange]);

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [chunks, history]);

    const submit = async () => {
        if ((!input.trim() && attachments.length === 0) || streaming) return;
        const msg = input.trim();
        const files = attachments;
        setInput("");
        setAttachments([]);
        setHistory(h => [...h, { role: "user", content: msg, files: files.map(f => f.name) }]);
        const reply = await send(msg, sessionId, history, files);
        if (reply) setHistory(h => [...h, { role: "assistant", content: reply }]);
    };

    const addAttachment = (file) => setAttachments(a => [...a, file]);
    const removeAttachment = (name) => setAttachments(a => a.filter(f => f.name !== name));

    return (
        <div style={{ display: "flex", flexDirection: "column", flex: 1, minWidth: 0, height: "100%", background: "var(--bg)", color: "var(--text)" }}>
            <div style={{ flex: 1, overflowY: "auto", padding: "20px 16px", display: "flex", flexDirection: "column", gap: "18px" }}>
                {history.map((m, i) => (
                    m.role === "user" ? (
                        <div key={i} style={{ alignSelf: "flex-end", maxWidth: "80%", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "4px" }}>
                            {m.files?.length > 0 && (
                                <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", justifyContent: "flex-end" }}>
                                    {m.files.map(name => (
                                        <span key={name} style={{ display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "11px", color: "var(--text-muted)", border: "1px solid var(--border)", borderRadius: "6px", padding: "2px 6px" }}>
                                            <FileIcon /> {name}
                                        </span>
                                    ))}
                                </div>
                            )}
                            {m.content && (
                                <div style={{ background: "var(--surface)", padding: "10px 14px", borderRadius: "18px", fontSize: "15px", lineHeight: "1.6" }}>
                                    {m.content}
                                </div>
                            )}
                        </div>
                    ) : (
                        <div key={i} style={{ alignSelf: "flex-start", maxWidth: "88%" }}>
                            <div
                                className="md-content"
                                style={{ padding: "0 2px", fontSize: "15px", lineHeight: "1.7" }}
                                dangerouslySetInnerHTML={renderMarkdown(m.content)}
                            />
                            <CopyButton text={m.content} />
                        </div>
                    )
                ))}
                {isThinking && (
                    <div style={{ alignSelf: "flex-start", padding: "6px 2px" }}>
                        <ThinkingIndicator />
                    </div>
                )}
                {streaming && !isThinking && (
                    <div
                        className="md-content"
                        style={{ alignSelf: "flex-start", maxWidth: "88%", padding: "0 2px", fontSize: "15px", lineHeight: "1.7" }}
                        dangerouslySetInnerHTML={renderMarkdown(fullResponse + " ▋")}
                    />
                )}
                {error && (
                    <div style={{ alignSelf: "flex-start", maxWidth: "80%", background: "rgba(196,69,58,0.08)", border: "1px solid var(--danger)", padding: "10px 14px", borderRadius: "12px", fontSize: "13px", lineHeight: "1.6", color: "var(--danger)" }}>
                        {error}
                    </div>
                )}
                <div ref={bottomRef} />
            </div>
            <div style={{ padding: "8px 8px 24px", width: "100%", boxSizing: "border-box" }}>
                <div style={{ display: "flex", flexDirection: "column", width: "100%", boxSizing: "border-box", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "26px", padding: "10px 14px 8px" }}>
                    {attachments.length > 0 && (
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", padding: "0 2px 8px" }}>
                            {attachments.map(f => (
                                <span key={f.name} style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "var(--text)", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: "8px", padding: "4px 8px" }}>
                                    <FileIcon /> {f.name}
                                    <button onClick={() => removeAttachment(f.name)} aria-label={`Remove ${f.name}`} style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: "13px", lineHeight: 1, padding: 0 }}>✕</button>
                                </span>
                            ))}
                        </div>
                    )}
                    <input
                        value={input}
                        onChange={e => setInput(e.target.value)}
                        onKeyDown={e => e.key === "Enter" && !e.shiftKey && submit()}
                        placeholder="Message SEMBLANCE..."
                        style={{ width: "100%", boxSizing: "border-box", background: "transparent", border: "none", padding: "2px 2px 8px", color: "var(--text)", fontSize: "15px", outline: "none" }}
                    />
                    <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                        <button
                            onClick={onNewChat}
                            aria-label="New chat"
                            style={{
                                width: "32px", height: "32px", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
                                background: "none", border: "1px solid var(--border)", borderRadius: "50%",
                                color: "var(--text-muted)", cursor: "pointer", fontSize: "17px", lineHeight: 1,
                            }}
                        >
                            +
                        </button>
                        <AttachMenu token={token} onAttach={addAttachment} />
                        <span style={{ display: "flex", alignItems: "center", gap: "3px", border: "1px solid var(--border)", borderRadius: "999px", padding: "5px 10px", fontSize: "12px", color: "var(--text-muted)" }}>
                            {MODEL_LABEL} <span style={{ fontSize: "9px" }}>▾</span>
                        </span>
                        <span style={{ flex: 1 }} />
                        <VoiceInput onTranscript={text => setInput(prev => (prev ? `${prev} ${text}` : text))} />
                        <button
                            onClick={streaming ? abort : submit}
                            aria-label={streaming ? "Stop" : "Send"}
                            style={{
                                width: "32px", height: "32px", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
                                background: streaming ? "var(--danger)" : "var(--accent)", border: "none", borderRadius: "50%",
                                color: "var(--accent-contrast)", cursor: "pointer", fontSize: "15px",
                            }}
                        >
                            {streaming ? "■" : "↑"}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
