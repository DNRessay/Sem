import { useEffect, useRef, useState } from "react";
import AvatarStage from "./AvatarStage";
import { GoldS } from "./Working";
import { canRecord, recordUtterance, transcribe } from "../utils/recordWav";

const API = import.meta.env.VITE_API_URL || "";
const MAX_SPOKEN = 1200;
const LOOK_KEY = "semblance_voice_look"; // "avatar" | "orb"
const VOICE_KEY = "semblance_voice_engine"; // "natural" (Kokoro on the server, Gemini fallback) | "fast" (the phone's own voice)
const SILENCE_MS = 700; // end your turn after this much quiet, instead of the browser's slower default
const FIRST_MIN = 20;   // start talking at the first sentence this long…
const NEXT_MIN = 220;   // …then speak in bigger pieces (fewer TTS calls, fewer seams)

function saved(key, fallback) {
    try { return localStorage.getItem(key) || fallback; } catch { return fallback; }
}

export function plainForSpeech(text) {
    return (text || "").replace(/\[\[SEMBLANCE_TOOL:[^\]]*\]\]\n?/g, "")
        .replace(/```[\s\S]*?```/g, " I've put the code in the chat. ")
        .replace(/!\[[^\]]*\]\([^)]*\)/g, "").replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
        .replace(/[#*_`>|]/g, "").replace(/\s+/g, " ").trim();
}

// Where the next spoken piece of a still-growing reply can end: after a sentence, never inside a code block.
export function speakableCut(text, min) {
    if ((text.match(/```/g) || []).length % 2) text = text.slice(0, text.lastIndexOf("```"));
    let cut = 0;
    for (const m of text.matchAll(/[.!?](?=\s)|\n/g)) {
        cut = m.index + 1;
        if (cut >= min) break;
    }
    return cut >= min ? cut : 0;
}

// Hands-free conversation: listens, sends what you said when you pause, and
// reads Sem's reply out while it is still being written, then listens again.
// Natural voice: the server makes each sentence's audio while the reply streams and sends it in the same
// stream (pipeline/voice_stream.py). Fast voice: the phone reads the text itself.
// Tap the orb to cut Sem off and talk; End to stop. The chat keeps every turn.
export default function VoiceMode({ token, send, busy, lastReply, liveReply = "", onClose }) {
    const [phase, setPhase] = useState("listening"); // listening | thinking | speaking | paused
    const [heard, setHeard] = useState("");
    const [note, setNote] = useState("");
    const [look, setLook] = useState(() => saved(LOOK_KEY, "avatar"));
    const [engine, setEngine] = useState(() => saved(VOICE_KEY, "natural"));
    const [avatarBroken, setAvatarBroken] = useState(false);
    const avatar = useRef(null);
    const useAvatar = look === "avatar" && !avatarBroken;
    const choose = (key, set) => (v) => { set(v); try { localStorage.setItem(key, v); } catch { /* private mode */ } };
    const open = useRef(true);
    const recog = useRef(null);
    const audio = useRef(null);
    const ctx = useRef(null);
    const engineRef = useRef(engine); engineRef.current = engine;
    const [said, setSaid] = useState("");     // what Sem is saying (captions)
    // The reply being read out: how much of it is queued, the queue, and whether the reply is complete.
    const turn = useRef(null); // { before, sawBusy, consumed, spoken, final, queue, playing, gen, server, heard }
    const gen = useRef(0);
    const audioCtx = () => {
        if (!ctx.current) ctx.current = new (window.AudioContext || window.webkitAudioContext)();
        ctx.current.resume();
        return ctx.current;
    };

    const stopSpeaking = () => {
        gen.current += 1;
        try { audio.current?.stop(); } catch { /* already stopped */ }
        audio.current?.onended?.();
        audio.current = null;
        window.speechSynthesis?.cancel();
        avatar.current?.stop();
    };

    // What you said goes to Sem; nothing heard means listen again.
    const handleHeard = (text) => {
        if (!open.current) return;
        if (text) {
            setPhase("thinking"); setSaid("");
            const t = { before: lastReplyRef.current, sawBusy: false, consumed: 0, spoken: 0, final: false,
                        queue: [], playing: false, gen: gen.current,
                        server: engineRef.current === "natural", heard: 0 };
            turn.current = t;
            send(text, t.server ? { voice: true, onSpeech: ev => onSpeech(t, ev) } : {});
        } else setTimeout(() => open.current && phaseRef.current === "listening" && listen(), 250);
    };

    // No speech recognition in this browser: record what you say and Whistle (on the server) writes it down.
    const listenWithWhistle = () => {
        setPhase("listening"); setHeard(""); setNote("");
        const rec = recordUtterance({ silenceMs: SILENCE_MS });
        recog.current = rec;
        rec.done.then(async (wav) => {
            if (recog.current !== rec) return;
            recog.current = null;
            if (!open.current) return;
            if (!wav) { handleHeard(""); return; }
            setHeard("…");
            try { const text = await transcribe(token, wav); setHeard(text); handleHeard(text); }
            catch (e) { setNote(e.message); setPhase("paused"); }
        });
    };

    const listen = () => {
        if (!open.current) return;
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR && canRecord()) { listenWithWhistle(); return; }
        if (!SR) { setNote("Voice isn't supported in this browser — try Chrome."); setPhase("paused"); return; }
        setPhase("listening"); setHeard(""); setNote("");
        const r = new SR();
        r.lang = "en-ZA"; r.interimResults = true; r.continuous = false;
        let finalText = "", latest = "", quiet = null;
        r.onresult = (e) => {
            let interim = "";
            for (let i = 0; i < e.results.length; i++) {
                if (e.results[i].isFinal) finalText = e.results[i][0].transcript;
                else interim += e.results[i][0].transcript;
            }
            latest = (finalText || interim).trim();
            setHeard(latest);
            clearTimeout(quiet);
            quiet = setTimeout(() => recog.current === r && r.stop(), SILENCE_MS);
        };
        r.onerror = (e) => { if (e.error === "not-allowed") { setNote("Microphone blocked — allow it in the browser."); setPhase("paused"); } };
        r.onend = () => {
            clearTimeout(quiet);
            recog.current = null;
            handleHeard((finalText || latest).trim());
        };
        recog.current = r;
        try { r.start(); } catch { /* already started */ }
    };

    // A sentence's audio from the server: an S3 link (fetched now, while the previous piece plays) or inline.
    const loadAudio = async (sp) => {
        if (sp.base64) return { base64: sp.base64 };
        if (!sp.url) return null;
        try {
            const blob = await (await fetch(sp.url)).blob();
            return await new Promise(resolve => {
                const r = new FileReader();
                r.onload = () => resolve({ base64: String(r.result).split(",")[1] });
                r.onerror = () => resolve(null);
                r.readAsDataURL(blob);
            });
        } catch { return null; }
    };

    const onSpeech = (t, ev) => {
        if (t.gen !== gen.current || !open.current) return;
        if (ev.speech) {
            t.heard += 1;
            t.queue.push({ text: ev.speech.text, audio: loadAudio(ev.speech) });
            playQueue(t);
        }
    };

    const playPiece = async (text, wav, face) => {
        if (wav && face) {
            try { await face.speakAudio(wav.base64, text); } catch { /* carry on */ }
            return;
        }
        if (wav) {
            try {
                const ac = audioCtx();
                const bytes = Uint8Array.from(atob(wav.base64), c => c.charCodeAt(0));
                const src = ac.createBufferSource();
                src.buffer = await ac.decodeAudioData(bytes.buffer);
                src.connect(ac.destination);
                await new Promise(resolve => { src.onended = resolve; audio.current = src; src.start(); });
                audio.current = null;
                return;
            } catch { /* fall through to the phone voice */ }
        }
        if (!window.speechSynthesis) return;
        await new Promise(resolve => {
            const u = new SpeechSynthesisUtterance(text);
            u.lang = "en-ZA"; u.onend = resolve; u.onerror = resolve;
            window.speechSynthesis.speak(u);
            face?.mouthAlong(text, (text.split(/\s+/).length / 2.6) * 1000);
        });
    };

    const playQueue = async (t) => {
        if (t.playing) return;
        t.playing = true;
        const face = avatar.current?.ready() ? avatar.current : null;
        face?.mood("happy");
        while (t.queue.length && open.current && t.gen === gen.current) {
            const piece = t.queue.shift();
            setPhase("speaking");
            setSaid(s => (s ? `${s} ${piece.text}` : piece.text));
            const wav = await piece.audio;
            if (t.gen !== gen.current || !open.current) break;
            await playPiece(piece.text, wav, face);
        }
        t.playing = false;
        if (t.gen !== gen.current || !open.current) return;
        if (t.final && !t.queue.length) {
            face?.mood("neutral");
            turn.current = null;
            listen();
        } else if (!t.queue.length) setPhase("thinking");
    };

    // Queue whatever new, complete part of the reply is ready (all of it once the reply is done).
    const feed = (t, text) => {
        const fresh = text.slice(t.consumed);
        const cut = t.final ? fresh.length : speakableCut(fresh, t.consumed ? NEXT_MIN : FIRST_MIN);
        if (!cut) return;
        t.consumed += cut;
        let piece = plainForSpeech(fresh.slice(0, cut));
        if (!piece || t.spoken >= MAX_SPOKEN) return;
        if (t.spoken + piece.length > MAX_SPOKEN) piece = `${piece.slice(0, MAX_SPOKEN - t.spoken).replace(/[^.!?]*$/, "")} The rest is in the chat.`;
        t.spoken += piece.length;
        t.queue.push({ text: piece, audio: Promise.resolve(null) });
        playQueue(t);
    };

    const phaseRef = useRef(phase); phaseRef.current = phase;
    const lastReplyRef = useRef(lastReply); lastReplyRef.current = lastReply;

    // Read the reply out as it streams in, then whatever is left once it's complete.
    useEffect(() => {
        const t = turn.current;
        if (!t || t.final || t.gen !== gen.current) return;
        if (busy) {
            t.sawBusy = true;
            if (liveReply && !t.server) feed(t, liveReply);
            return;
        }
        if (!t.sawBusy && lastReply === t.before) return;
        t.final = true;
        const reply = lastReply !== t.before ? lastReply : liveReply;
        // The server spoke nothing (an error, or an old server): read it with the phone voice instead.
        if (t.server && !t.heard) t.server = false;
        if (reply && !t.server) feed(t, reply);
        if (!t.queue.length && !t.playing) { turn.current = null; listen(); }
    }, [busy, lastReply, liveReply]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        audioCtx();
        // Start Sem's voice server now (Kokoro takes a few seconds to load) so the first reply isn't slow.
        fetch(`${API}/media/voice/warm`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
        listen();
        return () => { open.current = false; recog.current?.abort(); stopSpeaking(); ctx.current?.close(); };
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const tapOrb = () => {
        avatar.current?.resume();
        audioCtx();
        if (phase === "speaking") { stopSpeaking(); turn.current = null; listen(); }
        else if (phase === "paused") listen();
        else if (phase === "listening") recog.current?.stop();
    };
    const pause = () => { recog.current?.abort(); stopSpeaking(); turn.current = null; setPhase("paused"); };
    const end = () => { open.current = false; recog.current?.abort(); stopSpeaking(); onClose(); };

    const label = { listening: heard ? "" : "Listening…", thinking: "Sem is working…", speaking: "Tap to interrupt", paused: "Paused — tap to talk" }[phase];
    const pill = (active) => ({ border: "1px solid var(--border)", borderRadius: "999px", padding: "4px 12px", cursor: "pointer", fontSize: "12px",
                                background: "transparent", color: active ? "var(--text)" : "var(--text-muted)" });
    return (
        <div role="dialog" aria-label="Voice mode" style={{
            position: "fixed", inset: 0, zIndex: 100, background: "var(--bg)", display: "flex", flexDirection: "column",
            padding: "max(12px, env(safe-area-inset-top)) 16px max(20px, env(safe-area-inset-bottom))", boxSizing: "border-box",
        }}>
            <div style={{ display: "flex", alignItems: "center", gap: "6px", flexWrap: "wrap" }}>
                <span style={{ fontWeight: 700, fontSize: "15px", color: "var(--text)" }}>Sem voice</span>
                <span style={{ flex: 1 }} />
                {["natural", "fast"].map(v => (
                    <button key={v} onClick={() => choose(VOICE_KEY, setEngine)(v)} className={engine === v ? "is-selected" : ""} style={pill(engine === v)}
                        title={v === "fast" ? "The phone's own voice: starts instantly" : "Sem's voice (Kokoro): natural and quick; Gemini if it's down"}>
                        {v === "natural" ? "Natural" : "Fast"}
                    </button>
                ))}
                {["avatar", "orb"].map(l => (
                    <button key={l} onClick={() => choose(LOOK_KEY, setLook)(l)} className={look === l ? "is-selected" : ""} style={pill(look === l)}>
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
