import { useState, useRef } from "react";

function MicIcon() {
    return (
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="23" />
            <line x1="8" y1="23" x2="16" y2="23" />
        </svg>
    );
}

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
                color: listening ? "var(--danger)" : "var(--text-muted)", cursor: "pointer",
            }}
        >
            <MicIcon />
        </button>
    );
}
