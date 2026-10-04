import { useEffect, useRef, useState } from "react";
import { SendIcon } from "./Icons";

const API = import.meta.env.VITE_API_URL || "";
const MAX_VIDEOS = 20;
const FORMATS = [
    ["short", "Short", "9:16 · Reels, TikTok, Shorts", [5, 10, 15, 30]],
    ["long", "Long", "16:9 · YouTube", [15, 30, 45, 60]],
    ["square", "Square", "1:1 · Feed", [5, 10, 15, 30]],
];
const ASPECT = { short: "9:16", long: "16:9", square: "1:1" };
const CLIP_MINUTES = 10; // one 5-second Wan clip on the L4
const CLIP_USD = 0.13;
const FAST_MINUTES = 2; // fast mode (CausVid LoRA): ~6 steps instead of 50
const FAST_USD = 0.03;
const FAST_KEY = "semblance_video_fast";
const cost = (n, fast) => ({ minutes: n * (fast ? FAST_MINUTES : CLIP_MINUTES), usd: n * (fast ? FAST_USD : CLIP_USD) });
const VOICES = ["Kore", "Puck", "Charon", "Aoede", "Fenrir", "Leda"];
const IDEAS = ["A 15-second Reel for our weekend bread special", "A 60-second YouTube intro to what we do and why",
    "Behind the scenes: a day at the shop"];
const fmt = id => FORMATS.find(f => f[0] === id) || FORMATS[0];
const scenesFor = seconds => Math.max(1, Math.ceil(seconds / 5));
const alive = url => { try { return Number(new URL(url).searchParams.get("exp")) * 1000 > Date.now(); } catch { return true; } };

async function call(path, headers, body, method = "POST") {
    const r = await fetch(`${API}${path}`, { method, headers, ...(body ? { body: JSON.stringify(body) } : {}) });
    const d = await r.json().catch(() => ({}));
    if (r.status === 401) { const e = new Error("unauthorized"); e.unauthorized = true; throw e; }
    if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : `Failed (${r.status})`);
    return d;
}

function Player({ url, aspect, title }) {
    const [gone, setGone] = useState(!alive(url));
    if (gone) return <div className="ds-muted">This video expired (kept 7 days).</div>;
    return (
        <div style={{ maxWidth: aspect === "16:9" ? "640px" : aspect === "1:1" ? "420px" : "320px" }}>
            <video src={url} controls playsInline preload="metadata" onError={() => setGone(true)}
                style={{ width: "100%", borderRadius: "12px", background: "#000", display: "block" }} />
            <div className="ds-actions">
                <a className="ds-btn sm" href={url} download={`${(title || "semblance-video").replace(/[^\w-]+/g, "-")}.mp4`} target="_blank" rel="noreferrer">Download</a>
                <span className="ds-muted">Kept for 7 days</span>
            </div>
        </div>
    );
}

