import { useState, useRef, useEffect } from "react";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { useStream } from "../hooks/useStream";
import { HandoffCard } from "./TabDrawer";
import { SendIcon, StopIcon } from "./Icons";
import { ChatMenu, CopyButton, DownloadAllButton, SpeakButton, SuggestModel, errorClass, handleCodeCardClick, renderMarkdown } from "./MessageKit";
import { useTypewriter } from "../hooks/useTypewriter";
import VoiceInput from "./VoiceInput";
import ModelPicker, { loadModel } from "./ModelPicker";
import AttachMenu, { GitHubIcon, GitLabIcon, AttachFileIcon, ImageIcon } from "./AttachMenu";
import { copyToClipboard } from "../utils/clipboard";
import { extractCodeBlocks, filenameFor, downloadText, downloadAllAsZip } from "../utils/codeBlocks";

const API = import.meta.env.VITE_API_URL || "";
const THINKING_WORDS = ["Thinking", "Pondering", "Mulling it over", "Sleuthing", "Working on it", "Piecing it together"];

function iconForSource(source, mime) {
    if (source === "github") return <GitHubIcon />;
    if (source === "gitlab") return <GitLabIcon />;
    if ((mime || "").startsWith("image/")) return <ImageIcon />;
    return <AttachFileIcon />;
}

function GlobeIcon() {
    return (
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="2" y1="12" x2="22" y2="12" />
            <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
    );
}

function useElapsedSeconds(active) {
    // Lives in the parent, not in whichever indicator happens to be
    // showing — searching and thinking used to each own a separate timer
    // that reset when the UI swapped between them, so the clock visibly
    // jumped back to 0s the moment a search finished. One timer for the
    // whole wait, started once when it begins and reset only when a brand
    // new wait begins.
    const [elapsed, setElapsed] = useState(0);
    const startRef = useRef(null);

    useEffect(() => {
        if (!active) return;
        startRef.current = Date.now();
        setElapsed(0);
        const id = setInterval(() => setElapsed(Math.round((Date.now() - startRef.current) / 1000)), 1000);
        return () => clearInterval(id);
    }, [active]);

    return elapsed;
}

function WaitLabel({ elapsed, status }) {
    const [i, setI] = useState(0);

    useEffect(() => {
        const id = setInterval(() => setI(v => (v + 1) % THINKING_WORDS.length), 1100);
        return () => clearInterval(id);
    }, []);

    return (
        <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", color: "var(--text-muted)", fontSize: "14px" }}>
            {status && <GlobeIcon />}
            {elapsed}s · {status || `${THINKING_WORDS[i]}…`}
        </span>
    );
}

function ToolChip({ tool }) {
    const [open, setOpen] = useState(false);
    if (!tool) return null;
    const hasDetail = !!tool.detail;
    return (
        <div style={{ marginBottom: "8px" }}>
            <button
                onClick={() => hasDetail && setOpen(v => !v)}
                style={{
                    display: "inline-flex", alignItems: "center", gap: "6px",
                    background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "8px",
                    padding: "5px 10px", fontSize: "12px", color: "var(--text-muted)",
                    cursor: hasDetail ? "pointer" : "default",
                }}
            >
                <GlobeIcon /> {tool.label}
                {hasDetail && <span style={{ fontSize: "9px" }}>{open ? "▾" : "▸"}</span>}
            </button>
            {open && hasDetail && (
                <pre style={{
                    marginTop: "6px", padding: "10px", background: "var(--surface)", border: "1px solid var(--border)",
                    borderRadius: "8px", fontSize: "11px", color: "var(--text-muted)", whiteSpace: "pre-wrap",
                    maxHeight: "240px", overflowY: "auto", fontFamily: "monospace",
                }}>
                    {tool.detail}
                </pre>
            )}
        </div>
    );
}

