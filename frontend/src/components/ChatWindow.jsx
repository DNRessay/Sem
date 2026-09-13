import { useState, useRef, useEffect } from "react";
import { useStream } from "../hooks/useStream";
import VoiceInput from "./VoiceInput";

const API = import.meta.env.VITE_API_URL || "";

export default function ChatWindow({ sessionId = "default", onStreamChange }) {
    const [input, setInput] = useState("");
    const [history, setHistory] = useState([]);
    const { chunks, streaming, error, send, abort } = useStream(API);
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
        if (!input.trim() || streaming) return;
        const msg = input.trim();
        setInput("");
        setHistory(h => [...h, { role: "user", content: msg }]);
        const reply = await send(msg, sessionId, history);
        if (reply) setHistory(h => [...h, { role: "assistant", content: reply }]);
    };

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "var(--bg)", color: "var(--text)" }}>
            <div style={{ flex: 1, overflowY: "auto", padding: "20px 16px", display: "flex", flexDirection: "column", gap: "18px" }}>
                {history.map((m, i) => (
                    m.role === "user" ? (
                        <div key={i} style={{ alignSelf: "flex-end", maxWidth: "80%", background: "var(--surface-2)", padding: "10px 14px", borderRadius: "16px", fontSize: "14px", lineHeight: "1.6" }}>
                            {m.content}
                        </div>
                    ) : (
                        <div key={i} style={{ alignSelf: "flex-start", maxWidth: "85%", padding: "0 2px", fontSize: "14px", lineHeight: "1.7", whiteSpace: "pre-wrap" }}>
                            {m.content}
                        </div>
                    )
                ))}
                {isThinking && (
                    <div style={{ alignSelf: "flex-start", padding: "6px 2px" }}>
                        <span className="thinking-dots"><span /><span /><span /></span>
                    </div>
                )}
                {streaming && !isThinking && (
                    <div style={{ alignSelf: "flex-start", maxWidth: "85%", padding: "0 2px", fontSize: "14px", lineHeight: "1.7", whiteSpace: "pre-wrap" }}>
                        {fullResponse}<span style={{ opacity: 0.5, color: "var(--accent)" }}>▋</span>
                    </div>
                )}
                {error && (
                    <div style={{ alignSelf: "flex-start", maxWidth: "80%", background: "rgba(196,69,58,0.12)", border: "1px solid var(--danger)", padding: "10px 14px", borderRadius: "10px", fontSize: "13px", lineHeight: "1.6", color: "#e5897f" }}>
                        {error}
                    </div>
                )}
                <div ref={bottomRef} />
            </div>
            <div style={{ display: "flex", gap: "8px", padding: "12px 16px", borderTop: "1px solid var(--border)" }}>
                <VoiceInput onTranscript={text => setInput(prev => (prev ? `${prev} ${text}` : text))} />
                <input
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => e.key === "Enter" && !e.shiftKey && submit()}
                    placeholder="Message SEMBLANCE..."
                    style={{ flex: 1, background: "var(--surface)", border: "1px solid var(--border)", borderRadius: "10px", padding: "10px 14px", color: "var(--text)", fontSize: "14px", outline: "none" }}
                />
                <button onClick={streaming ? abort : submit} style={{ padding: "10px 18px", background: streaming ? "var(--danger)" : "var(--accent)", border: "none", borderRadius: "10px", color: "#fff", cursor: "pointer", fontSize: "13px", fontWeight: "600" }}>
                    {streaming ? "Stop" : "Send"}
                </button>
            </div>
        </div>
    );
}
