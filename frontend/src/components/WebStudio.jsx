import { useEffect, useState } from "react";
import { runStream } from "../utils/runs";
import { copyToClipboard } from "../utils/clipboard";

const API = import.meta.env.VITE_API_URL || "";
const btn = {
    padding: "8px 12px", borderRadius: "10px", border: "1px solid var(--border)", background: "var(--surface)",
    color: "var(--text)", fontSize: "13px", fontWeight: 600, cursor: "pointer", textDecoration: "none",
};
const primary = { ...btn, background: "var(--accent)", color: "var(--accent-contrast)", border: "none" };
const field = {
    width: "100%", padding: "9px 11px", borderRadius: "10px", border: "1px solid var(--border)",
    background: "var(--surface)", color: "var(--text)", fontSize: "14px", fontFamily: "inherit", boxSizing: "border-box",
};
const label = { fontSize: "11px", fontWeight: 600, letterSpacing: "1px", color: "var(--text-muted)", margin: "14px 0 6px" };
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
            <div style={label}>FROM FIGMA (OPTIONAL)</div>
            {connected === false && (
                <>
                    <div style={{ display: "flex", gap: "8px" }}>
                        <input value={token} onChange={e => setToken(e.target.value)} type="password" placeholder="Figma personal access token" style={{ ...field, flex: 1 }} />
                        <button onClick={connect} disabled={!token.trim() || !!busy || disabled} style={btn}>Connect</button>
                    </div>
                    <div style={hint}>Figma → Settings → Security → Personal access tokens. "File content: read" is enough.</div>
                </>
            )}
            {connected && (
                <div style={{ display: "flex", gap: "8px" }}>
                    <input value={url} onChange={e => setUrl(e.target.value)} placeholder="Figma link — a file, or a frame (right-click → Copy link)" style={{ ...field, flex: 1 }} />
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

// Design → Web: logo concepts, a single-file web page (from a brief or a Figma design), refine, download or
// hand to the Code tab. Everything is saved with the campaign; logo images and Figma frames are kept 7 days.
export default function WebStudio({ headers, chat, updateChat, brief, site, model, busy, setBusy, setNotice, onUnauthorized, onHandoff }) {
    const web = chat.web || {};
    const setWeb = (fn) => updateChat(chat.id, c => ({ web: { ...(c.web || {}), ...(typeof fn === "function" ? fn(c.web || {}) : fn) } }));
    const [styles, setStyles] = useState(STYLES.map(([id]) => id));
    const [change, setChange] = useState("");
    const [view, setView] = useState("preview");
    const figma = web.figma || {};

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

    const makePage = (refine) => stream("/design/page", {
        request: refine ? change : web.request, brief, model, design: figma.notes || "", html: refine ? web.html : "",
    }, (ev) => {
        if (ev.type === "status") setBusy(ev.text);
        else if (ev.type === "page") { setWeb({ html: ev.html, pageModel: ev.model }); setView("preview"); if (refine) setChange(""); }
        else if (ev.type === "error") setNotice(ev.text);
    }, refine ? "Updating the page…" : "Designing the page…");

    const download = () => {
        const a = document.createElement("a");
        a.href = URL.createObjectURL(new Blob([web.html], { type: "text/html" }));
        a.download = `${(web.name || site || "page").replace(/[^a-z0-9]+/gi, "-").toLowerCase()}.html`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    };
    // Full screen stays inside the sandboxed iframe: a blob/new-tab page would run with this app's origin
    // and could read the login token.
    const [full, setFull] = useState(false);

    return (
        <div>
            <Figma headers={headers} figma={figma} setFigma={f => setWeb({ figma: f })} disabled={!!busy} />

            <div style={label}>LOGO</div>
            <input value={web.name || ""} onChange={e => setWeb({ name: e.target.value })} placeholder="Business name, exactly as it should be spelled" style={field} />
            <div style={{ display: "flex", flexWrap: "wrap", gap: "6px", marginTop: "8px" }}>
                {STYLES.map(([id, name]) => (
                    <button key={id} onClick={() => setStyles(s => (s.includes(id) ? s.filter(x => x !== id) : [...s, id]))} aria-pressed={styles.includes(id)}
                        className={styles.includes(id) ? "is-selected" : ""} style={{ ...btn, fontSize: "12px", fontWeight: 500 }}>{name}</button>
                ))}
                <button onClick={makeLogos} disabled={!web.name?.trim() || !styles.length || !!busy} className="btn-primary" style={primary}>Make logos</button>
            </div>
            {web.logos?.length > 0 && (
                <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))", gap: "10px", marginTop: "10px" }}>
                    {web.logos.map((l, i) => (
                        <div key={i} style={{ border: "1px solid var(--border)", borderRadius: "12px", overflow: "hidden", background: "#fff" }}>
                            <div style={{ aspectRatio: "1", display: "flex", alignItems: "center", justifyContent: "center" }}>
                                {l.image ? <img src={src(l.image)} alt={`${l.style} logo`} style={{ width: "100%" }}
                                    onError={() => l.image?.url && setWeb(w => ({ logos: w.logos.map((x, j) => (j === i ? { ...x, image: null, error: "Expired (kept 7 days)" } : x)) }))} />
                                    : <span style={{ fontSize: "12px", color: l.error ? "var(--danger)" : "#777", padding: "8px", textAlign: "center" }}>{l.error || "Drawing…"}</span>}
                            </div>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "6px 8px", background: "var(--surface)" }}>
                                <span style={{ fontSize: "11px", color: "var(--text-muted)" }}>{l.style}</span>
                                {l.image && <a href={src(l.image)} download={`logo-${l.style}.png`} target="_blank" rel="noreferrer" style={{ ...btn, fontSize: "11px", padding: "4px 8px" }}>Download</a>}
                            </div>
                        </div>
                    ))}
                </div>
            )}

            <div style={label}>WEBSITE / PAGE</div>
            <textarea value={web.request || ""} onChange={e => setWeb({ request: e.target.value })} rows={3} style={field}
                placeholder={figma.notes ? "e.g. Build this design as a responsive landing page" : "e.g. A one-page site: hero with our weekend special, menu, reviews, location and WhatsApp button"} />
            <div style={{ display: "flex", gap: "8px", marginTop: "8px", flexWrap: "wrap", alignItems: "center" }}>
                <button onClick={() => makePage(false)} disabled={!web.request?.trim() || !!busy} className="btn-primary" style={primary}>
                    {web.html ? "Design again" : figma.notes ? "Build from Figma" : "Design page"}
                </button>
                {!figma.notes && <span style={{ fontSize: "12px", color: "var(--text-muted)" }}>Uses the business brief above{figma.frames ? "" : " — add a Figma design to copy a look exactly"}</span>}
            </div>

            {web.html && (
                <div style={{ marginTop: "12px" }}>
                    <div style={{ display: "flex", gap: "6px", flexWrap: "wrap", marginBottom: "8px" }}>
                        <button onClick={() => setView(v => (v === "preview" ? "code" : "preview"))} style={btn}>{view === "preview" ? "Code" : "Preview"}</button>
                        <button onClick={() => setFull(true)} style={btn}>Full screen</button>
                        <button onClick={download} style={btn}>Download HTML</button>
                        <button onClick={() => copyToClipboard(web.html)} style={btn}>Copy</button>
                        {onHandoff && (
                            <button onClick={() => onHandoff("code", [
                                "Add this page to my website's codebase, matching its framework and structure, and open a PR.",
                                site ? `Website: ${site}` : "",
                                "The page (single-file HTML to adapt):",
                                web.html.slice(0, 20000),
                            ].filter(Boolean).join("\n"))} style={btn}>Build it with Code →</button>
                        )}
                    </div>
                    {view === "preview" ? (
                        // sandboxed without same-origin: the page can't reach this app, its storage or your login
                        <iframe title="Page preview" srcDoc={web.html} sandbox="allow-scripts"
                            style={{ width: "100%", height: "70vh", border: "1px solid var(--border)", borderRadius: "12px", background: "#fff" }} />
                    ) : (
                        <pre style={{ ...field, height: "70vh", overflow: "auto", fontSize: "11px", whiteSpace: "pre-wrap", margin: 0 }}>{web.html}</pre>
                    )}
                    <div style={{ display: "flex", gap: "8px", marginTop: "8px" }}>
                        <input value={change} onChange={e => setChange(e.target.value)} onKeyDown={e => e.key === "Enter" && change.trim() && !busy && makePage(true)}
                            placeholder="Change something, e.g. make the header dark and add a pricing section" style={{ ...field, flex: 1 }} />
                        <button onClick={() => makePage(true)} disabled={!change.trim() || !!busy} style={btn}>Apply</button>
                    </div>
                    {full && (
                        <div role="dialog" aria-label="Page preview" style={{ position: "fixed", inset: 0, zIndex: 200, background: "#fff", display: "flex", flexDirection: "column" }}>
                            <button onClick={() => setFull(false)} style={{ ...btn, borderRadius: 0, border: "none", borderBottom: "1px solid var(--border)" }}>Close preview</button>
                            <iframe title="Page preview full screen" srcDoc={web.html} sandbox="allow-scripts" style={{ flex: 1, border: "none" }} />
                        </div>
                    )}
                    {web.pageModel && <div style={hint}>Made with {web.pageModel}. Pick a bigger model in the top bar for richer pages.</div>}
                </div>
            )}
        </div>
    );
}
