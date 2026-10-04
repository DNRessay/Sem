import { useRef, useState } from "react";
import { canRecord, recordUtterance, transcribe } from "../utils/recordWav";

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

// Dictation into the message box: words appear while you speak (interim
// results), and it keeps listening until you tap the mic again. Browsers without speech recognition record
// instead, and Whistle on the server writes it down when you tap the mic again.
export default function VoiceInput({ value = "", onChange, token }) {
    const [listening, setListening] = useState(false);
    const recogRef = useRef(null);
    const baseRef = useRef("");

    const stop = () => { recogRef.current?.stop(); setListening(false); };

    const record = () => {
        const base = value.trim();
        const rec = recordUtterance({ autoStop: false });
        recogRef.current = rec;
        setListening(true);
        rec.done.then(async (wav) => {
            setListening(false);
            recogRef.current = null;
            if (!wav) return;
            try {
                const text = await transcribe(token || localStorage.getItem("semblance_token") || "", wav);
                if (text) onChange?.(base ? `${base} ${text}` : text);
            } catch (e) { alert(e.message); }
        });
    };

    const toggle = () => {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (listening) { stop(); return; }
        if (!SR && canRecord()) { record(); return; }
        if (!SR) { alert("Voice input isn't supported in this browser."); return; }
        baseRef.current = value.trim();
        const r = new SR();
        r.continuous = true;
        r.interimResults = true;
        r.lang = "en-ZA";
        r.onresult = (e) => {
            let heard = "";
            for (let i = 0; i < e.results.length; i++) heard += e.results[i][0].transcript;
            const text = heard.trim();
            onChange?.(baseRef.current && text ? `${baseRef.current} ${text}` : baseRef.current || text);
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
            title={listening ? "Listening — tap to stop" : "Voice input"}
            aria-label={listening ? "Stop voice input" : "Voice input"}
            style={{
                width: "32px", height: "32px", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
                background: listening ? "var(--danger-bg)" : "none", border: "none", borderRadius: "50%",
                color: listening ? "var(--danger)" : "var(--text-muted)", cursor: "pointer",
                animation: listening ? "sem-pulse 1.2s ease-in-out infinite" : "none",
            }}
        >
            <MicIcon />
        </button>
    );
}
