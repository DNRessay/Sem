import { useState, useRef, useEffect } from "react";
import { useStream } from "../hooks/useStream";
import VoiceInput from "./VoiceInput";

const API = import.meta.env.VITE_API_URL || "";

export default function ChatWindow({ sessionId = "default" }) {
    const [input, setInput] = useState("");
    const [history, setHistory] = useState([]);
    const { chunks, streaming, error, send, abort } = useStream(API);
    const bottomRef = useRef(null);

    const fullResponse = chunks.join("");

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
        <div style={{ display: "flex", flexDirection: "column", height: "100%", background: "#050a0f", color: "#e2e8f0", fontFamily: "monospace" }}>
            <div style={{ flex: 1, overflowY: "auto", padding: "16px", display: "flex", flexDirection: "column", gap: "12px" }}>
                {history.map((m, i) => (
                    <div key={i} style={{ alignSelf: m.role === "user" ? "flex-end" : "flex-start", maxWidth: "80%", background: m.role === "user" ? "#1e3a5f" : "#0f1e2e", padding: "10px 14px", borderRadius: "8px", fontSize: "13px", lineHeight: "1.6" }}>
                        {m.content}
                    </div>
                ))}
                {streaming && (
                    <div style={{ alignSelf: "flex-start", maxWidth: "80%", background: "#0f1e2e", padding: "10px 14px", borderRadius: "8px", fontSize: "13px", lineHeight: "1.6", color: "#00f5ff" }}>
                        {fullResponse}<span style={{ opacity: 0.5 }}>▋</span>
                    </div>
                )}
                {error && (
                    <div style={{ alignSelf: "flex-start", maxWidth: "80%", background: "#3f0f0f", padding: "10px 14px", borderRadius: "8px", fontSize: "13px", lineHeight: "1.6", color: "#f87171" }}>
                        {error}
                    </div>
                )}
                <div ref={bottomRef} />
            </div>
            <div style={{ display: "flex", gap: "8px", padding: "12px", borderTop: "1px solid #1e293b" }}>
                <VoiceInput onTranscript={text => setInput(prev => (prev ? `${prev} ${text}` : text))} />
                <input
                    value={input}
                    onChange={e => setInput(e.target.value)}
                    onKeyDown={e => e.key === "Enter" && !e.shiftKey && submit()}
                    placeholder="Message SEMBLANCE..."
                    style={{ flex: 1, background: "#0a1628", border: "1px solid #1e3a5f", borderRadius: "6px", padding: "10px 14px", color: "#e2e8f0", fontFamily: "monospace", fontSize: "13px", outline: "none" }}
                />
                <button onClick={streaming ? abort : submit} style={{ padding: "10px 18px", background: streaming ? "#7f1d1d" : "#1e3a5f", border: "none", borderRadius: "6px", color: "#e2e8f0", cursor: "pointer", fontFamily: "monospace", fontSize: "13px" }}>
                    {streaming ? "Stop" : "Send"}
                </button>
            </div>
        </div>
    );
}