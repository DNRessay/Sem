import { useEffect, useRef, useState } from "react";
import ModelPicker, { loadModel } from "./ModelPicker";
import { readEvents } from "../utils/sse";
import { copyToClipboard } from "../utils/clipboard";
import TabDrawer, { MenuButton } from "./TabDrawer";
import useTabChats from "../hooks/useTabChats";

const API = import.meta.env.VITE_API_URL || "";
const STORE_KEY = "semblance_design_campaigns";
const OLD_KEY = "semblance_design";
const PLACEMENTS = [
    ["fb_ig_feed", "FB/IG feed"], ["square", "Square"], ["story_reel", "Story/Reel/TikTok"],
    ["google_display", "Google Display"], ["whatsapp_status", "WhatsApp Status"],
];

const btn = {
    padding: "8px 12px", borderRadius: "10px", border: "1px solid var(--border)", background: "var(--surface)",
    color: "var(--text)", fontSize: "13px", fontWeight: 600, cursor: "pointer",
};
const primary = { ...btn, background: "var(--accent)", color: "var(--accent-contrast)", border: "none" };
const field = {
    width: "100%", padding: "9px 11px", borderRadius: "10px", border: "1px solid var(--border)",
    background: "var(--surface)", color: "var(--text)", fontSize: "14px", fontFamily: "inherit", boxSizing: "border-box",
};
const label = { fontSize: "11px", fontWeight: 600, letterSpacing: "1px", color: "var(--text-muted)", margin: "14px 0 6px" };

function loadSaved() {
    try { return JSON.parse(localStorage.getItem(OLD_KEY)) || {}; } catch { return {}; }
}

const MAX_REFS = 4;

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

function Inspiration({ refs, setRefs, style, disabled }) {
    const [error, setError] = useState("");
    const add = async (files) => {
        setError("");
        try {
            let added = [];
            for (const f of files) added = added.concat(f.type.startsWith("video/") ? await videoToRefs(f) : await imageToRef(f));
            setRefs(r => [...r, ...added].slice(0, MAX_REFS));
            if (refs.length + added.length > MAX_REFS) setError(`Kept the first ${MAX_REFS} — that's all the image model takes.`);
        } catch (e) { setError(e.message); }
    };
    return (
        <div>
            <div style={label}>INSPIRATION (OPTIONAL)</div>
            <div style={{ fontSize: "12px", color: "var(--text-muted)", marginBottom: "6px" }}>
                Ads, posts, photos or a video you like. Sem copies the look (colours, layout, mood), not the content.
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", alignItems: "center" }}>
                {refs.map((r, i) => (
                    <div key={i} style={{ position: "relative" }}>
                        <img src={`data:${r.mime};base64,${r.base64}`} alt={r.name} title={r.name}
                            style={{ width: "64px", height: "64px", objectFit: "cover", borderRadius: "8px", border: "1px solid var(--border)" }} />
                        <button onClick={() => setRefs(x => x.filter((_, j) => j !== i))} aria-label="Remove"
                            style={{ position: "absolute", top: "-6px", right: "-6px", width: "20px", height: "20px", borderRadius: "50%", border: "none", background: "var(--text)", color: "var(--bg)", fontSize: "11px", cursor: "pointer" }}>✕</button>
                    </div>
                ))}
                {refs.length < MAX_REFS && (
                    <label style={{ ...btn, display: "inline-flex", alignItems: "center", height: "64px", boxSizing: "border-box", opacity: disabled ? 0.5 : 1 }}>
                        + Images / video
                        <input type="file" accept="image/*,video/*" multiple disabled={disabled} style={{ display: "none" }}
                            onChange={e => { add([...e.target.files]); e.target.value = ""; }} />
                    </label>
                )}
            </div>
            {error && <div style={{ fontSize: "12px", color: "var(--danger)", marginTop: "4px" }}>{error}</div>}
            {style && (
                <details style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "6px" }}>
                    <summary style={{ cursor: "pointer" }}>Style Sem picked up</summary>
                    <div style={{ whiteSpace: "pre-wrap", marginTop: "4px" }}>{style}</div>
                </details>
            )}
        </div>
    );
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
        <details style={{ marginTop: "8px", fontSize: "12px", color: "var(--text-muted)" }}>
            <summary style={{ cursor: "pointer" }}>Connect Vicinic (use a customer site's details)</summary>
            <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginTop: "6px" }}>
                <input value={form.url} onChange={e => setForm({ ...form, url: e.target.value })} placeholder="https://… Vicinic backend address" style={field} />
                <input value={form.key} onChange={e => setForm({ ...form, key: e.target.value })} placeholder="vic_… key (Vicinic Admin → Connect apps)" type="password" style={field} />
                <button className="btn-primary" onClick={connect} disabled={!form.url || !form.key} style={{ ...btn, alignSelf: "flex-start" }}>Connect</button>
                {msg && <div>{msg}</div>}
            </div>
        </details>
    );
    return (
        <div style={{ display: "flex", gap: "8px", marginTop: "8px", alignItems: "center", flexWrap: "wrap" }}>
            <select value={slug} onChange={e => setSlug(e.target.value)} style={{ ...field, flex: 1, minWidth: "160px" }}>
                <option value="">Vicinic customer site…</option>
                {state.sites.map(x => <option key={x.slug} value={x.slug}>{x.name} ({x.package})</option>)}
            </select>
            <button onClick={use} disabled={!slug || disabled} style={btn}>Use its details</button>
            {msg && <div style={{ fontSize: "12px", color: "var(--text-muted)", width: "100%" }}>{msg}</div>}
        </div>
    );
}

