import { useEffect, useRef, useState } from "react";
import AvatarStage from "./AvatarStage";
import { GoldS } from "./Working";

const API = import.meta.env.VITE_API_URL || "";
const MAX_SPOKEN = 1200;
const LOOK_KEY = "semblance_voice_look"; // "avatar" | "orb"

function savedLook() {
    try { return localStorage.getItem(LOOK_KEY) || "avatar"; } catch { return "avatar"; }
}

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
    const [look, setLook] = useState(savedLook);
    const [avatarBroken, setAvatarBroken] = useState(false);
    const avatar = useRef(null);
    const useAvatar = look === "avatar" && !avatarBroken;
    const chooseLook = (l) => { setLook(l); try { localStorage.setItem(LOOK_KEY, l); } catch { /* private mode */ } };
    const open = useRef(true);
    const recog = useRef(null);
    const audio = useRef(null);
    const pending = useRef(null); // { before, sawBusy }
    const ctx = useRef(null);
    const [said, setSaid] = useState("");     // what Sem is saying (captions)
    const audioCtx = () => {
        if (!ctx.current) ctx.current = new (window.AudioContext || window.webkitAudioContext)();
        ctx.current.resume();
        return ctx.current;
    };

    const stopSpeaking = () => {
        try { audio.current?.stop(); } catch { /* already stopped */ }
        audio.current = null;
        window.speechSynthesis?.cancel();
        avatar.current?.stop();
    };

    const listen = () => {
        if (!open.current) return;
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) { setNote("Voice isn't supported in this browser — try Chrome."); setPhase("paused"); return; }
        setPhase("listening"); setHeard(""); setNote("");
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
            // (paused: stays quiet until you tap)
        };
        recog.current = r;
        try { r.start(); } catch { /* already started */ }
    };

    const speak = async (text) => {
        const plain = plainForSpeech(text);
        if (!plain || !open.current) return listen();
        setPhase("speaking");
        setSaid(plain);
        const face = avatar.current?.ready() ? avatar.current : null;
        face?.mood("happy");
        const done = () => {
            audio.current = null; face?.mood("neutral");
            if (open.current && phaseRef.current === "speaking") listen();
        };
        let wav = null;
        try {
            const r = await fetch(`${API}/media/speech`, {
                method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
                body: JSON.stringify({ text: plain }),
            });
            if (r.ok) wav = await r.json();
        } catch { /* fall through to the phone voice */ }
        if (!open.current) return;
        if (wav && face) {
            // The avatar plays the audio itself so its lips follow it.
            try { await face.speakAudio(wav.base64, plain); } catch { /* still carry on listening */ }
            return done();
        }
        if (wav) {
            try {
                const ac = audioCtx();
                const bytes = Uint8Array.from(atob(wav.base64), c => c.charCodeAt(0));
                const src = ac.createBufferSource();
                src.buffer = await ac.decodeAudioData(bytes.buffer);
                src.connect(ac.destination);
                src.onended = done;
                audio.current = src;
                src.start();
                return;
            } catch { /* fall through to the phone voice */ }
        }
        // Free fallback: the phone's own voice (the avatar mouths along).
        if (!window.speechSynthesis) return done();
        const u = new SpeechSynthesisUtterance(plain);
        u.lang = "en-ZA"; u.onend = done; u.onerror = done;
        window.speechSynthesis.speak(u);
        face?.mouthAlong(plain, (plain.split(/\s+/).length / 2.6) * 1000);
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
        audioCtx();
        listen();
        return () => { open.current = false; recog.current?.abort(); stopSpeaking(); ctx.current?.close(); };
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const tapOrb = () => {
        avatar.current?.resume();
        audioCtx();
        if (phase === "speaking") { stopSpeaking(); listen(); }
        else if (phase === "paused") listen();
        else if (phase === "listening") recog.current?.stop();
    };
    const pause = () => { recog.current?.abort(); stopSpeaking(); setPhase("paused"); };
    const end = () => { open.current = false; recog.current?.abort(); stopSpeaking(); onClose(); };

    const label = { listening: heard ? "" : "Listening…", thinking: "Sem is working…", speaking: "Tap to interrupt", paused: "Paused — tap to talk" }[phase];
    const pill = (active) => ({ border: "1px solid var(--border)", borderRadius: "999px", padding: "4px 12px", cursor: "pointer", fontSize: "12px",
                                background: "transparent", color: active ? "var(--text)" : "var(--text-muted)" });
    return (
        <div role="dialog" aria-label="Voice mode" style={{
            position: "fixed", inset: 0, zIndex: 100, background: "var(--bg)", display: "flex", flexDirection: "column",
            padding: "max(12px, env(safe-area-inset-top)) 16px max(20px, env(safe-area-inset-bottom))", boxSizing: "border-box",
        }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                <span style={{ fontWeight: 700, fontSize: "15px", color: "var(--text)" }}>Sem voice</span>
                <span style={{ flex: 1 }} />
                {["avatar", "orb"].map(l => (
                    <button key={l} onClick={() => chooseLook(l)} className={look === l ? "is-selected" : ""} style={pill(look === l)}>
                        {l === "avatar" ? "Avatar" : "Orb"}
                    </button>
                ))}
                <button onClick={end} aria-label="Close voice mode" style={{ background: "none", border: "none", fontSize: "22px", color: "var(--text-muted)", cursor: "pointer", padding: "0 4px" }}>×</button>
            </div>
            {avatarBroken && look === "avatar" && <div style={{ fontSize: "12px", color: "var(--text-muted)", textAlign: "center", marginTop: "6px" }}>The avatar can't run on this device — using the orb.</div>}

            <div onClick={tapOrb} style={{ flex: 1, minHeight: 0, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", position: "relative" }}>
                {useAvatar ? (
                    <div style={{ width: "100%", maxWidth: "520px" }}>
                        <AvatarStage ref={avatar} height={Math.round(window.innerHeight * 0.58)} onFail={() => setAvatarBroken(true)} />
                    </div>
                ) : (
                    <div aria-label={phase === "speaking" ? "Interrupt" : "Talk"} style={{
                        width: "160px", height: "160px", borderRadius: "50%", border: "3px solid #f5b800",
                        background: "radial-gradient(circle at 35% 30%, #fff3b0, #ffcf33 45%, #c98a00)",
                        animation: phase === "paused" ? "none" : `sem-orb ${phase === "listening" ? "1.1s" : phase === "speaking" ? "0.6s" : "1.8s"} ease-in-out infinite`,
                        display: "flex", alignItems: "center", justifyContent: "center",
                    }}>
                        {phase === "thinking" ? <GoldS size={70} /> : <span style={{ fontSize: "64px", fontWeight: 800, color: "#5a3d00", fontFamily: "Georgia, serif" }}>S</span>}
                    </div>
                )}
                {useAvatar && phase === "thinking" && <div style={{ position: "absolute", top: "8px" }}><GoldS size={30} /></div>}
            </div>

            <div style={{ minHeight: "64px", maxHeight: "22vh", overflowY: "auto", textAlign: "center", padding: "0 6px", fontSize: "16px", lineHeight: 1.5,
                          color: phase === "speaking" || (phase === "listening" && heard) ? "var(--text)" : "var(--text-muted)" }}>
                {note || (phase === "speaking" ? said : phase === "listening" && heard ? heard : label)}
            </div>

            <div style={{ display: "flex", justifyContent: "center", gap: "12px", marginTop: "12px" }}>
                <button onClick={phase === "paused" ? listen : pause} style={{ ...pill(true), padding: "10px 20px", fontSize: "14px" }}>
                    {phase === "paused" ? "Resume" : "Pause"}
                </button>
                <button onClick={end} style={{ border: "none", borderRadius: "999px", padding: "10px 24px", fontSize: "14px", cursor: "pointer",
                                               background: "var(--danger)", color: "#fff", fontWeight: 600 }}>End</button>
            </div>
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
