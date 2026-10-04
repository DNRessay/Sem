import { useEffect, useRef, useState } from "react";
import { SendIcon } from "./Icons";

const API = import.meta.env.VITE_API_URL || "";
const MAX_TRACKS = 20;
const LENGTHS = [10, 20, 30, 47];
const IDEAS = ["Upbeat Amapiano instrumental, 112 BPM, log drums, shakers, warm piano chords",
    "Dark cinematic ambient for a premium teaser, 70 BPM, deep synth pads, soft piano, rising shimmer",
    "Bright acoustic background for a bakery ad, 100 BPM, ukulele, claps, light percussion"];
const alive = url => { try { return Number(new URL(url).searchParams.get("exp")) * 1000 > Date.now(); } catch { return true; } };

async function call(path, headers, body, method = "POST") {
    const r = await fetch(`${API}${path}`, { method, headers, ...(body ? { body: JSON.stringify(body) } : {}) });
    const d = await r.json().catch(() => ({}));
    if (r.status === 401) { const e = new Error("unauthorized"); e.unauthorized = true; throw e; }
    if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : `Failed (${r.status})`);
    return d;
}

function Track({ track }) {
    const [gone, setGone] = useState(track.url && !alive(track.url));
    return (
        <>
            <div className="ds-user">
                {track.prompt}
                <div className="ds-tags"><span className="ds-tag">🎵 {track.seconds}s</span></div>
            </div>
            <div className="ds-sem">
                <div className="ds-avatar">S</div>
                <div className="ds-sem-body">
                    {track.status === "rendering" && <div className="ds-status"><span className="ds-spin" />Composing… usually under a minute (longer if the GPU is waking up)</div>}
                    {track.status === "failed" && <div className="msg-error" style={{ margin: 0 }}>{track.error || "The track failed"}</div>}
                    {track.status === "done" && track.url && (gone ? <div className="ds-muted">This track expired (kept 7 days).</div> : (
                        <div style={{ maxWidth: "460px" }}>
                            <audio src={track.url} controls preload="metadata" onError={() => setGone(true)} style={{ width: "100%" }} />
                            <div className="ds-actions">
                                <a className="ds-btn sm" href={track.url} download="semblance-music.wav" target="_blank" rel="noreferrer">Download</a>
                                <span className="ds-muted">Kept for 7 days</span>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </>
    );
}

// Music tab: instrumental tracks for videos, reels and ads (Stable Audio Open on Modal, a few cents each).
export default function MusicStudio({ headers, chat, updateChat, onUnauthorized, top }) {
    const [prompt, setPrompt] = useState("");
    const [seconds, setSeconds] = useState(30);
    const [error, setError] = useState("");
    const tracks = chat.music || [];
    const chatsRef = useRef(chat);
    chatsRef.current = chat;
    const scroller = useRef(null);
    const setTrack = (chatId, id, patch) => updateChat(chatId, c => ({ music: (c.music || []).map(t => (t.id === id ? { ...t, ...patch } : t)) }));

    useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" }); }, [tracks.length]);

    // Tracks render on the server; check the unfinished ones until they're done.
    useEffect(() => {
        const check = async () => {
            const c = chatsRef.current;
            for (const t of c.music || []) {
                if (t.status !== "rendering" || !t.job_id) continue;
                try {
                    const d = await call(`/design/music/${t.job_id}`, headers, null, "GET");
                    if (d.status !== "rendering") setTrack(c.id, t.id, d);
                } catch (e) { if (e.unauthorized) { onUnauthorized(); return; } }
            }
        };
        check();
        const timer = setInterval(check, 8000);
        return () => clearInterval(timer);
    }, [chat.id]); // eslint-disable-line react-hooks/exhaustive-deps

    const send = async () => {
        const text = prompt.trim();
        if (!text) return;
        setPrompt(""); setError("");
        const id = Math.random().toString(36).slice(2, 10);
        updateChat(chat.id, c => ({ title: c.title || text.slice(0, 60),
            music: [...(c.music || []), { id, prompt: text, seconds, status: "rendering", created: Date.now() }].slice(-MAX_TRACKS) }));
        try {
            const d = await call("/design/music", headers, { prompt: text, seconds });
            setTrack(chat.id, id, { job_id: d.job_id, seconds: d.seconds });
        } catch (e) {
            if (e.unauthorized) { onUnauthorized(); return; }
            setTrack(chat.id, id, { status: "failed", error: e.message });
        }
    };

    return (<>
        <div className="ds-feed" ref={scroller}>
            <div className="ds-col">
                {top}
                {!tracks.length && (
                    <div className="ds-empty">
                        <h2>What should it sound like?</h2>
                        <div className="ds-muted" style={{ marginBottom: "14px" }}>
                            Describe the genre, mood, tempo and instruments. Instrumental only (no singing) — for videos, reels and ads.
                        </div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", justifyContent: "center" }}>
                            {IDEAS.map(s => <button key={s} className="ds-chip" style={{ whiteSpace: "normal", textAlign: "left" }} onClick={() => setPrompt(s)}>{s}</button>)}
                        </div>
                    </div>
                )}
                {tracks.map(t => <Track key={t.id} track={t} />)}
                {error && <div className="msg-error">{error}</div>}
            </div>
        </div>
        <div className="ds-composer">
            <div className="ds-composer-box">
                <textarea rows={1} value={prompt} onChange={e => setPrompt(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && window.matchMedia("(pointer: fine)").matches) { e.preventDefault(); send(); } }}
                    placeholder="e.g. Chill lo-fi hip hop, 85 BPM, soft piano, vinyl crackle, mellow drums" />
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <div className="ds-chips" style={{ flex: 1, minWidth: 0 }}>
                        {LENGTHS.map(s => (
                            <button key={s} onClick={() => setSeconds(s)} aria-pressed={seconds === s}
                                className={`ds-chip${seconds === s ? " is-selected" : ""}`}>{s}s</button>
                        ))}
                    </div>
                    <button className="ds-send btn-primary" onClick={send} disabled={!prompt.trim()} aria-label="Make the track" style={{ border: "none" }}><SendIcon size={18} /></button>
                </div>
            </div>
        </div>
    </>);
}