function AdCard({ ad, onRetry }) {
    const text = `${ad.headline}\n\n${ad.primary_text}\n\n${(ad.hashtags || []).join(" ")}`;
    return (
        <div style={{ border: "1px solid var(--border)", borderRadius: "14px", overflow: "hidden", background: "var(--surface)" }}>
            <div style={{ background: "var(--surface-2)", minHeight: "120px", display: "flex", alignItems: "center", justifyContent: "center" }}>
                {ad.image ? (
                    <img src={`data:${ad.image.mime};base64,${ad.image.base64}`} alt={ad.headline} style={{ width: "100%", display: "block" }} />
                ) : (
                    <span style={{ fontSize: "12px", color: !ad.imageError ? "var(--text-muted)" : /limit|not kept/i.test(ad.imageError) ? "var(--warning)" : "var(--danger)", padding: "16px", textAlign: "center" }}>
                        {ad.imageError || "Making image…"}
                    </span>
                )}
            </div>
            <div style={{ padding: "10px 12px", display: "flex", flexDirection: "column", gap: "6px" }}>
                <div style={{ fontSize: "11px", color: "var(--text-muted)" }}>{ad.placementLabel} · {ad.angle}</div>
                <div style={{ fontWeight: 700, fontSize: "15px" }}>{ad.headline}</div>
                <div style={{ fontSize: "14px", lineHeight: 1.5 }}>{ad.primary_text}</div>
                <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>{(ad.hashtags || []).join(" ")}</div>
                <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", alignItems: "center" }}>
                    <span style={{ ...btn, cursor: "default", fontSize: "12px" }}>{ad.cta}</span>
                    <span style={{ flex: 1 }} />
                    <button onClick={() => copyToClipboard(text)} style={{ ...btn, fontSize: "12px" }}>Copy text</button>
                    {ad.image && (
                        <a href={`data:${ad.image.mime};base64,${ad.image.base64}`} download={`ad-${ad.placement}.png`} style={{ ...btn, fontSize: "12px", textDecoration: "none" }}>Download</a>
                    )}
                    <button onClick={onRetry} style={{ ...btn, fontSize: "12px" }}>New image</button>
                </div>
            </div>
        </div>
    );
}

