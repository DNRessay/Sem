import { useEffect, useRef, useState } from "react";
import { GoldS } from "./Working";

const API = import.meta.env.VITE_API_URL || "";
const MAX_SPOKEN = 1200;

function plainForSpeech(text) {
    let t = (text || "").replace(/```[\s\S]*?```/g, " I've put the code in the chat. ")
        .replace(/!\[[^\]]*\]\([^)]*\)/g, "").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
        .replace(/[#*_`>|]/g, "").replace(/\s+/g, " ").trim();
    if (t.length > MAX_SPOKEN) t = t.slice(0, MAX_SPOKEN).replace(/[^.!?]*$/, "") + " The rest is in the chat.";
    return t;
}

// Hands-free conversation: listens, sends what you said when you pause,
// waits for Sem's reply, reads it out, then listens again. Tap the orb to
// cut Sem off and talk; End to stop. The chat underneath keeps every turn.
export default function VoiceMode({ token, send, busy, lastReply, onClose }) {
    const [phase, setPhase] = useState("listening"); // listening | thinking | speaking | paused
    const [heard, setHeard] = useState("");
    const [note, setNote] = useState("");
    const open = useRef(true);
    const recog = useRef(null);
    const audio = useRef(null);
    const pending = useRef(null); // { before, sawBusy }

    const stopSpeaking = () => {
        audio.current?.pause(); audio.current = null;
        window.speechSynthesis?.cancel();
    };

    const listen = () => {
        if (!open.current) return;
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) { setNote("Voice isn't supported in this browser — try Chrome."); setPhase("paused"); return; }
        setPhase("listening"); setHeard("");
        const r = new SR();
        r.lang = "en-ZA"; r.interimResults = true; r.continuous = false;
        let finalText = "";
        r.onresult = (e) => {
            let interim = "";
            for (let i = 0; i < e.results.length; i++) {
                if (e.results[i].isFinal) finalText = e.results[i][0].transcript;
                else interim += e.results[i][0].transcript;
            }
            setHeard((finalText || interim).trim());
        };
        r.onerror = (e) => { if (e.error === "not-allowed") { setNote("Microphone blocked — allow it in the browser."); setPhase("paused"); } };
        r.onend = () => {
            recog.current = null;
            if (!open.current) return;
            const said = finalText.trim();
            if (said) {
                setPhase("thinking");
                pending.current = { before: lastReplyRef.current, sawBusy: false };
                send(said);
            } else setTimeout(() => open.current && phaseRef.current === "listening" && listen(), 250);
        };
        recog.current = r;
        try { r.start(); } catch { /* already started */ }
    };

    const speak = async (text) => {
        const plain = plainForSpeech(text);
        if (!plain || !open.current) return listen();
        setPhase("speaking");
        const done = () => { audio.current = null; if (open.current && phaseRef.current === "speaking") listen(); };
        try {
            const r = await fetch(`${API}/media/speech`, {
                method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({ text: plain }),
            });
            if (!r.ok) throw new Error();
            const d = await r.json();
            if (!open.current) return;
            const a = new Audio(`data:${d.mime};base64,${d.base64}`);
            audio.current = a; a.onended = done;
            await a.play();
        } catch {
            // Free fallback: the phone's own voice.
            if (!window.speechSynthesis || !open.current) return done();
            const u = new SpeechSynthesisUtterance(plain);
            u.lang = "en-ZA"; u.onend = done; u.onerror = done;
            window.speechSynthesis.speak(u);
        }
    };

    const phaseRef = useRef(phase); phaseRef.current = phase;
    const lastReplyRef = useRef(lastReply); lastReplyRef.current = lastReply;

    // Reply finished → read it out.
    useEffect(() => {
        const p = pending.current;
        if (!p) return;
        if (busy) { p.sawBusy = true; return; }
        if (p.sawBusy || lastReply !== p.before) {
            pending.current = null;
            if (lastReply && lastReply !== p.before) speak(lastReply);
            else listen();
        }
    }, [busy, lastReply]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        listen();
        return () => { open.current = false; recog.current?.abort(); stopSpeaking(); };
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const tapOrb = () => {
        if (phase === "speaking") { stopSpeaking(); listen(); }
        else if (phase === "paused") listen();
        else if (phase === "listening") recog.current?.stop();
    };
    const end = () => { open.current = false; recog.current?.abort(); stopSpeaking(); onClose(); };

    const label = { listening: heard ? "" : "Listening…", thinking: "Sem is working…", speaking: "Speaking — tap to interrupt", paused: "Tap to talk" }[phase];
    return (
        <div role="dialog" aria-label="Voice mode" style={{
            position: "fixed", left: 0, right: 0, bottom: 0, zIndex: 60, padding: "14px 16px 22px",
            background: "var(--surface)", borderTop: "1px solid var(--border)", borderRadius: "18px 18px 0 0",
            boxShadow: "0 -8px 28px rgba(0,0,0,0.22)", display: "flex", flexDirection: "column", alignItems: "center", gap: "10px",
        }}>
            <button onClick={tapOrb} aria-label={phase === "speaking" ? "Interrupt" : "Talk"} style={{
                width: "76px", height: "76px", borderRadius: "50%", border: "2px solid #f5b800", cursor: "pointer",
                background: "radial-gradient(circle at 35% 30%, #fff3b0, #ffcf33 45%, #c98a00)",
                animation: phase === "paused" ? "none" : `sem-orb ${phase === "listening" ? "1.1s" : phase === "speaking" ? "0.6s" : "1.8s"} ease-in-out infinite`,
                display: "flex", alignItems: "center", justifyContent: "center",
            }}>
                {phase === "thinking" ? <GoldS size={34} /> : <span style={{ fontSize: "30px", fontWeight: 800, color: "#5a3d00", fontFamily: "Georgia, serif" }}>S</span>}
            </button>
            <div style={{ minHeight: "20px", fontSize: "14px", color: heard && phase === "listening" ? "var(--text)" : "var(--text-muted)", textAlign: "center", maxWidth: "100%" }}>
                {note || (phase === "listening" && heard ? heard : label)}
            </div>
            <button onClick={end} className="btn-primary" style={{ border: "1px solid var(--gold, #c9a227)", borderRadius: "999px", padding: "6px 18px", fontSize: "13px", cursor: "pointer" }}>End voice</button>
        </div>
    );
}

// The composer button that opens voice mode: a gold sound-wave icon.
export function VoiceModeButton({ onClick, disabled }) {
    return (
        <button onClick={onClick} disabled={disabled} aria-label="Talk hands-free" title="Talk hands-free"
            style={{ width: "32px", height: "32px", flexShrink: 0, display: "flex", alignItems: "center", justifyContent: "center",
                     background: "none", border: "none", borderRadius: "50%", color: "var(--gold-text, #b8860b)", cursor: "pointer" }}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
                <path d="M4 10v4M8 7v10M12 4v16M16 7v10M20 10v4" />
            </svg>
        </button>
    );
}