// One video in the chat: the idea, then its storyboard (editable), then the render and the finished video.
function VideoTurn({ turn, update, onRender, onReplan, onRetryScene, onRejoin, busy }) {
    const plan = turn.plan;
    const project = turn.project;
    const [, tick] = useState(0);
    const rendering = project && ["rendering", "joining"].includes(project.status);
    useEffect(() => {
        if (!rendering) return;
        const t = setInterval(() => tick(x => x + 1), 10000);
        return () => clearInterval(t);
    }, [rendering]);
    const setScene = (i, patch) => update({ plan: { ...plan, scenes: plan.scenes.map((s, j) => (j === i ? { ...s, ...patch } : s)) } });
    const done = project ? project.scenes.filter(s => s.status === "done").length : 0;
    const total = project ? project.scenes.length : 0;
    const minutes = Math.max(0, Math.floor((Date.now() / 1000 - (project?.created || Date.now() / 1000)) / 60));
    const [, label, sub] = fmt(turn.format);
    return (
        <>
            <div className="ds-user">
                {turn.idea}
                <div className="ds-tags">
                    <span className="ds-tag">{label} · {turn.seconds}s · {sub.split(" · ")[0]}</span>
                    {turn.voiceover && <span className="ds-tag">Voiceover · {turn.voice}</span>}
                    <span className="ds-tag">{turn.fast ? "⚡ Fast" : "Full quality"}</span>
                </div>
            </div>
            <div className="ds-sem">
                <div className="ds-avatar">S</div>
                <div className="ds-sem-body">
                    {turn.status === "planning" && <div className="ds-status"><span className="ds-spin" />Writing the storyboard…</div>}
                    {turn.error && <div className="msg-error" style={{ margin: 0 }}>{turn.error}</div>}

                    {plan && !project && (
                        <div className="ds-card"><div className="ds-card-body" style={{ paddingTop: "14px" }}>
                            <div className="ds-kicker">Storyboard{plan.title ? ` · ${plan.title}` : ""}</div>
                            {plan.style && <div className="ds-muted">Look: {plan.style}</div>}
                            {plan.scenes.map((s, i) => (
                                <div key={i} style={{ display: "flex", flexDirection: "column", gap: "4px" }}>
                                    <div className="ds-muted">Scene {i + 1} · {i * 5}–{i * 5 + 5}s</div>
                                    <textarea className="ds-field" rows={2} value={s.prompt} disabled={busy}
                                        onChange={e => setScene(i, { prompt: e.target.value })} aria-label={`Scene ${i + 1} shot`} />
                                    {turn.voiceover && (
                                        <input className="ds-field" value={s.narration || ""} disabled={busy} placeholder="Voiceover for this scene"
                                            onChange={e => setScene(i, { narration: e.target.value })} aria-label={`Scene ${i + 1} voiceover`} />
                                    )}
                                </div>
                            ))}
                            <div className="ds-actions">
                                <button className="ds-btn btn-primary" onClick={onRender} disabled={busy}>
                                    ▶ Render{turn.fast ? " ⚡" : ""} · ~{cost(plan.scenes.length, turn.fast).minutes} min · ~${cost(plan.scenes.length, turn.fast).usd.toFixed(2)}
                                </button>
                                <button className="ds-btn sm" onClick={onReplan} disabled={busy}>↻ New storyboard</button>
                            </div>
                            <div className="ds-muted">Each scene is a 5-second clip rendered one after another on one GPU. Edit any shot before rendering.</div>
                        </div></div>
                    )}

                    {project && rendering && (
                        <div style={{ maxWidth: "420px", display: "flex", flexDirection: "column", gap: "6px" }}>
                            <div className="ds-status"><span className="ds-spin" />
                                {project.status === "joining" ? "Joining the scenes" + (project.audio_url ? " and adding the voiceover…" : "…") + (project.join_stage ? ` (${project.join_stage})` : "")
                                    : `Rendering scene ${Math.min(done + 1, total)} of ${total} · ${minutes} min`}
                            </div>
                            <div className="ds-progress"><div style={{ width: `${Math.max(3, ((done + (project.status === "joining" ? 0.5 : 0)) / total) * 100)}%` }} /></div>
                            <div className="ds-muted">About {Math.max(1, (total - done) * (project.fast ? FAST_MINUTES : CLIP_MINUTES))} min left. You can leave — it finishes and saves here.</div>
                            {project.note && <div className="ds-muted">{project.note}</div>}
                        </div>
                    )}
                    {project?.status === "scene_failed" && (
                        <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                            {project.scenes.map((s, i) => s.status === "failed" && (
                                <div key={i} className="ds-actions">
                                    <span className="msg-error" style={{ margin: 0 }}>Scene {i + 1} failed: {s.error || "render error"}</span>
                                    <button className="ds-btn sm" onClick={() => onRetryScene(i)} disabled={busy}>↻ Render it again</button>
                                </div>
                            ))}
                        </div>
                    )}
                    {project?.status === "failed" && (
                        <div className="ds-actions">
                            <span className="msg-error" style={{ margin: 0 }}>{project.error || "The video failed"}</span>
                            {project.scenes?.every(s => s.status === "done") &&
                                <button className="ds-btn sm" onClick={onRejoin} disabled={busy}>↻ Retry join</button>}
                        </div>
                    )}
                    {project?.status === "done" && project.url && (
                        <>
                            <Player url={project.url} aspect={project.aspect_ratio} title={project.title} />
                            {turn.voiceover && !project.voice && <div className="ds-muted">{project.note || "No voiceover this time."}</div>}
                            <div className="ds-actions"><button className="ds-btn sm" onClick={onReplan} disabled={busy}>↻ Make another version</button></div>
                        </>
                    )}
                </div>
            </div>
        </>
    );
}

