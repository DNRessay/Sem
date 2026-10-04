import { useEffect, useRef, useState } from "react";
import ModelPicker, { loadModel } from "./ModelPicker";
import { runStream, useResumeRun } from "../utils/runs";
import { copyToClipboard } from "../utils/clipboard";
import { HeaderStatus } from "./StatusBar";
import AgentFeedPanel from "./AgentFeedPanel";
import useAgentFeed from "../hooks/useAgentFeed";
import TabDrawer, { MenuButton } from "./TabDrawer";
import useTabChats, { newId } from "../hooks/useTabChats";
import WebStudio from "./WebStudio";
import VideoStudio from "./VideoStudio";
import MusicStudio from "./MusicStudio";
import ImproveButton from "./ImproveButton";
import { CloseIcon, PaperclipIcon, SendIcon } from "./Icons";

const API = import.meta.env.VITE_API_URL || "";
const STORE_KEY = "semblance_design_campaigns";
const MODE_KEY = "semblance_design_mode"; // "ads" (the Images tab) | "video" | "music" | "web"
const OLD_KEY = "semblance_design";
const MAX_TURNS = 30;
const MAX_REFS = 4;
const RENDER_SECONDS = 600; // a typical Wan render, for the progress bar
// Each platform gets its own look, caption, hashtags and search words (pipeline/ad_studio.py PLAYBOOK).
const PLACEMENTS = [
    ["instagram", "Instagram", "Scroll-stopping, beautiful photos people save — no text on the image"],
    ["facebook", "Facebook", "Clear, informative page posts and boosted ads: the offer, why it's good value, what to do"],
    ["pinterest", "Pinterest", "Tall, clickable pins with a bold title and keyword-rich description"],
    ["linkedin", "LinkedIn", "Professional, credible images and insight-led posts"],
    ["story", "Stories & Status", "Instagram/Facebook Stories and WhatsApp Status"],
    ["tiktok", "TikTok photo", "TikTok is mostly video (use the Video tab); this makes a photo post"],
    ["google_display", "Google Display", "Wide web banners"],
];
const ALIASES = { fb_ig_feed: "instagram", square: "facebook", story_reel: "story", whatsapp_status: "story" };
const platform = id => ALIASES[id] || id;
const ASPECTS = [["9:16", "9:16 Reel"], ["16:9", "16:9 YouTube"], ["1:1", "1:1 Feed"]];
const SUGGESTIONS = ["Weekend special: 2 loaves for R80, ends Sunday", "Grand opening — first 50 customers get 20% off",
    "Book a free consultation this month"];
const placementLabel = id => (PLACEMENTS.find(p => p[0] === platform(id)) || [])[1] || id;
const keepLinks = list => (list || []).map(({ image, ...x }) => (image?.url ? { ...x, image } : x));
// Saved images/videos are links (kept 7 days in S3); older or unsaved ones are inline base64.
export const mediaSrc = m => m?.url || (m?.base64 ? `data:${m.mime};base64,${m.base64}` : "");
const EXPIRED = "Image expired (kept 7 days) — tap New image";
const linkAlive = url => { try { return Number(new URL(url).searchParams.get("exp")) * 1000 > Date.now(); } catch { return true; } };

function loadSaved() {
    try { return JSON.parse(localStorage.getItem(OLD_KEY)) || {}; } catch { return {}; }
}

function canvasJpeg(source, w, h) {
    const scale = Math.min(1, 1024 / Math.max(w, h));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(w * scale); canvas.height = Math.round(h * scale);
    canvas.getContext("2d").drawImage(source, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.85).split(",")[1];
}

function imageToRef(file) {
    return new Promise((resolve, reject) => {
        const url = URL.createObjectURL(file);
        const img = new Image();
        img.onload = () => { resolve([{ mime: "image/jpeg", base64: canvasJpeg(img, img.naturalWidth, img.naturalHeight), name: file.name }]); URL.revokeObjectURL(url); };
        img.onerror = () => { reject(new Error(`Couldn't read ${file.name}`)); URL.revokeObjectURL(url); };
        img.src = url;
    });
}

// A video becomes three still frames (start, middle, end) — enough to read its look.
function videoToRefs(file) {
    return new Promise((resolve, reject) => {
        const url = URL.createObjectURL(file);
        const v = document.createElement("video");
        v.muted = true; v.preload = "auto"; v.src = url;
        const frames = [];
        const fail = () => { reject(new Error(`Couldn't read ${file.name} — try an MP4 or a screenshot of it`)); URL.revokeObjectURL(url); };
        const timer = setTimeout(fail, 20000); // some phone videos never decode in the browser
        v.onerror = () => { clearTimeout(timer); fail(); };
        v.onloadedmetadata = () => {
            const times = [0.1, 0.5, 0.85].map(f => f * (v.duration || 1));
            const next = () => {
                if (!times.length) { clearTimeout(timer); resolve(frames); URL.revokeObjectURL(url); return; }
                v.currentTime = times.shift();
            };
            v.onseeked = () => { frames.push({ mime: "image/jpeg", base64: canvasJpeg(v, v.videoWidth, v.videoHeight), name: `${file.name} @${Math.round(v.currentTime)}s` }); next(); };
            next();
        };
    });
}