function VideoStudio({ token, seedPrompt }) {
    const [prompt, setPrompt] = useState("");
    const [aspect, setAspect] = useState("9:16");
    const [job, setJob] = useState(null);
    const [status, setStatus] = useState("");
    const [video, setVideo] = useState(null);
    const [budget, setBudget] = useState(null);
    const timer = useRef(null);
    const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

    useEffect(() => { if (seedPrompt) setPrompt(seedPrompt); }, [seedPrompt]);
    useEffect(() => {
        fetch(`${API}/design/video/budget`, { headers }).then(r => r.json()).then(d => d.ok && setBudget(d)).catch(() => {});
        return () => clearTimeout(timer.current);
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const poll = (id) => {
        timer.current = setTimeout(async () => {
            try {
                const r = await fetch(`${API}/design/video/${id}`, { headers });
                const d = await r.json();
                if (d.status === "done") { setVideo(d); setStatus(`Done in ${Math.round((d.gpu_seconds || 0) / 60)} min of GPU time`); setJob(null); return; }
                if (d.status === "failed" || !r.ok) { setStatus(d.error || d.detail || "Render failed"); setJob(null); return; }
                setStatus("Rendering… (usually 5-10 minutes; you can leave this page open)");
                poll(id);
            } catch { poll(id); }
        }, 10000);
    };

    const submit = async () => {
        setVideo(null); setStatus("Starting…");
        const r = await fetch(`${API}/design/video`, { method: "POST", headers, body: JSON.stringify({ prompt, aspect_ratio: aspect }) });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) { setStatus(d.detail || `Failed (${r.status})`); return; }
        setJob(d.job_id); setBudget({ used_usd: d.used_usd, cap_usd: d.cap_usd });
        setStatus("Queued — warming up the GPU…");
        poll(d.job_id);
    };

    return (
        <div>
            <div style={label}>VIDEO AD (OPEN-SOURCE WAN 2.1)</div>
            <textarea value={prompt} onChange={e => setPrompt(e.target.value)} rows={3} style={field}
                placeholder="Describe a 5-second clip, e.g. Slow close-up of steaming sourdough on a wooden board, warm morning light" />
            <div style={{ display: "flex", gap: "8px", alignItems: "center", marginTop: "8px", flexWrap: "wrap" }}>
                <select value={aspect} onChange={e => setAspect(e.target.value)} style={{ ...field, width: "auto" }}>
                    <option value="9:16">9:16 Reel/Story</option>
                    <option value="16:9">16:9 YouTube</option>
                    <option value="1:1">1:1 Feed</option>
                </select>
                <button onClick={submit} disabled={!prompt.trim() || !!job} className="btn-primary" style={primary}>{job ? "Rendering…" : "Render video"}</button>
                {budget && <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>Budget ${Number(budget.used_usd).toFixed(2)} / ${Number(budget.cap_usd).toFixed(2)} this month</span>}
            </div>
            {status && <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "8px" }}>{status}</div>}
            {video && (
                <div style={{ marginTop: "10px" }}>
                    <video src={`data:${video.mime};base64,${video.base64}`} controls style={{ width: "100%", borderRadius: "12px" }} />
                    <a href={`data:${video.mime};base64,${video.base64}`} download="semblance-video-ad.mp4" style={{ ...btn, display: "inline-block", marginTop: "6px", textDecoration: "none" }}>Download video</a>
                </div>
            )}
        </div>
    );
}

