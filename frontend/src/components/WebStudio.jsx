import { useEffect, useState } from "react";
import { runStream } from "../utils/runs";
import { copyToClipboard } from "../utils/clipboard";
import { SendIcon } from "./Icons";

const API = import.meta.env.VITE_API_URL || "";
const btn = {
    padding: "8px 12px", borderRadius: "10px", border: "1px solid var(--border)", background: "var(--surface)",
    color: "var(--text)", fontSize: "13px", fontWeight: 600, cursor: "pointer", textDecoration: "none",
};
const field = {
    width: "100%", padding: "9px 11px", borderRadius: "10px", border: "1px solid var(--border)",
    background: "var(--surface)", color: "var(--text)", fontSize: "14px", fontFamily: "inherit", boxSizing: "border-box",
};
const hint = { fontSize: "12px", color: "var(--text-muted)", marginTop: "6px", lineHeight: 1.5 };
const STYLES = [["wordmark", "Wordmark"], ["icon", "Icon + name"], ["emblem", "Emblem"], ["monogram", "Monogram"]];
const src = (m) => m?.url || (m?.base64 ? `data:${m.mime || "image/png"};base64,${m.base64}` : "");

function Figma({ headers, figma, setFigma, disabled }) {
    const [connected, setConnected] = useState(null);
    const [token, setToken] = useState("");
    const [url, setUrl] = useState(figma.url || "");
    const [busy, setBusy] = useState("");
    const [error, setError] = useState("");
    useEffect(() => {
        fetch(`${API}/design/figma`, { headers }).then(r => r.json()).then(d => setConnected(!!d.connected)).catch(() => setConnected(false));
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const call = async (path, body, working) => {
        setBusy(working); setError("");
        try {
            const r = await fetch(`${API}${path}`, { method: "POST", headers, body: JSON.stringify(body) });
            const d = await r.json().catch(() => ({}));
            if (!r.ok) throw new Error(typeof d.detail === "string" ? d.detail : `Failed (${r.status})`);
            return d;
        } catch (e) { setError(e.message); return null; } finally { setBusy(""); }
    };
    const connect = async () => { if (await call("/design/figma/connect", { token }, "Checking your token…")) { setConnected(true); setToken(""); } };
    const load = async () => {
        const d = await call("/design/figma/import", { url }, "Fetching frames from Figma and reading the design…");
        if (d) setFigma({ url, frames: d.frames, notes: d.notes });
        if (d?.notes_error) setError(`Frames imported, but the design notes failed: ${d.notes_error}`);
    };

    return (
        <div>
            <div className="ds-kicker">From Figma (optional)</div>
            {connected === false && (
                <>
                    <div style={{ display: "flex", gap: "8px" }}>
                        <input value={token} onChange={e => setToken(e.target.value)} type="password" placeholder="Figma personal access token" style={{ ...field, flex: 1, minWidth: 0 }} />
                        <button onClick={connect} disabled={!token.trim() || !!busy || disabled} style={btn}>Connect</button>
                    </div>
                    <div style={hint}>Figma → Settings → Security → Personal access tokens. "File content: read" is enough.</div>
                </>
            )}
            {connected && (
                <div style={{ display: "flex", gap: "8px" }}>
                    <input value={url} onChange={e => setUrl(e.target.value)} placeholder="Figma link — a file, or a frame (right-click → Copy link)" style={{ ...field, flex: 1, minWidth: 0 }} />
                    <button onClick={load} disabled={!url.trim() || !!busy || disabled} style={btn}>Import</button>
                </div>
            )}
            {(busy || error) && <div style={{ ...hint, color: error ? "var(--danger)" : "var(--text-muted)" }}>{busy || error}</div>}
            {figma.frames?.length > 0 && (
                <>
                    <div style={{ display: "flex", gap: "8px", overflowX: "auto", marginTop: "8px" }}>
                        {figma.frames.map((f, i) => (
                            <img key={i} src={src(f)} alt={f.name} title={f.name}
                                style={{ height: "90px", borderRadius: "8px", border: "1px solid var(--border)", flexShrink: 0 }} />
                        ))}
                    </div>
                    <details style={{ marginTop: "6px" }}>
                        <summary style={{ fontSize: "12px", color: "var(--text-muted)", cursor: "pointer" }}>Design notes Sem will follow (editable)</summary>
                        <textarea value={figma.notes || ""} onChange={e => setFigma({ ...figma, notes: e.target.value })} rows={8} style={{ ...field, marginTop: "6px", fontSize: "12px" }} />
                    </details>
                    <button onClick={() => setFigma({})} style={{ ...btn, fontSize: "12px", marginTop: "6px" }}>Remove design</button>
                </>
            )}
        </div>
    );
}

const MAX_PAGES = 8;

// Design → Web: logo concepts and a single-file web page (from a brief or a Figma design) as a chat — each
// design or change is a version you can go back to. Logo images and Figma frames are kept 7 days.
export default function WebStudio({ headers, chat, updateChat, brief, site, model, busy, setBusy, notice, setNotice, onUnauthorized, onHandoff, top }) {
    const web = chat.web || {};
    const setWeb = (fn) => updateChat(chat.id, c => ({ web: { ...(c.web || {}), ...(typeof fn === "function" ? fn(c.web || {}) : fn) } }));
    const [styles, setStyles] = useState(STYLES.map(([id]) => id));
    const [draft, setDraft] = useState("");
    const [view, setView] = useState("preview");
    const [full, setFull] = useState(false);
    const figma = web.figma || {};
    // Versions of the page; an old save with only web.html becomes version 1.
    const pages = web.pages || (web.html ? [{ html: web.html, model: web.pageModel, request: web.request || "" }] : []);
    const shown = Math.min(web.pageIndex ?? pages.length - 1, pages.length - 1);
    const page = pages[shown];
    useEffect(() => { setDraft(""); }, [chat.id]);

    const stream = async (path, body, onEvent, working) => {
        setBusy(working); setNotice("");
        try {
            const r = await runStream(path, { headers, body: { ...body, chat_id: chat.id }, onEvent });
            if (r.status === 401) { onUnauthorized(); return; }
            if (r.error) throw new Error(r.error);
        } catch (e) { if (e.name !== "AbortError") setNotice(e.message); }
        setBusy("");
    };

    const makeLogos = () => {
        setWeb({ logos: styles.map(style => ({ style })) });
        return stream("/design/logos", { name: web.name, brief, styles, notes: figma.notes ? "Match the brand colours in the design notes" : "" }, (ev) => {
            if (ev.type === "status") setBusy(ev.text);
            else if (ev.type === "logo") setWeb(w => ({ logos: (w.logos || []).map((l, i) => (i === ev.index ? { ...l, image: ev.url ? { url: ev.url } : { mime: ev.mime, base64: ev.base64 } } : l)) }));
            else if (ev.type === "logo_error") setWeb(w => ({ logos: (w.logos || []).map((l, i) => (i === ev.index ? { ...l, error: ev.error } : l)) }));
        }, "Drawing logos…");
    };

    // A message refines the version on screen; "Start over" designs from scratch.
    const makePage = (ask, fresh) => {
        const base = fresh ? "" : page?.html || "";
        setDraft("");
        return stream("/design/page", { request: ask, brief, model, design: figma.notes || "", html: base }, (ev) => {
            if (ev.type === "status") setBusy(ev.text);
            else if (ev.type === "page") {
                setWeb(w => {
                    const list = [...(w.pages || pages), { html: ev.html, model: ev.model, request: ask, created: Date.now() }].slice(-MAX_PAGES);
                    return { pages: list, pageIndex: list.length - 1, html: ev.html, pageModel: ev.model, request: ask };
                });
                setView("preview");
            } else if (ev.type === "error") setNotice(ev.text);
        }, base ? "Updating the page…" : "Designing the page…");
    };

    const download = () => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([page.html], { type: "text/html" }));
        a.download = `${(web.name || site || "page").replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.html`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    };
    const send = () => draft.trim() && !busy && brief.trim() && makePage(draft.trim(), !page);

    return (<>
        <div className="ds-feed">
            <div className="ds-col">
                {top}
                <div className="ds-card"><div className="ds-card-body" style={{ paddingTop: "14px" }}>
                    <Figma headers={headers} figma={figma} setFigma={f => setWeb({ figma: f })} disabled={!!busy} />
                </div></div>

                <div className="ds-card"><div className="ds-card-body" style={{ paddingTop: "14px" }}>
                    <div className="ds-kicker">Logo</div>
                    <input className="ds-field" value={web.name || ""} onChange={e => setWeb({ name: e.target.value })} placeholder="Business name, exactly as it should be spelled" />
                    <div className="ds-chips" style={{ flexWrap: "wrap" }}>
                        {STYLES.map(([id, name]) => (
                            <button key={id} onClick={() => setStyles(s => (s.includes(id) ? s.filter(x => x !== id) : [...s, id]))} aria-pressed={styles.includes(id)}
                                className={`ds-chip${styles.includes(id) ? " is-selected" : ""}`}>{name}</button>
                        ))}
                        <button onClick={makeLogos} disabled={!web.name?.trim() || !styles.length || !!busy} className="ds-btn sm btn-primary">Make logos</button>
                    </div>
                    {web.logos?.length > 0 && (
                        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: "10px" }}>
                            {web.logos.map((l, i) => (
                                <div key={i} className="ds-ad" style={{ background: "#fff" }}>
                                    <div className="ds-ad-media" style={{ aspectRatio: "1", background: "#fff", minHeight: 0 }}>
                                        {l.image ? <img src={src(l.image)} alt={`${l.style} logo`}
                                            onError={() => l.image?.url && setWeb(w => ({ logos: w.logos.map((x, j) => (j === i ? { ...x, image: null, error: "Expired (kept 7 days)" } : x)) }))} />
                                            : l.error ? <span style={{ fontSize: "12px", color: "var(--danger)", padding: "8px", textAlign: "center" }}>{l.error}</span>
                                            : <><div className="ds-shimmer" /><span style={{ fontSize: "12px", color: "#777" }}>Drawing…</span></>}
                                    </div>
                                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 8px", background: "var(--bg)" }}>
                                        <span className="ds-muted">{l.style}</span>
                                        {l.image && <a href={src(l.image)} download={`logo-${l.style}.png`} target="_blank" rel="noreferrer" className="ds-btn sm">Download</a>}
                                    </div>
                                </div>
                            ))}
                        </div>
                    )}
                </div></div>

                {pages.map((p, i) => (
                    <div key={i} className="ds-user" style={{ opacity: i === shown ? 1 : 0.6, cursor: "pointer" }} onClick={() => setWeb({ pageIndex: i, html: p.html })}
                        title="Show this version">
                        {p.request || "Page"}
                        <div className="ds-tags"><span className="ds-tag">v{i + 1}{i === shown ? " · showing" : ""}</span></div>
                    </div>
                ))}
                {(page || busy) && (
                    <div className="ds-sem">
                        <div className="ds-avatar">S</div>
                        <div className="ds-sem-body">
                            {busy && <div className="ds-status"><span className="ds-spin" />{busy}</div>}
                            {page && (<>
                                <div className="ds-actions">
                                    <div className="ds-seg">
                                        {[["preview", "Preview"], ["code", "Code"]].map(([id, name]) => (
                                            <button key={id} aria-selected={view === id} onClick={() => setView(id)}>{name}</button>
                                        ))}
                                    </div>
                                    {pages.length > 1 && (
                                        <select className="ds-chip" value={shown} onChange={e => { const i = Number(e.target.value); setWeb({ pageIndex: i, html: pages[i].html }); }}>
                                            {pages.map((_, i) => <option key={i} value={i}>Version {i + 1}</option>)}
                                        </select>
                                    )}
                                    <button className="ds-btn sm" onClick={() => setFull(true)}>Full screen</button>
                                    <button className="ds-btn sm" onClick={download}>Download</button>
                                    <button className="ds-btn sm" onClick={() => copyToClipboard(page.html)}>Copy</button>
                                    {onHandoff && (
                                        <button className="ds-btn sm" onClick={() => onHandoff("code", [
                                            "Add this page to my website's codebase, matching its framework and structure, and open a PR.",
                                            site ? `Website: ${site}` : "",
                                            "The page (single-file HTML to adapt):",
                                            page.html.slice(0, 20000),
                                        ].filter(Boolean).join("\n"))}>Build it with Code →</button>
                                    )}
                                </div>
                                {view === "preview" ? (
                                    // sandboxed without same-origin: the page can't reach this app, its storage or your login
                                    <iframe title="Page preview" srcDoc={page.html} sandbox="allow-scripts"
                                        style={{ width: "100%", height: "70vh", border: "1px solid var(--border)", borderRadius: "14px", background: "#fff" }} />
                                ) : (
                                    <pre className="ds-field" style={{ height: "70vh", overflow: "auto", fontSize: "11px", whiteSpace: "pre-wrap", margin: 0 }}>{page.html}</pre>
                                )}
                                {page.model && <div className="ds-muted">Made with {page.model}. Pick a bigger model in the top bar for richer pages.</div>}
                            </>)}
                        </div>
                    </div>
                )}
                {!page && !busy && (
                    <div className="ds-empty">
                        <h2>What should the site look like?</h2>
                        <div className="ds-muted">{figma.notes ? "Sem will build your Figma design — say what the page is for below." : "Describe the page below. Uses the business brief above; add a Figma design to copy a look exactly."}</div>
                    </div>
                )}
                {notice && <div className="msg-error">{notice}</div>}
            </div>
        </div>
        <div className="ds-composer">
            <div className="ds-composer-box">
                <textarea rows={1} value={draft} onChange={e => setDraft(e.target.value)}
                    onKeyDown={e => { if (e.key === "Enter" && !e.shiftKey && window.matchMedia("(pointer: fine)").matches) { e.preventDefault(); send(); } }}
                    placeholder={page ? "Change something, e.g. make the header dark and add a pricing section"
                        : figma.notes ? "e.g. Build this design as a responsive landing page" : "e.g. A one-page site: hero with our weekend special, menu, reviews, WhatsApp button"} />
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <span className="ds-muted" style={{ flex: 1 }}>{!brief.trim() ? "Add the business brief first" : page ? `Changes version ${shown + 1}` : "New page"}</span>
                    {page && <button className="ds-btn sm" disabled={!draft.trim() || !!busy || !brief.trim()} onClick={() => makePage(draft.trim(), true)}>Start over</button>}
                    <button className="ds-send btn-primary" onClick={send} disabled={!draft.trim() || !!busy || !brief.trim()} aria-label="Send" style={{ border: "none" }}><SendIcon size={18} /></button>
                </div>
            </div>
        </div>
        {full && page && (
            <div role="dialog" aria-label="Page preview" style={{ position: "fixed", inset: 0, zIndex: 200, background: "#fff", display: "flex", flexDirection: "column" }}>
                <button onClick={() => setFull(false)} className="ds-btn" style={{ borderRadius: 0, border: "none", borderBottom: "1px solid var(--border)", justifyContent: "center" }}>Close preview</button>
                <iframe title="Page preview full screen" srcDoc={page.html} sandbox="allow-scripts" style={{ flex: 1, border: "none" }} />
            </div>
        )}
    </>);
}