// The old single-list save becomes the first round, so earlier ads aren't lost.
function withTurns(c) {
    if (Array.isArray(c.turns)) return c;
    const ads = c.ads || [];
    return { ...c, ads: [], turns: ads.length ? [{ id: "t0", kind: "ads", campaign: c.campaign || "", placements: c.placements || [],
        count: c.count, ads, style: c.style, status: "done", created: c.updated || Date.now() }] : [] };
}

// Vicinic customer sites (DNRessay/Digital over MCP): pick one to fill the business brief.
function VicinicPicker({ headers, onBrief, disabled }) {
    const [state, setState] = useState(null); // {connected, sites}
    const [slug, setSlug] = useState("");
    const [form, setForm] = useState({ url: "", key: "" });
    const [msg, setMsg] = useState("");
    const load = () => fetch(`${API}/design/vicinic/sites`, { headers }).then(r => r.json())
        .then(d => setState(d)).catch(() => setState({ connected: false, sites: [] }));
    useEffect(() => { load(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const connect = async () => {
        setMsg("Connecting…");
        const r = await fetch(`${API}/design/vicinic/connect`, { method: "POST", headers, body: JSON.stringify(form) });
        const d = await r.json().catch(() => ({}));
        setMsg(r.ok ? `Connected — ${d.tools.length} tools (also available in Co-work and Code).` : (d.detail || `Failed (${r.status})`));
        if (r.ok) load();
    };
    const use = async () => {
        setMsg("Reading the site…");
        const r = await fetch(`${API}/design/vicinic/brief/${encodeURIComponent(slug)}`, { headers });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { setMsg(d.detail || `Failed (${r.status})`); return; }
        onBrief(d);
        setMsg("");
    };

    if (!state) return null;
    if (!state.connected) return (
        <details className="ds-muted">
            <summary style={{ cursor: "pointer" }}>Connect Vicinic (use a customer site's details)</summary>
            <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginTop: "6px" }}>
                <input className="ds-field" value={form.url} onChange={e => setForm({ ...form, url: e.target.value })} placeholder="https://… Vicinic backend address" />
                <input className="ds-field" value={form.key} onChange={e => setForm({ ...form, key: e.target.value })} placeholder="vic_… key (Vicinic Admin → Connect apps)" type="password" />
                <button className="ds-btn" onClick={connect} disabled={!form.url || !form.key} style={{ alignSelf: "flex-start" }}>Connect</button>
                {msg && <div>{msg}</div>}
            </div>
        </details>
    );
    return (
        <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
            <select className="ds-field" value={slug} onChange={e => setSlug(e.target.value)} style={{ flex: 1, minWidth: "160px" }}>
                <option value="">Vicinic customer site…</option>
                {state.sites.map(x => <option key={x.slug} value={x.slug}>{x.name} ({x.package})</option>)}
            </select>
            <button className="ds-btn" onClick={use} disabled={!slug || disabled}>Use its details</button>
            {msg && <div className="ds-muted" style={{ width: "100%" }}>{msg}</div>}
        </div>
    );
}

// The business everything is made for: collapsed to one line once there's a brief.
function BusinessCard({ chat, setSite, setBrief, setArea, headers, model, onUnauthorized, disabled }) {
    const { site = "", brief = "", area = "" } = chat;
    const [open, setOpen] = useState(!brief);
    const [busy, setBusy] = useState("");
    const [notice, setNotice] = useState("");
    useEffect(() => { setOpen(!chat.brief); setNotice(""); }, [chat.id]); // eslint-disable-line react-hooks/exhaustive-deps

    const learn = async () => {
        setBusy("Reading your website…"); setNotice("");
        try {
            const r = await fetch(`${API}/design/brief`, { method: "POST", headers, body: JSON.stringify({ url: site, model }) });
            if (r.status === 401) { onUnauthorized(); return; }
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || `Failed (${r.status})`);
            setBrief(d.brief);
            setNotice(`Read ${d.pages_read} page${d.pages_read === 1 ? "" : "s"} from ${d.url}. Edit the brief if anything's off.`);
        } catch (e) { setNotice(e.message); }
        setBusy("");
    };

    return (
        <div className="ds-card" style={!brief ? { borderColor: "var(--gold)" } : undefined}>
            <div className="ds-card-head" onClick={() => setOpen(o => !o)}>
                <div style={{ flex: 1, minWidth: 0 }}>
                    <div className="ds-kicker">Your business</div>
                    <div style={{ fontSize: "14px", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis", color: brief ? "var(--text)" : "var(--text-muted)" }}>
                        {brief ? (site ? `${site} · ` : "") + brief.split("\n")[0] : "Tell Sem about the business first — or point it at the website"}
                    </div>
                </div>
                <span className="ds-muted">{open ? "Hide" : "Edit"}</span>
            </div>
            {open && (
                <div className="ds-card-body">
                    <div style={{ display: "flex", gap: "8px" }}>
                        <input className="ds-field" value={site} onChange={e => setSite(e.target.value)} placeholder="yourwebsite.co.za" style={{ flex: 1 }} />
                        <button className="ds-btn" onClick={learn} disabled={!site.trim() || !!busy || disabled}>{busy ? <span className="ds-spin" /> : null}Learn from site</button>
                    </div>
                    <VicinicPicker headers={headers} disabled={disabled} onBrief={d => {
                        setBrief([d.brief, d.phone && `Phone: ${d.phone}`, d.whatsapp && `WhatsApp: ${d.whatsapp}`,
                            d.primary_color && `Brand colour: ${d.primary_color}`].filter(Boolean).join("\n"));
                        if (d.domain) setSite(d.domain);
                        setNotice(`Using ${d.slug}'s details from Vicinic. Edit anything that's off.`);
                    }} />
                    <textarea className="ds-field" value={brief} onChange={e => setBrief(e.target.value)} rows={brief ? 7 : 3}
                        placeholder="Or describe the business: what you sell, who to, where, your tone…" />
                    <input className="ds-field" value={area} onChange={e => setArea(e.target.value)}
                        placeholder="Area to target, e.g. Soweto, Johannesburg (goes into captions, hashtags and search words)" />
                    {(busy || notice) && <div className="ds-muted">{busy || notice}</div>}
                </div>
            )}
        </div>
    );
}

function AdCard({ ad, onRetry, onExpired }) {
    const caption = ad.caption || ad.primary_text || "";
    const tags = (ad.hashtags || []).join(" ");
    const text = [ad.headline && platform(ad.placement) !== "instagram" ? ad.headline : "", caption, tags].filter(Boolean).join("\n\n");
    const waiting = !ad.image && !ad.imageError;
    return (
        <div className="ds-ad">
            <div className="ds-ad-media" style={{ aspectRatio: !ad.image ? (ad.aspect_ratio || "1:1").replace(":", "/") : undefined, minHeight: ad.image ? 0 : undefined }}>
                {ad.image ? (
                    <img src={mediaSrc(ad.image)} alt={ad.alt_text || ad.headline} onError={onExpired} />
                ) : waiting ? (
                    <><div className="ds-shimmer" /><span className="ds-muted">Making image…</span></>
                ) : (
                    <span style={{ fontSize: "12px", padding: "16px", textAlign: "center", color: /limit|not kept|expired|skipped/i.test(ad.imageError) ? "var(--warning)" : "var(--danger)" }}>{ad.imageError}</span>
                )}
                <span className="ds-badge">{placementLabel(ad.placement)}</span>
            </div>
            <div className="ds-ad-body">
                {ad.angle && <div className="ds-kicker" style={{ letterSpacing: "0.5px" }}>{ad.angle}</div>}
                {ad.headline && <div style={{ fontWeight: 700, fontSize: "15px", lineHeight: 1.3 }}>{ad.headline}</div>}
                <div style={{ fontSize: "14px", lineHeight: 1.5, whiteSpace: "pre-wrap" }}>{caption}</div>
                {tags && <div style={{ fontSize: "13px", color: "var(--gold)", lineHeight: 1.5 }}>{tags}</div>}
                {ad.cta && <span className="ds-cta">{ad.cta}</span>}
                {(ad.keywords?.length > 0 || ad.alt_text) && (
                    <details className="ds-muted"><summary style={{ cursor: "pointer" }}>Search words & alt text</summary>
                        {ad.keywords?.length > 0 && <div style={{ marginTop: "4px" }}>People searching: {ad.keywords.join(" · ")}</div>}
                        {ad.alt_text && <div style={{ marginTop: "4px" }}>Alt text: {ad.alt_text}</div>}
                    </details>
                )}
                <span style={{ flex: 1 }} />
                <div className="ds-actions">
                    <button className="ds-btn sm" onClick={() => copyToClipboard(text)}>Copy post</button>
                    {tags && <button className="ds-btn sm" onClick={() => copyToClipboard(tags)}>Copy hashtags</button>}
                    {ad.image && <a className="ds-btn sm" href={mediaSrc(ad.image)} download={`ad-${ad.placement}.png`} target="_blank" rel="noreferrer">Download</a>}
                    <button className="ds-btn sm" onClick={onRetry} disabled={waiting}>New image</button>
                </div>
            </div>
        </div>
    );
}

function AdsTurn({ turn, onRetry, onExpired, onAgain, onVideo, onBuild, disabled }) {
    const working = turn.status === "working";
    return (
        <>
            <div className="ds-user">
                {turn.campaign}
                <div className="ds-tags">
                    {(turn.placements || []).map(p => <span key={p} className="ds-tag">{placementLabel(p)}</span>)}
                    {turn.count > 1 && <span className="ds-tag">{turn.count} each</span>}
                    {turn.refs > 0 && <span className="ds-tag">{turn.refs} inspiration</span>}
                </div>
            </div>
            <div className="ds-sem">
                <div className="ds-avatar">S</div>
                <div className="ds-sem-body">
                    {working && <div className="ds-status"><span className="ds-spin" />{turn.statusText || "Working…"}</div>}
                    {turn.style && (
                        <details className="ds-muted"><summary style={{ cursor: "pointer" }}>Style Sem picked up from your inspiration</summary>
                            <div style={{ whiteSpace: "pre-wrap", marginTop: "4px" }}>{turn.style}</div></details>
                    )}
                    {turn.error && <div className="msg-error" style={{ margin: 0 }}>{turn.error}</div>}
                    {turn.ads?.length > 0 && (
                        <div className="ds-grid">
                            {turn.ads.map((ad, i) => <AdCard key={i} ad={ad} onRetry={() => onRetry(i)} onExpired={() => onExpired(i)} />)}
                        </div>
                    )}
                    {!working && (
                        <div className="ds-actions">
                            <button className="ds-btn sm" onClick={onAgain} disabled={disabled}>↻ Generate again</button>
                            {turn.ads?.length > 0 && <button className="ds-btn sm" onClick={onVideo}>▶ Make a video of this</button>}
                            {turn.ads?.length > 0 && onBuild && <button className="ds-btn sm" onClick={onBuild}>Build it with Code →</button>}
                        </div>
                    )}
                </div>
            </div>
        </>
    );
}

function VideoPlayer({ video, onGone }) {
    return (
        <div style={{ maxWidth: video.aspect_ratio === "16:9" ? "560px" : "320px" }}>
            <video src={mediaSrc(video)} controls playsInline preload="metadata" onError={onGone}
                style={{ width: "100%", borderRadius: "14px", background: "#000", display: "block" }} />
            <div className="ds-actions" style={{ marginTop: "6px" }}>
                <a className="ds-btn sm" href={mediaSrc(video)} download="semblance-video-ad.mp4" target="_blank" rel="noreferrer">Download</a>
                {video.url && <span className="ds-muted">Kept for 7 days</span>}
            </div>
        </div>
    );
}

function VideoTurn({ turn, onAgain, onGone, disabled }) {
    const [, tick] = useState(0);
    const rendering = turn.status === "rendering";
    useEffect(() => {
        if (!rendering) return;
        const t = setInterval(() => tick(x => x + 1), 5000);
        return () => clearInterval(t);
    }, [rendering]);
    const elapsed = Math.max(0, (Date.now() - (turn.created || Date.now())) / 1000);
    return (
        <>
            <div className="ds-user">
                {turn.prompt}
                <div className="ds-tags"><span className="ds-tag">Video · {turn.aspect_ratio}</span></div>
            </div>
            <div className="ds-sem">
                <div className="ds-avatar">S</div>
                <div className="ds-sem-body">
                    {rendering && (
                        <div style={{ maxWidth: "360px", display: "flex", flexDirection: "column", gap: "6px" }}>
                            <div className="ds-status"><span className="ds-spin" />Rendering on the GPU · {Math.floor(elapsed / 60)} min</div>
                            <div className="ds-progress"><div style={{ width: `${Math.min(95, (elapsed / RENDER_SECONDS) * 100)}%` }} /></div>
                            <div className="ds-muted">Usually 5–10 minutes. You can leave — it's saved here when it's done.</div>
                        </div>
                    )}
                    {turn.status === "done" && turn.video && <VideoPlayer video={{ ...turn.video, aspect_ratio: turn.aspect_ratio }} onGone={onGone} />}
                    {turn.status === "done" && turn.gpu_seconds > 0 && <div className="ds-muted">{Math.round(turn.gpu_seconds / 60)} min of GPU time</div>}
                    {turn.status === "failed" && (
                        <>
                            <div className="msg-error" style={{ margin: 0 }}>{turn.error || "Render failed"}</div>
                            <div className="ds-actions"><button className="ds-btn sm" onClick={onAgain} disabled={disabled}>↻ Try again</button></div>
                        </>
                    )}
                </div>
            </div>
        </>
    );
}

// Every render from the last 7 days (kept on the server), wherever it was started.
function VideoLibrary({ videos, onClose }) {
    return (
        <div className="ds-sheet" onClick={onClose}>
            <div onClick={e => e.stopPropagation()}>
                <div style={{ display: "flex", alignItems: "center", padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                    <span style={{ fontWeight: 700, flex: 1 }}>Your videos</span>
                    <button onClick={onClose} aria-label="Close" style={{ background: "none", border: "none", cursor: "pointer", color: "var(--text)" }}><CloseIcon size={20} /></button>
                </div>
                <div style={{ flex: 1, overflowY: "auto", padding: "14px 16px", display: "flex", flexDirection: "column", gap: "18px" }}>
                    {!videos.length && <div className="ds-muted">No videos in the last 7 days.</div>}
                    {videos.map(v => (
                        <div key={v.job_id} style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                            <div style={{ fontSize: "13px" }}>{v.prompt}</div>
                            <div className="ds-muted">{v.created ? new Date(v.created * 1000).toLocaleString() : ""} · {v.aspect_ratio}</div>
                            {v.url ? <VideoPlayer video={v} /> : v.status === "failed"
                                ? <div className="msg-error" style={{ margin: 0 }}>{v.error || "Render failed"}</div>
                                : <div className="ds-status"><span className="ds-spin" />Rendering…</div>}
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}

function Composer({ kind, draft, setDraft, onSend, disabled, placements, togglePlacement, count, setCount,
                    aspect, setAspect, refs, setRefs, budget, improve }) {
    const [error, setError] = useState("");
    const box = useRef(null);
    useEffect(() => {
        const el = box.current;
        if (el) { el.style.height = "auto"; el.style.height = `${Math.min(160, el.scrollHeight)}px`; }
    }, [draft]);
    const addRefs = async (files) => {
        setError("");
        try {
            let added = [];
            for (const f of files) added = added.concat(f.type.startsWith("video/") ? await videoToRefs(f) : await imageToRef(f));
            setRefs(r => [...r, ...added].slice(0, MAX_REFS));
            if (refs.length + added.length > MAX_REFS) setError(`Kept the first ${MAX_REFS} — that's all the image model takes.`);
        } catch (e) { setError(e.message); }
    };
    const ready = draft.trim() && !disabled && (kind === "video" || placements.length);
    return (
        <div className="ds-composer">
            <div className="ds-composer-box">
                {kind === "ads" && refs.length > 0 && (
                    <div style={{ display: "flex", gap: "8px", padding: "6px 4px 0" }}>
                        {refs.map((r, i) => (
                            <div key={i} className="ds-thumb">
                                <img src={`data:${r.mime};base64,${r.base64}`} alt={r.name} title={r.name} />
                                <button onClick={() => setRefs(x => x.filter((_, j) => j !== i))} aria-label="Remove">✕</button>
                            </div>
                        ))}
                    </div>
                )}
                <textarea ref={box} rows={1} value={draft} onChange={e => setDraft(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && window.matchMedia("(pointer: fine)").matches) { e.preventDefault(); if (ready) onSend(); } }}
                    placeholder={kind === "ads" ? "What's the post about? e.g. Free website check for Soweto businesses this month" : "Describe a 5-second clip, e.g. Slow close-up of steaming sourdough, warm morning light"} />
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <div className="ds-chips" style={{ flex: 1, minWidth: 0 }}>
                        {kind === "ads" ? (<>
                            {PLACEMENTS.map(([id, name, hint]) => (
                                <button key={id} title={hint} onClick={() => togglePlacement(id)} aria-pressed={placements.includes(id)}
                                    className={`ds-chip${placements.includes(id) ? " is-selected" : ""}`}>{name}</button>
                            ))}
                            <select className="ds-chip" value={count} onChange={e => setCount(Number(e.target.value))} aria-label="Posts per platform">
                                {[1, 2, 3].map(n => <option key={n} value={n}>{n} each</option>)}
                            </select>
                        </>) : (<>
                            {ASPECTS.map(([id, name]) => (
                                <button key={id} onClick={() => setAspect(id)} aria-pressed={aspect === id}
                                    className={`ds-chip${aspect === id ? " is-selected" : ""}`}>{name}</button>
                            ))}
                            {budget && <span className="ds-muted" style={{ alignSelf: "center", whiteSpace: "nowrap" }}>${Number(budget.used_usd).toFixed(2)} / ${Number(budget.cap_usd).toFixed(2)} this month</span>}
                        </>)}
                    </div>
                    {kind === "ads" && improve && (
                        <ImproveButton {...improve} kind="images" text={draft} setText={setDraft} disabled={disabled} onError={setError} />
                    )}
                    {kind === "ads" && refs.length < MAX_REFS && (
                        <label className="ds-send" title="Inspiration: ads, photos or a video whose look Sem should copy" style={{ color: "var(--text-muted)" }}>
                            <PaperclipIcon size={18} />
                            <input type="file" accept="image/*,video/*" multiple disabled={disabled} style={{ display: "none" }}
                                onChange={e => { addRefs([...e.target.files]); e.target.value = ""; }} />
                        </label>
                    )}
                    <button className="ds-send btn-primary" onClick={onSend} disabled={!ready} aria-label="Send" style={{ border: "none" }}><SendIcon size={18} /></button>
                </div>
            </div>
            {error && <div className="ds-muted" style={{ color: "var(--danger)", maxWidth: "920px", margin: "6px auto 0" }}>{error}</div>}
        </div>
    );
}

// Design tab: digital-marketing assistant as a chat. Learns the business from its own website, then each
// message is a round of ads (copy + Nano Banana images per placement) or a video ad (Wan 2.1 on Modal, capped).
// Every round stays in the chat, so earlier ads are never lost when a new one fails.
export default function DesignPage({ token, onNavigate, onUnauthorized, handoff, onHandoff }) {
    const { chats, chat: rawChat, updateChat, newChat, selectChat, deleteChat } = useTabChats(STORE_KEY, {
        blank: () => ({ site: "", brief: "", area: "", placements: ["instagram", "facebook"], count: 2, turns: [] }),
        legacy: () => { const s = loadSaved(); return { ...s, title: (s.campaign || "").slice(0, 60) }; },
        // Saved images are short links and stay with the chat; inline (unsaved) ones are too big for the phone.
        persist: c => ({
            ...c,
            turns: (c.turns || []).map(t => (t.kind !== "ads" ? t : { ...t, ads: (t.ads || []).map(({ image, ...ad }) => (
                image?.url ? { ...ad, image } : image ? { ...ad, imageError: "Image not kept — tap New image" } : ad)) })),
            ...(c.web ? { web: { ...c.web, logos: keepLinks(c.web.logos),
                ...(c.web.figma ? { figma: { ...c.web.figma, frames: (c.web.figma.frames || []).filter(f => f.url) } } : {}) } } : {}),
        }),
    });
    const chat = withTurns(rawChat);
    const { site = "", brief = "", area = "", count = 2, turns } = chat;
    const placements = [...new Set((chat.placements || []).map(platform))].filter(id => PLACEMENTS.some(p => p[0] === id));
    const set = (key, v) => updateChat(chat.id, c => ({ [key]: typeof v === "function" ? v(c[key]) : v }));
    const [menuOpen, setMenuOpen] = useState(false);
    const feed = useAgentFeed(`design:${chat.id}`, token);
    const [feedOpen, setFeedOpen] = useState(false);
    // Inspiration images stay in memory only (too big for phone storage); the style text they produced is saved.
    const [refs, setRefs] = useState([]);
    const [draft, setDraft] = useState("");
    const [aspect, setAspect] = useState("9:16");
    const [budget, setBudget] = useState(null);
    const [library, setLibrary] = useState(null); // null = closed
    const [videos, setVideos] = useState([]);
    const [model, setModel] = useState(() => loadModel("semblance_design_model"));
    const [busy, setBusy] = useState(""); // Web mode's running step
    const [notice, setNotice] = useState("");
    const [mode, setModeState] = useState(() => { try { const m = localStorage.getItem(MODE_KEY); return ["web", "video", "music"].includes(m) ? m : "ads"; } catch { return "ads"; } });
    const [videoIdea, setVideoIdea] = useState("");
    const setMode = m => { setModeState(m); setNotice(""); try { localStorage.setItem(MODE_KEY, m); } catch { /* private mode */ } };
    const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
    const scroller = useRef(null);
    const chatsRef = useRef(chats);
    chatsRef.current = chats;
    const references = refs.map(({ mime, base64 }) => ({ mime, base64 }));
    const working = turns.some(t => t.kind === "ads" && t.status === "working");

    const setTurn = (chatId, turnId, fn) => updateChat(chatId, c => ({
        turns: withTurns(c).turns.map(t => (t.id === turnId ? { ...t, ...(typeof fn === "function" ? fn(t) : fn) } : t)),
    }));
    const addTurn = (chatId, turn, extra = {}) => updateChat(chatId, c => ({
        ...withTurns(c), ...extra, turns: [...withTurns(c).turns, turn].slice(-MAX_TURNS),
    }));

    // Switching chats: migrate an old save, and mark a round that died with the page (no run to resume) as interrupted.
    useEffect(() => {
        setRefs([]); setDraft(""); setNotice("");
        const stuck = turns.some(t => t.kind === "ads" && t.status === "working" && chat.pendingRun?.turnId !== t.id);
        if (!Array.isArray(rawChat.turns) || stuck) updateChat(chat.id, c => ({
            ...withTurns(c),
            turns: withTurns(c).turns.map(t => (t.kind === "ads" && t.status === "working" && c.pendingRun?.turnId !== t.id
                ? { ...t, status: "error", error: t.error || "Interrupted before it finished — tap Generate again" } : t)),
        }));
    }, [chat.id]); // eslint-disable-line react-hooks/exhaustive-deps

    const takenHandoff = useRef(0);
    useEffect(() => {
        if (handoff?.view !== "design" || takenHandoff.current === handoff.at) return;
        takenHandoff.current = handoff.at;
        newChat({ site, brief, placements, count, title: handoff.task.slice(0, 60) });
        setMode("ads");
        setTimeout(() => setDraft(handoff.task), 0);
    }, [handoff]); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        const el = scroller.current;
        if (el) el.scrollTop = el.scrollHeight;
    }, [chat.id, turns.length, mode]);

    // ── Videos: renders are tracked on the server, so they finish into S3 even when nobody's watching ──
    const loadVideos = () => fetch(`${API}/design/videos`, { headers }).then(r => (r.ok ? r.json() : null))
        .then(d => d && setVideos(d.videos || [])).catch(() => {});
    useEffect(() => {
        fetch(`${API}/design/video/budget`, { headers }).then(r => r.json()).then(d => d.ok && setBudget(d)).catch(() => {});
        loadVideos();
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        const inFlight = new Set();
        const check = async () => {
            for (const c of chatsRef.current) {
                for (const t of c.turns || []) {
                    if (t.kind !== "video" || t.status !== "rendering" || !t.jobId || inFlight.has(t.jobId)) continue;
                    inFlight.add(t.jobId);
                    try {
                        const r = await fetch(`${API}/design/video/${t.jobId}`, { headers });
                        const d = await r.json().catch(() => ({}));
                        if (d.status === "done") {
                            setTurn(c.id, t.id, { status: "done", gpu_seconds: d.gpu_seconds,
                                video: d.url ? { url: d.url, mime: d.mime } : { mime: d.mime, base64: d.base64 } });
                            loadVideos();
                        } else if (d.status === "failed" || (!r.ok && r.status !== 401 && r.status < 500)) {
                            setTurn(c.id, t.id, { status: "failed", error: d.error || d.detail || "Render failed" });
                        }
                    } catch { /* offline: next round */ }
                    inFlight.delete(t.jobId);
                }
            }
        };
        check();
        const timer = setInterval(check, 10000);
        return () => clearInterval(timer);
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const renderVideo = async (prompt, ratio) => {
        const chatId = chat.id;
        const turnId = newId();
        addTurn(chatId, { id: turnId, kind: "video", prompt, aspect_ratio: ratio, status: "rendering", created: Date.now() },
            { title: chat.title || prompt.slice(0, 60) });
        try {
            const r = await fetch(`${API}/design/video`, { method: "POST", headers, body: JSON.stringify({ prompt, aspect_ratio: ratio, chat_id: chatId }) });
            if (r.status === 401) { onUnauthorized(); return; }
            const d = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(d.detail || `Failed (${r.status})`);
            setTurn(chatId, turnId, { jobId: d.job_id, created: Date.now() });
            setBudget({ used_usd: d.used_usd, cap_usd: d.cap_usd });
            loadVideos();
        } catch (e) { setTurn(chatId, turnId, { status: "failed", error: e.message }); }
    };

    // ── Ads: each send is a new round; events land in that round only ──
    const applyEvent = (chatId, turnId, ev) => {
        if (ev.type === "status") setTurn(chatId, turnId, { statusText: ev.text });
        else if (ev.type === "style") { setTurn(chatId, turnId, { style: ev.text }); updateChat(chatId, () => ({ style: ev.text })); }
        else if (ev.type === "variants") setTurn(chatId, turnId, { ads: ev.variants, statusText: "Making images…" });
        else if (ev.type === "image") setTurn(chatId, turnId, t => ({ ads: (t.ads || []).map((ad, i) => (i === ev.index
            ? { ...ad, image: ev.url ? { mime: ev.mime, url: ev.url } : { mime: ev.mime, base64: ev.base64 }, imageError: "" } : ad)) }));
        else if (ev.type === "image_error") setTurn(chatId, turnId, t => ({ ads: (t.ads || []).map((ad, i) => (i === ev.index ? { ...ad, imageError: ev.error } : ad)) }));
        else if (ev.type === "error") setTurn(chatId, turnId, { error: ev.text });
    };
    const finishAds = (chatId, turnId, error) => {
        updateChat(chatId, () => ({ pendingRun: null }));
        setTurn(chatId, turnId, t => ({
            status: "done", statusText: "", error: error || t.error || "",
            ads: (t.ads || []).map(ad => (ad.image || ad.imageError ? ad : { ...ad, imageError: "Skipped (image limit reached) — tap New image later" })),
        }));
    };
    useResumeRun(chat.id, chat.pendingRun, {
        headers, apply: ev => applyEvent(chat.id, chat.pendingRun.turnId, ev),
        onStart: () => setTurn(chat.id, chat.pendingRun.turnId, { ads: [], status: "working", statusText: "Picking your ads back up…" }),
        done: () => finishAds(chat.id, chat.pendingRun?.turnId),
    });

    const createAds = async (campaign, opts = {}) => {
        const chatId = chat.id;
        const turnId = newId();
        const round = { placements: opts.placements || placements, count: opts.count || count };
        addTurn(chatId, { id: turnId, kind: "ads", campaign, ...round, refs: refs.length, ads: [], status: "working",
            statusText: refs.length ? "Studying your inspiration…" : "Writing ads…", created: Date.now() },
            { title: chat.title || campaign.slice(0, 60) });
        let error = "";
        try {
            const r = await runStream("/design/ads", {
                headers, body: { brief, campaign, ...round, area, model, references, chat_id: chatId },
                onEvent: ev => applyEvent(chatId, turnId, ev),
                onRun: (id, seq) => seq === 0 && updateChat(chatId, () => ({ pendingRun: { id, seq: 0, turnId } })),
            });
            if (r.status === 401) { onUnauthorized(); return; }
            if (r.error) error = r.error;
        } catch (e) { error = e.message; }
        finishAds(chatId, turnId, error);
    };

    const retryImage = async (turnId, index) => {
        const ad = turns.find(t => t.id === turnId)?.ads?.[index];
        if (!ad) return;
        const patch = fn => setTurn(chat.id, turnId, t => ({ ads: t.ads.map((x, i) => (i === index ? { ...x, ...fn(x) } : x)) }));
        patch(() => ({ image: null, imageError: "" }));
        try {
            const r = await fetch(`${API}/design/image`, { method: "POST", headers, body: JSON.stringify({ prompt: ad.image_prompt, aspect_ratio: ad.aspect_ratio, references }) });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || `Failed (${r.status})`);
            patch(() => ({ image: d.url ? { mime: d.mime, url: d.url } : { mime: d.mime, base64: d.base64 } }));
        } catch (e) { patch(() => ({ imageError: e.message })); }
    };

    const send = () => {
        const text = draft.trim();
        if (!text) return;
        setDraft("");
        createAds(text);
    };

    const buildWithCode = turn => onHandoff && (() => onHandoff("code", [
        "Build this campaign into my website: a landing section (or page) that matches the site's existing style,",
        "linked from the navigation, using this copy. Then open a PR.",
        `Campaign: ${turn.campaign}`,
        ...turn.ads.slice(0, 3).map(a => `- ${a.headline}: ${a.primary_text} [${a.cta}]`),
        site ? `Website: ${site}` : "",
    ].filter(Boolean).join("\n")));

    const business = (
        <BusinessCard chat={chat} setSite={v => set("site", v)} setBrief={v => set("brief", v)} setArea={v => set("area", v)} headers={headers} model={model}
            onUnauthorized={onUnauthorized} disabled={working || !!busy} />
    );

    return (
        <div style={{ position: "fixed", inset: 0, background: "var(--bg)", zIndex: 25, display: "flex", flexDirection: "column", overflowX: "hidden" }}>
            <div className="ds-head">
                <MenuButton onClick={() => setMenuOpen(true)} />
                <span style={{ fontWeight: 700, color: "var(--text)", whiteSpace: "nowrap" }}>Sem Design</span>
                <div className="ds-seg ds-modes" role="tablist" aria-label="Design mode">
                    {[["ads", "Images"], ["video", "Video"], ["music", "Music"], ["web", "Web"]].map(([id, name]) => (
                        <button key={id} role="tab" aria-selected={mode === id} disabled={!!busy && mode !== id} onClick={() => setMode(id)}>{name}</button>
                    ))}
                </div>
                <span style={{ flex: 1 }} />
                <button className="ds-btn sm" onClick={() => { setLibrary(true); loadVideos(); }} title="Your videos (last 7 days)">
                    ▶ {videos.filter(v => v.url).length || ""}
                </button>
                <HeaderStatus token={token} onFeed={() => { setFeedOpen(true); feed.acknowledgeErrors(); }} hasError={feed.hasError} busy={working || !!busy} />
                <ModelPicker token={token} value={model} onChange={setModel} storageKey="semblance_design_model" />
            </div>
            <AgentFeedPanel open={feedOpen} onClose={() => setFeedOpen(false)} events={feed.events}
                title={`Activity · ${chat.title || "New chat"}`} />
            <TabDrawer open={menuOpen} onClose={() => setMenuOpen(false)} title="Sem Design" current="design"
                onNavigate={onNavigate} newLabel="+ New campaign" disabled={!!busy}
                onNew={() => newChat({ site, brief, placements, count })}
                chats={chats} activeId={chat.id} onSelect={selectChat} onDelete={deleteChat}
                subtitle={c => c.site || ""} />
            {library && <VideoLibrary videos={videos.filter(v => !v.url || linkAlive(v.url))} onClose={() => setLibrary(null)} />}

            {mode === "music" ? (
                <MusicStudio headers={headers} chat={chat} updateChat={updateChat} onUnauthorized={onUnauthorized} top={business} brief={brief} model={model} />
            ) : mode === "video" ? (
                <VideoStudio headers={headers} chat={chat} updateChat={updateChat} brief={brief} model={model}
                    onUnauthorized={onUnauthorized} top={business} idea={videoIdea} setIdea={setVideoIdea} onRendered={loadVideos} />
            ) : mode === "web" ? (
                <WebStudio headers={headers} chat={chat} updateChat={updateChat} brief={brief} site={site} model={model}
                    busy={busy} setBusy={setBusy} notice={notice} setNotice={setNotice} onUnauthorized={onUnauthorized} onHandoff={onHandoff} top={business} />
            ) : (<>
                <div className="ds-feed" ref={scroller}>
                    <div className="ds-col">
                        {business}
                        {!turns.length && (
                            <div className="ds-empty">
                                <h2>What are we posting?</h2>
                                <div className="ds-muted" style={{ marginBottom: "14px" }}>
                                    Pick the platforms below. Each gets an image made for how people use it, a ready-to-paste caption, hashtags and the words people search for. Videos have their own tab.
                                </div>
                                <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", justifyContent: "center" }}>
                                    {SUGGESTIONS.map(s => <button key={s} className="ds-chip" onClick={() => setDraft(s)}>{s}</button>)}
                                </div>
                            </div>
                        )}
                        {turns.map(t => (t.kind === "video" ? (
                            <VideoTurn key={t.id} turn={t} disabled={working} onAgain={() => renderVideo(t.prompt, t.aspect_ratio)}
                                onGone={() => t.video?.url && setTurn(chat.id, t.id, { status: "failed", video: null, error: "Video expired (kept 7 days)" })} />
                        ) : (
                            <AdsTurn key={t.id} turn={t} disabled={working || !brief.trim()}
                                onRetry={i => retryImage(t.id, i)}
                                onExpired={i => t.ads[i]?.image?.url && setTurn(chat.id, t.id, x => ({ ads: x.ads.map((y, j) => (j === i ? { ...y, image: null, imageError: EXPIRED } : y)) }))}
                                onAgain={() => createAds(t.campaign, { placements: t.placements, count: t.count })}
                                onVideo={() => { setVideoIdea(`A short video for this campaign: ${t.campaign}`); setMode("video"); }}
                                onBuild={buildWithCode(t)} />
                        )))}
                        {!brief.trim() && turns.length > 0 && <div className="ds-muted" style={{ textAlign: "center" }}>Add the business brief above to make more.</div>}
                    </div>
                </div>
                <Composer kind="ads" draft={draft} setDraft={setDraft} onSend={send}
                    disabled={working || !brief.trim()}
                    placements={placements} togglePlacement={id => set("placements", p => { const now = (p || []).map(platform); return now.includes(id) ? now.filter(x => x !== id) : [...now, id]; })}
                    count={count} setCount={v => set("count", v)} aspect={aspect} setAspect={setAspect}
                    refs={refs} setRefs={setRefs} budget={budget}
                    improve={{ headers, brief, model, extra: [area && `Area: ${area}`, placements.length && `Platforms: ${placements.map(placementLabel).join(", ")}`].filter(Boolean).join(". ") }} />
            </>)}
        </div>
    );
}