// Design tab: digital-marketing assistant. Learns the business from its own
// website, then writes ad copy and makes matching images per placement
// (Nano Banana, free tier) and short video ads (Wan 2.1 on Modal, capped).
export default function DesignPage({ token, onNavigate, onUnauthorized, handoff, onHandoff }) {
    // Each campaign is a saved "chat": the business brief, the campaign and its ad copy (images aren't stored).
    const { chats, chat, updateChat, newChat, selectChat, deleteChat } = useTabChats(STORE_KEY, {
        blank: () => ({ site: "", brief: "", campaign: "", placements: ["fb_ig_feed", "story_reel"], count: 2, ads: [] }),
        legacy: () => { const s = loadSaved(); return { ...s, title: (s.campaign || "").slice(0, 60) }; },
        persist: c => ({ ...c, ads: (c.ads || []).map(({ image, ...ad }) => (image ? { ...ad, imageError: "Image not kept — tap New image" } : ad)) }),
    });
    const { site, brief, campaign, placements, count } = chat;
    const field$ = key => v => updateChat(chat.id, c => ({ [key]: typeof v === "function" ? v(c[key]) : v,
        ...(key === "campaign" ? { title: (typeof v === "function" ? v(c[key]) : v).slice(0, 60) } : {}) }));
    const setSite = field$("site");
    const setBrief = field$("brief");
    const setCampaign = field$("campaign");
    const setPlacements = field$("placements");
    const setCount = field$("count");
    const [menuOpen, setMenuOpen] = useState(false);
    // Inspiration images stay in memory only (too big for phone storage); the style text they produced is saved.
    const [refs, setRefs] = useState([]);
    useEffect(() => { setRefs([]); }, [chat.id]);
    const references = refs.map(({ mime, base64 }) => ({ mime, base64 }));
    const takenHandoff = useRef(0);
    useEffect(() => {
        if (handoff?.view !== "design" || takenHandoff.current === handoff.at) return;
        takenHandoff.current = handoff.at;
        newChat({ site, brief, placements, count, ads: [], campaign: handoff.task, title: handoff.task.slice(0, 60) });
    }, [handoff]); // eslint-disable-line react-hooks/exhaustive-deps
    const [model, setModel] = useState(() => loadModel("semblance_design_model"));
    const ads = chat.ads || [];
    const setAds = v => updateChat(chat.id, c => ({ ads: typeof v === "function" ? v(c.ads || []) : v }));
    const [busy, setBusy] = useState("");
    const [notice, setNotice] = useState("");
    const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

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

    const create = async () => {
        setBusy("Writing ads…"); setNotice(""); setAds([]);
        try {
            const r = await fetch(`${API}/design/ads`, { method: "POST", headers, body: JSON.stringify({ brief, campaign, placements, count, model, references }) });
            if (r.status === 401) { onUnauthorized(); return; }
            if (!r.ok || !r.body) throw new Error((await r.json().catch(() => ({}))).detail || `Failed (${r.status})`);
            await readEvents(r, (ev) => {
                if (ev.type === "status") setBusy(ev.text);
                else if (ev.type === "style") updateChat(chat.id, () => ({ style: ev.text }));
                else if (ev.type === "variants") {
                    setAds(ev.variants.map(v => ({ ...v, placementLabel: (PLACEMENTS.find(p => p[0] === v.placement) || [])[1] })));
                    setBusy("Making images…");
                } else if (ev.type === "image") setAds(a => a.map((ad, i) => (i === ev.index ? { ...ad, image: { mime: ev.mime, base64: ev.base64 } } : ad)));
                else if (ev.type === "image_error") setAds(a => a.map((ad, i) => (i === ev.index ? { ...ad, imageError: ev.error } : ad)));
                else if (ev.type === "error") setNotice(ev.text);
            });
            setAds(a => a.map(ad => (ad.image || ad.imageError ? ad : { ...ad, imageError: "Skipped (image limit reached) — tap New image later" })));
        } catch (e) { setNotice(e.message); }
        setBusy("");
    };

    const retryImage = async (index) => {
        const ad = ads[index];
        setAds(a => a.map((x, i) => (i === index ? { ...x, image: null, imageError: "" } : x)));
        try {
            const r = await fetch(`${API}/design/image`, { method: "POST", headers, body: JSON.stringify({ prompt: ad.image_prompt, aspect_ratio: ad.aspect_ratio, references }) });
            const d = await r.json();
            if (!r.ok) throw new Error(d.detail || `Failed (${r.status})`);
            setAds(a => a.map((x, i) => (i === index ? { ...x, image: { mime: d.mime, base64: d.base64 } } : x)));
        } catch (e) { setAds(a => a.map((x, i) => (i === index ? { ...x, imageError: e.message } : x))); }
    };

    const toggle = (id) => setPlacements(p => (p.includes(id) ? p.filter(x => x !== id) : [...p, id]));

    return (
        <div style={{ position: "fixed", inset: 0, background: "var(--bg)", zIndex: 25, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                <MenuButton onClick={() => setMenuOpen(true)} />
                <span style={{ fontWeight: 700, color: "var(--text)", flex: 1 }}>Sem Design</span>
                <ModelPicker token={token} value={model} onChange={setModel} storageKey="semblance_design_model" />
            </div>
            <TabDrawer open={menuOpen} onClose={() => setMenuOpen(false)} title="Sem Design" current="design"
                onNavigate={onNavigate} newLabel="+ New campaign" disabled={!!busy}
                onNew={() => { newChat({ site, brief, placements, count }); setNotice(""); }}
                chats={chats} activeId={chat.id} onSelect={id => { selectChat(id); setNotice(""); }} onDelete={deleteChat}
                subtitle={c => c.site || ""} />

            <div style={{ flex: 1, overflowY: "auto", padding: "4px 16px 32px" }}>
                <div style={label}>YOUR BUSINESS</div>
                <div style={{ display: "flex", gap: "8px" }}>
                    <input value={site} onChange={e => setSite(e.target.value)} placeholder="yourwebsite.co.za" style={{ ...field, flex: 1 }} />
                    <button onClick={learn} disabled={!site.trim() || !!busy} style={btn}>Learn from site</button>
                </div>
                <VicinicPicker headers={headers} disabled={!!busy} onBrief={d => {
                    setBrief([d.brief, d.phone && `Phone: ${d.phone}`, d.whatsapp && `WhatsApp: ${d.whatsapp}`,
                        d.primary_color && `Brand colour: ${d.primary_color}`].filter(Boolean).join("\n"));
                    if (d.domain) setSite(d.domain);
                    setNotice(`Using ${d.slug}'s details from Vicinic. Edit anything that's off.`);
                }} />
                <textarea value={brief} onChange={e => setBrief(e.target.value)} rows={brief ? 9 : 3} style={{ ...field, marginTop: "8px" }}
                    placeholder="Or describe the business: what you sell, who to, where, your tone…" />

                <Inspiration refs={refs} setRefs={setRefs} style={chat.style} disabled={!!busy} />

                <div style={label}>CAMPAIGN</div>
                <textarea value={campaign} onChange={e => setCampaign(e.target.value)} rows={2} style={field}
                    placeholder="e.g. Weekend special: 2 loaves for R80, ends Sunday" />
                <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginTop: "8px" }}>
                    {PLACEMENTS.map(([id, name]) => (
                        <button key={id} onClick={() => toggle(id)} aria-pressed={placements.includes(id)}
                            className={placements.includes(id) ? "is-selected" : ""} style={{ ...btn, fontSize: "12px", fontWeight: 500 }}>
                            {name}
                        </button>
                    ))}
                </div>
                <div style={{ display: "flex", gap: "8px", alignItems: "center", marginTop: "10px" }}>
                    <select value={count} onChange={e => setCount(Number(e.target.value))} style={{ ...field, width: "auto" }}>
                        {[1, 2, 3].map(n => <option key={n} value={n}>{n} per placement</option>)}
                    </select>
                    <button onClick={create} disabled={!brief.trim() || !campaign.trim() || !placements.length || !!busy} className="btn-primary" style={primary}>Create ads</button>
                </div>
                {(busy || notice) && <div style={{ fontSize: "12px", color: "var(--text-muted)", marginTop: "8px" }}>{busy || notice}</div>}

                {ads.length > 0 && onHandoff && (
                    <button onClick={() => onHandoff("code", [
                        "Build this campaign into my website: a landing section (or page) that matches the site's existing style,",
                        "linked from the navigation, using this copy. Then open a PR.",
                        `Campaign: ${campaign}`,
                        ...ads.slice(0, 3).map(a => `- ${a.headline}: ${a.primary_text} [${a.cta}]`),
                        site ? `Website: ${site}` : "",
                    ].filter(Boolean).join("\n"))} style={{ ...btn, marginTop: "12px" }}>Build it with Code →</button>
                )}
                {ads.length > 0 && (
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: "12px", marginTop: "14px" }}>
                        {ads.map((ad, i) => <AdCard key={i} ad={ad} onRetry={() => retryImage(i)} />)}
                    </div>
                )}

                <VideoStudio token={token} seedPrompt={ads[0]?.image_prompt || ""} />
            </div>
        </div>
    );
}
