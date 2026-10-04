import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

const AVATAR_URL = "https://cdn.jsdelivr.net/gh/met4citizen/TalkingHead@1.7/avatars/brunette.glb";
const TALKINGHEAD = "talkinghead"; // resolved by the import map in index.html

// Even word timings across the audio, weighted by word length — good enough
// lip-sync for TTS that doesn't return timestamps (Gemini, the phone voice).
function timings(text, ms) {
    const words = text.split(/\s+/).filter(Boolean);
    const weights = words.map(w => w.length + 2);
    const total = weights.reduce((a, b) => a + b, 0) || 1;
    let t = 0;
    const wtimes = [], wdurations = [];
    for (const w of weights) {
        const d = (w / total) * ms;
        wtimes.push(t); wdurations.push(d * 0.9); t += d;
    }
    return { words, wtimes, wdurations };
}

// The 3D talking avatar from AvaTa (TalkingHead, three.js) inside Sem.
// speakAudio(base64Wav, text) lip-syncs to real audio; mouthAlong(text, ms)
// moves the lips over silence while the phone's own voice talks.
const AvatarStage = forwardRef(function AvatarStage({ onFail, height = 300 }, ref) {
    const box = useRef(null);
    const head = useRef(null);
    const acting = useRef(null);
    const [progress, setProgress] = useState(0);
    const [ready, setReady] = useState(false);

    useEffect(() => {
        let dead = false;
        (async () => {
            try {
                const { TalkingHead } = await import(/* @vite-ignore */ TALKINGHEAD);
                if (dead) return;
                const h = new TalkingHead(box.current, {
                    ttsEndpoint: "N/A", lipsyncModules: ["en"], cameraView: "upper", mixerGainSpeech: 3,
                    cameraRotateEnable: false, cameraZoomEnable: false, cameraPanEnable: false,
                });
                await h.showAvatar({ url: AVATAR_URL, body: "F", avatarMood: "neutral", lipsyncLang: "en" },
                    ev => ev.lengthComputable && setProgress(Math.round((100 * ev.loaded) / ev.total)));
                if (dead) { h.stop?.(); return; }
                head.current = h;
                setReady(true);
            } catch (e) {
                console.error("avatar failed", e);
                if (!dead) onFail?.(String(e));
            }
        })();
        return () => { dead = true; clearInterval(acting.current); head.current?.stop?.(); };
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const playBuffer = async (buffer, text) => {
        const h = head.current;
        await h.audioCtx.resume();
        h.speakAudio({ audio: buffer, ...timings(text, buffer.duration * 1000) });
        await new Promise(r => setTimeout(r, buffer.duration * 1000 + 60));
    };

    useImperativeHandle(ref, () => ({
        ready: () => !!head.current,
        resume: () => head.current?.audioCtx.resume(),
        mood: (m) => head.current?.setMood(m),
        gesture: (g) => head.current?.playGesture(g, 2.5),
        stop: () => head.current?.stopSpeaking(),
        // Acts out what Sem is doing while it works (WorkProps shows the prop): eyes down on the laptop, book or
        // paper, looking around while it searches, up while thinking. act(null) looks back at you.
        act(kind) {
            const h = head.current;
            clearInterval(acting.current);
            acting.current = null;
            if (!h) return;
            const safe = fn => { try { fn(); } catch { /* older TalkingHead: skip that move */ } };
            const w = box.current?.clientWidth || 300, ht = box.current?.clientHeight || 300;
            if (!kind) { safe(() => h.setMood("neutral")); safe(() => h.makeEyeContact?.(800)); return; }
            // Eyes only (no hand gestures): down at the laptop, book or paper, glancing around while searching,
            // up and to the side while thinking. The head-scratch itself is the 🤔 in WorkProps.
            const look = (x, y, ms) => safe(() => h.lookAt?.(w * x, ht * y, ms));
            const moves = {
                laptop: () => (Math.random() < 0.5 ? look(0.5, 1.1, 1300) : look(Math.random(), 0.2 + Math.random() * 0.5, 1100)),
                book: () => look(0.35 + Math.random() * 0.3, 1.05, 1500),
                newspaper: () => look(0.3 + Math.random() * 0.4, 0.9, 1500),
                paint: () => look(0.7, 1.0, 1200),
                thinking: () => look(Math.random() < 0.5 ? 0.15 : 0.85, -0.2, 1600),
            };
            safe(() => h.setMood(kind === "thinking" ? "neutral" : "happy"));
            const move = moves[kind] || moves.thinking;
            move();
            acting.current = setInterval(move, 2600);
        },
        async speakAudio(base64, text) {
            const h = head.current;
            const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
            const buffer = await h.audioCtx.decodeAudioData(bytes.buffer);
            await playBuffer(buffer, text);
        },
        async mouthAlong(text, ms) {
            const h = head.current;
            const buffer = h.audioCtx.createBuffer(1, Math.max(1, Math.round((ms / 1000) * 22050)), 22050);
            await playBuffer(buffer, text);
        },
    }), []); // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div style={{ position: "relative", width: "100%", height: `${height}px` }}>
            <div ref={box} style={{ width: "100%", height: "100%" }} />
            {!ready && (
                <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center",
                              fontSize: "13px", color: "var(--text-muted)" }}>
                    Loading avatar{progress ? ` ${progress}%` : "…"}
                </div>
            )}
        </div>
    );
});

export default AvatarStage;