export default function ChatWindow({ sessionId = "default", initialHistory = [], onStreamChange, onTitle, token, onUnauthorized, onHandoff, draft }) {
    const [input, setInput] = useState("");
    useEffect(() => { if (draft?.task) setInput(draft.task); }, [draft?.at]); // eslint-disable-line react-hooks/exhaustive-deps
    const [history, setHistory] = useState(initialHistory);
    const [attachments, setAttachments] = useState([]);
    const [webSearchEnabled, setWebSearchEnabled] = useState(true);
    const [model, setModel] = useState(() => loadModel("semblance_chat_model"));
    const [research, setResearch] = useState(false);
    const { chunks, streaming, error, status, tool, send, abort } = useStream(API, token, onUnauthorized);
    const bottomRef = useRef(null);
    // Set once send() resolves and cleared once the typewriter below has
    // fully caught up to it — history isn't updated until then, so the
    // live streaming bubble (mid-animation) never gets abruptly swapped
    // out for the static final message.
    const [pendingReply, setPendingReply] = useState(null);

    const fullResponse = chunks.join("");
    const revealed = useTypewriter(fullResponse);
    const isWaiting = streaming && fullResponse.length === 0;
    const elapsed = useElapsedSeconds(isWaiting);

    useEffect(() => {
        onStreamChange?.(streaming);
    }, [streaming, onStreamChange]);

    useEffect(() => {
        bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }, [chunks, revealed, history]);

    // Commits the finished reply to history only once the typewriter has
    // revealed all of it — until then the live bubble below keeps showing
    // (and animating) the same content instead of a hard cut.
    useEffect(() => {
        if (!pendingReply || revealed.length < fullResponse.length) return;
        setHistory(h => [...h, { role: "assistant", content: pendingReply.reply, tool: pendingReply.tool, handoff: pendingReply.handoff,
                                 suggest: pendingReply.suggest, retry: pendingReply.retry }]);
        if (pendingReply.title) onTitle?.(sessionId, pendingReply.title);
        setPendingReply(null);
    }, [pendingReply, revealed, fullResponse, sessionId, onTitle]);

    const submit = async (retry = null, useModel = model) => {
        if (streaming) return;
        if (!retry && !input.trim() && attachments.length === 0) return;
        const msg = retry ?? input.trim();
        const files = retry ? [] : attachments;
        if (!retry) { setInput(""); setAttachments([]); }
        setHistory(h => [...h, { role: "user", content: msg, files: files.map(f => ({ name: f.name, source: f.source, mime: f.mime })) }]);
        const { reply, tool: toolResult, title, handoff, suggest } = await send(msg, sessionId, history, files, webSearchEnabled, useModel, research);
        if (reply || handoff) setPendingReply({ reply, tool: toolResult, title, handoff, suggest, retry: suggest ? msg : null });
        else if (title) onTitle?.(sessionId, title);
    };

    const addAttachment = (file) => setAttachments(a => [...a, file]);
    const removeAttachment = (name) => setAttachments(a => a.filter(f => f.name !== name));

    return (
        <div style={{ display: "flex", flexDirection: "column", flex: 1, minWidth: 0, height: "100%", background: "var(--bg)", color: "var(--text)", position: "relative" }}>
            {history.length > 0 && (
                <div style={{ position: "absolute", top: "6px", right: "8px", zIndex: 5 }}>
                    <ChatMenu title="SEMBLANCE chat" messages={history.map(m => ({ role: m.role, text: m.content || "" }))} />
                </div>
            )}
            <div style={{ flex: 1, overflowY: "auto", padding: "20px 16px", display: "flex", flexDirection: "column", gap: "18px" }}>
                {history.map((m, i) => (
                    m.role === "user" ? (
                        <div key={i} style={{ alignSelf: "flex-end", maxWidth: "80%", display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "4px" }}>
                            {m.files?.length > 0 && (
                                <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "3px" }}>
                                    <span style={{ fontSize: "10px", color: "var(--text-muted)" }}>Attached files</span>
                                    <div style={{ display: "flex", flexWrap: "wrap", gap: "4px", justifyContent: "flex-end" }}>
                                        {m.files.map(f => (
                                            <span key={f.name} style={{ display: "inline-flex", alignItems: "center", gap: "4px", fontSize: "11px", color: "var(--text-muted)", border: "1px solid var(--border)", borderRadius: "6px", padding: "2px 6px" }}>
                                                {iconForSource(f.source, f.mime)} {f.name}
                                            </span>
                                        ))}
                                    </div>
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
                            {m.tool && <ToolChip tool={m.tool} />}
                            <div
                                className={/^(Something went wrong|I've hit)/.test(m.content) ? `md-content ${errorClass(m.content)}` : "md-content"}
                                style={{ padding: "0 2px", fontSize: "15px", lineHeight: "1.7" }}
                                onClick={handleCodeCardClick}
                                dangerouslySetInnerHTML={renderMarkdown(m.content)}
                            />
                            {m.handoff && <HandoffCard tab={m.handoff.tab} task={m.handoff.task} onHandoff={onHandoff} />}
                            {m.suggest && i === history.length - 1 && (
                                <SuggestModel suggest={m.suggest} onSwitch={id => { setModel(id); submit(m.retry, id); }} />
                            )}
                            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                <CopyButton text={m.content} />
                                <SpeakButton text={m.content} token={token} />
                                <DownloadAllButton content={m.content} />
                            </div>
                        </div>
                    )
                ))}
                {isWaiting && (
                    <div style={{ alignSelf: "flex-start", padding: "6px 2px" }}>
                        {tool && <ToolChip tool={tool} />}
                        <WaitLabel elapsed={elapsed} status={status} />
                    </div>
                )}
                {(streaming || pendingReply) && fullResponse.length > 0 && (
                    <div style={{ alignSelf: "flex-start", maxWidth: "88%", padding: "0 2px" }}>
                        {tool && <ToolChip tool={tool} />}
                        <div
                            className="md-content"
                            style={{ fontSize: "15px", lineHeight: "1.7" }}
                            onClick={handleCodeCardClick}
                            dangerouslySetInnerHTML={renderMarkdown(revealed + " ▋")}
                        />
                    </div>
                )}
                {error && (
                    <div className={errorClass(error)} style={{ alignSelf: "flex-start", maxWidth: "80%", lineHeight: "1.6" }}>
                        {error}
                    </div>
                )}
                <div ref={bottomRef} />
            </div>
            <div style={{ padding: "8px 8px 24px", width: "100%", boxSizing: "border-box" }}>
                <div style={{ display: "flex", flexDirection: "column", width: "100%", boxSizing: "border-box", background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "26px", padding: "10px 14px 8px" }}>
                    {attachments.length > 0 && (
                        <div style={{ display: "flex", flexDirection: "column", gap: "4px", padding: "0 2px 8px" }}>
                            <span style={{ fontSize: "10px", color: "var(--text-muted)" }}>Attached files</span>
                            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px" }}>
                                {attachments.map(f => {
                                    const isImage = (f.mime || "").startsWith("image/") && f.base64;
                                    return (
                                        <span key={f.name} style={{ display: "inline-flex", alignItems: "center", gap: "6px", fontSize: "12px", color: "var(--text)", background: "var(--bg)", border: "1px solid var(--border)", borderRadius: "8px", padding: "4px 8px" }}>
                                            {isImage ? (
                                                <img src={`data:${f.mime};base64,${f.base64}`} alt="" style={{ width: "20px", height: "20px", objectFit: "cover", borderRadius: "4px" }} />
                                            ) : iconForSource(f.source, f.mime)}
                                            {f.name}
                                            <button onClick={() => removeAttachment(f.name)} aria-label={`Remove ${f.name}`} style={{ background: "none", border: "none", color: "var(--text-muted)", cursor: "pointer", fontSize: "13px", lineHeight: 1, padding: 0 }}>✕</button>
                                        </span>
                                    );
                                })}
                            </div>
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
                        <AttachMenu
                            token={token} sessionId={sessionId} onAttach={addAttachment}
                            webSearchEnabled={webSearchEnabled} onToggleWebSearch={setWebSearchEnabled}
                        />
                        <ModelPicker token={token} value={model} onChange={setModel} storageKey="semblance_chat_model" />
                        <button
                            onClick={() => setResearch(r => !r)}
                            aria-pressed={research}
                            title="Deep research: searches and reads several sources, then answers with citations (slower)"
                            style={{
                                border: "1px solid var(--border)", borderRadius: "999px", padding: "5px 10px", fontSize: "12px", cursor: "pointer",
                                background: research ? "var(--accent)" : "transparent", color: research ? "var(--accent-contrast)" : "var(--text-muted)",
                            }}
                        >
                            Research
                        </button>
                        <span style={{ flex: 1 }} />
                        <VoiceInput value={input} onChange={setInput} />
                        <button
                            onClick={streaming ? abort : () => submit()}
                            aria-label={streaming ? "Stop" : "Send"} className={streaming ? "" : "btn-gold"}
                            style={{
                                width: "32px", height: "32px", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
                                background: streaming ? "var(--danger)" : "var(--accent)", border: "none", borderRadius: "50%",
                                color: "var(--accent-contrast)", cursor: "pointer", fontSize: "15px",
                            }}
                        >
                            {streaming ? <StopIcon size={14} /> : <SendIcon size={16} />}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
