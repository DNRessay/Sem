import { useState, useRef } from "react";

export default function VoiceInput({ onTranscript }) {
    const [listening, setListening] = useState(false);
    const recogRef = useRef(null);

    const toggle = () => {
        if (!("webkitSpeechRecognition" in window || "SpeechRecognition" in window)) {
            alert("Speech recognition not supported in this browser.");
            return;
        }
        if (listening) {
            recogRef.current?.stop();
            setListening(false);
            return;
        }
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        const r = new SR();
        r.continuous = false;
        r.interimResults = false;
        r.lang = "en-US";
        r.onresult = e => {
            onTranscript?.(e.results[0][0].transcript);
            setListening(false);
        };
        r.onerror = () => setListening(false);
        r.onend = () => setListening(false);
        recogRef.current = r;
        r.start();
        setListening(true);
    };

    return (
        <button onClick={toggle} title="Voice input" style={{ background: "none", border: `1px solid ${listening ? "#f97316" : "#1e293b"}`, borderRadius: "6px", padding: "8px 12px", color: listening ? "#f97316" : "#475569", cursor: "pointer", fontSize: "14px" }}>
            {listening ? "🔴" : "🎙️"}
        </button>
    );
}