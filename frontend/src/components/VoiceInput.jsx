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
        <button
            onClick={toggle}
            title="Voice input"
            aria-label="Voice input"
            style={{
                width: "32px", height: "32px", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
                background: "none", border: "none", borderRadius: "50%",
                color: listening ? "var(--danger)" : "var(--text-muted)", cursor: "pointer", fontSize: "15px",
            }}
        >
            {listening ? "●" : "🎙"}
        </button>
    );
}