// Video tab: short-form (Reels/TikTok/Shorts) and long-form (YouTube) videos. Sem writes a storyboard of 5-second
// scenes in one look, you edit it, then every scene renders on Modal (Wan 2.1) and they're joined into one video,
// with a Gemini voiceover read over it if you want one.
export default function VideoStudio({ headers, chat, updateChat, brief, model, onUnauthorized, top, idea, setIdea, onRendered }) {
    const turns = chat.videos || [];
    const [format, setFormat] = useState(() => chat.videoFormat || "short");
    const [seconds, setSeconds] = useState(15);
    const [voiceover, setVoiceover] = useState(true);
    const [voice, setVoice] = useState("Kore");
    const [fast, setFastState] = useState(() => { try { return localStorage.getItem(FAST_KEY) !== "0"; } catch { return true; } });
    const setFast = v => { setFastState(v); try { localStorage.setItem(FAST_KEY, v ? "1" : "0"); } catch { /* private mode */ } };
    const [budget, setBudget] = useState(null);
    const [busy, setBusy] = useState(false);
    const scroller = useRef(null);
    const box = useRef(null);
    const chatsRef = useRef(chat);
    chatsRef.current = chat;

    const setTurns = (chatId, fn) => updateChat(chatId, c => ({ videos: fn(c.videos || []).slice(-MAX_VIDEOS) }));
    const setTurn = (chatId, id, patch) => setTurns(chatId, list => list.map(t => (t.id === id ? { ...t, ...(typeof patch === "function" ? patch(t) : patch) } : t)));
    const fail = e => { if (e.unauthorized) onUnauthorized(); return e.message; };

    const loadBudget = () => fetch(`${API}/design/video/budget`, { headers }).then(r => r.json()).then(d => d.ok && setBudget(d)).catch(() => {});
    useEffect(() => { loadBudget(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
    useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: "smooth" }); }, [chat.id, turns.length]);
    useEffect(() => {
        const el = box.current;
        if (el) { el.style.height = "auto"; el.style.height = `${Math.min(160, el.scrollHeight)}px`; }
    }, [idea]);
    useEffect(() => { // lengths differ per format
        const lengths = fmt(format)[3];
        if (!lengths.includes(seconds)) setSeconds(lengths[Math.min(2, lengths.length - 1)]);
    }, [format]); // eslint-disable-line react-hooks/exhaustive-deps

    // Renders run on the server; poll the ones in progress (any chat) until they're done.
    useEffect(() => {
        const check = async () => {
            const c = chatsRef.current;
            for (const t of c.videos || []) {
                if (!t.project || !["rendering", "joining"].includes(t.project.status)) continue;
                try {
                    const p = await call(`/design/video/project/${t.project.id}`, headers, null, "GET");
                    setTurn(c.id, t.id, { project: p });
                    if (p.status === "done") onRendered?.();
                } catch (e) { if (e.unauthorized) { onUnauthorized(); return; } }
            }
        };
        check();
        const timer = setInterval(check, 15000);
        return () => clearInterval(timer);
    }, [chat.id]); // eslint-disable-line react-hooks/exhaustive-deps

    const planFor = async (chatId, turn) => {
        setTurn(chatId, turn.id, { status: "planning", error: "", plan: null, project: null });
        try {
            const plan = await call("/design/video/plan", headers, { brief, idea: turn.idea, seconds: turn.seconds, format: turn.format,
                voiceover: turn.voiceover, model });
            setTurn(chatId, turn.id, { status: "planned", plan });
        } catch (e) { setTurn(chatId, turn.id, { status: "error", error: fail(e) }); }
    };

    const send = () => {
        const text = idea.trim();
        if (!text || busy) return;
        setIdea("");
        const turn = { id: Math.random().toString(36).slice(2, 10), idea: text, format, seconds, voiceover, voice, fast, created: Date.now() };
        updateChat(chat.id, c => ({ title: c.title || text.slice(0, 60), videoFormat: format, videos: [...(c.videos || []), turn].slice(-MAX_VIDEOS) }));
        planFor(chat.id, turn);
    };

    const render = async turn => {
        setBusy(true);
        setTurn(chat.id, turn.id, { error: "" });
        try {
            const project = await call("/design/video/project", headers, {
                title: turn.plan.title, style: turn.plan.style, scenes: turn.plan.scenes, aspect_ratio: turn.plan.aspect_ratio || ASPECT[turn.format],
                format: turn.format, voiceover: turn.voiceover, voice: turn.voice, fast: !!turn.fast, chat_id: chat.id,
            });
            setTurn(chat.id, turn.id, { status: "rendering", project });
            loadBudget();
        } catch (e) { setTurn(chat.id, turn.id, { error: fail(e) }); } finally { setBusy(false); }
    };

    const retryScene = async (turn, index) => {
        setBusy(true);
        try {
            const project = await call(`/design/video/project/${turn.project.id}/scene/${index}`, headers, {});
            setTurn(chat.id, turn.id, { project, error: "" });
        } catch (e) { setTurn(chat.id, turn.id, { error: fail(e) }); } finally { setBusy(false); }
    };

    const rejoin = async turn => {
        setBusy(true);
        try {
            const project = await call(`/design/video/project/${turn.project.id}/join`, headers, {});
            setTurn(chat.id, turn.id, { status: "rendering", project, error: "" });
        } catch (e) { setTurn(chat.id, turn.id, { error: fail(e) }); } finally { setBusy(false); }
    };

    const [, , , lengths] = fmt(format);
    const n = scenesFor(seconds);
    return (<>
        <div className="ds-feed" ref={scroller}>
            <div className="ds-col">
                {top}
                {!turns.length && (
                    <div className="ds-empty">
                        <h2>What's the video about?</h2>
                        <div className="ds-muted" style={{ marginBottom: "14px" }}>
                            Pick short or long below. Sem writes a storyboard of 5-second scenes, you tweak it, then it renders and joins them into one video, with a voiceover if you want.
                        </div>
                        <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", justifyContent: "center" }}>
                            {IDEAS.map(s => <button key={s} className="ds-chip" onClick={() => setIdea(s)}>{s}</button>)}
                        </div>
                    </div>
                )}
                {turns.map(t => (
                    <VideoTurn key={t.id} turn={t} busy={busy} update={patch => setTurn(chat.id, t.id, patch)}
                        onRender={() => render(t)} onReplan={() => planFor(chat.id, t)} onRetryScene={i => retryScene(t, i)} onRejoin={() => rejoin(t)} />
                ))}
            </div>
        </div>
        <div className="ds-composer">
            <div className="ds-composer-box">
                <textarea ref={box} rows={1} value={idea} onChange={e => setIdea(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && window.matchMedia("(pointer: fine)").matches) { e.preventDefault(); send(); } }}
                    placeholder={format === "long" ? "What's the video about? e.g. A 60-second intro to our bakery for YouTube" : "What's the video about? e.g. Weekend special Reel: 2 loaves for R80"} />
                <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                    <div className="ds-seg" role="tablist" aria-label="Format">
                        {FORMATS.map(([id, name, sub]) => (
                            <button key={id} role="tab" aria-selected={format === id} title={sub} onClick={() => setFormat(id)}>{name}</button>
                        ))}
                    </div>
                    <div className="ds-chips" style={{ flex: 1, minWidth: 0 }}>
                        {lengths.map(s => (
                            <button key={s} onClick={() => setSeconds(s)} aria-pressed={seconds === s}
                                className={`ds-chip${seconds === s ? " is-selected" : ""}`}>{s}s</button>
                        ))}
                        <button onClick={() => setFast(!fast)} aria-pressed={fast} className={`ds-chip${fast ? " is-selected" : ""}`}
                            title="Fast: ~2 min a scene instead of ~10. Turn off if the motion looks worse.">⚡ Fast</button>
                        <button onClick={() => setVoiceover(v => !v)} aria-pressed={voiceover} className={`ds-chip${voiceover ? " is-selected" : ""}`}>🎙 Voiceover</button>
                        {voiceover && (
                            <select className="ds-chip" value={voice} onChange={e => setVoice(e.target.value)} aria-label="Voice">
                                {VOICES.map(v => <option key={v} value={v}>{v}</option>)}
                            </select>
                        )}
                    </div>
                    <button className="ds-send btn-primary" onClick={send} disabled={!idea.trim() || busy} aria-label="Write the storyboard" style={{ border: "none" }}><SendIcon size={18} /></button>
                </div>
                <div className="ds-muted" style={{ padding: "0 4px 4px" }}>
                    {fmt(format)[2]} · {n} scene{n > 1 ? "s" : ""} · ~{cost(n, fast).minutes} min to render · ~${cost(n, fast).usd.toFixed(2)}{fast ? " (fast)" : ""}
                    {budget && ` · $${Number(budget.used_usd).toFixed(2)} of $${Number(budget.cap_usd).toFixed(2)} used this month`}
                </div>
            </div>
        </div>
    </>);
}
