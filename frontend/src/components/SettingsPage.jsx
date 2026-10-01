import { useEffect, useState } from "react";
import { copyToClipboard } from "../utils/clipboard";

const API = import.meta.env.VITE_API_URL || "";

const btn = {
    padding: "7px 12px", borderRadius: "10px", border: "1px solid var(--border)", background: "var(--surface)",
    color: "var(--text)", fontSize: "12px", fontWeight: 600, cursor: "pointer",
};
const field = {
    width: "100%", padding: "8px 10px", borderRadius: "10px", border: "1px solid var(--border)",
    background: "var(--surface)", color: "var(--text)", fontSize: "13px", boxSizing: "border-box",
};
const label = { fontSize: "11px", fontWeight: 600, letterSpacing: "1px", color: "var(--text-muted)", margin: "18px 0 8px" };

function Features({ features }) {
    const groups = [...new Set(features.map(f => f.group))];
    return groups.map(g => (
        <div key={g}>
            <div style={label}>{g.toUpperCase()}</div>
            {features.filter(f => f.group === g).map(f => (
                <div key={f.name} style={{ display: "flex", gap: "10px", alignItems: "baseline", padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
                    <span style={{ color: f.on ? "var(--ready)" : "var(--text-muted)", width: "14px" }}>{f.on ? "✓" : "–"}</span>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: "14px", color: "var(--text)" }}>{f.name}</div>
                        {(f.note || (!f.on && f.enable)) && (
                            <div style={{ fontSize: "11px", color: "var(--text-muted)", wordBreak: "break-word" }}>
                                {!f.on && f.enable ? <>Add <code>{f.enable}</code> as a GitHub secret{f.note ? ` · ${f.note}` : ""}</> : f.note}
                            </div>
                        )}
                    </div>
                </div>
            ))}
        </div>
    ));
}

function McpServers({ headers }) {
    const [servers, setServers] = useState([]);
    const [form, setForm] = useState({ name: "", url: "", auth: "", require_approval: false });
    const [msg, setMsg] = useState("");
    const [busy, setBusy] = useState(false);

    const refresh = () => fetch(`${API}/mcp/servers`, { headers }).then(r => r.json()).then(d => setServers(d.servers || [])).catch(() => {});
    useEffect(() => { refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

    const add = async () => {
        setBusy(true); setMsg("Connecting…");
        const r = await fetch(`${API}/mcp/servers`, { method: "POST", headers, body: JSON.stringify(form) });
        const d = await r.json().catch(() => ({}));
        setMsg(r.ok ? `Connected ${d.name}: ${d.tools.length} tool(s) — ${d.tools.slice(0, 6).join(", ")}` : (d.detail || `Failed (${r.status})`));
        if (r.ok) { setForm({ name: "", url: "", auth: "", require_approval: false }); refresh(); }
        setBusy(false);
    };
    const remove = async (name) => {
        await fetch(`${API}/mcp/servers/${encodeURIComponent(name)}`, { method: "DELETE", headers });
        refresh();
    };

    return (
        <div>
            <div style={label}>MCP SERVERS SEM CAN USE</div>
            <div style={{ fontSize: "12px", color: "var(--text-muted)", marginBottom: "8px" }}>
                Their tools show up in Co-work and Code automatically.
            </div>
            {servers.map(s => (
                <div key={s.name} style={{ display: "flex", alignItems: "center", gap: "8px", padding: "6px 0", borderBottom: "1px solid var(--border)" }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: "14px" }}>{s.name}{s.require_approval ? " · asks first" : ""}</div>
                        <div style={{ fontSize: "11px", color: "var(--text-muted)", overflow: "hidden", textOverflow: "ellipsis" }}>{s.url}{s.auth ? " · token saved" : ""}</div>
                    </div>
                    <button onClick={() => remove(s.name)} style={{ ...btn, color: "var(--danger)" }}>Remove</button>
                </div>
            ))}
            <div style={{ display: "flex", flexDirection: "column", gap: "6px", marginTop: "8px" }}>
                <input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} placeholder="Name, e.g. notion" style={field} />
                <input value={form.url} onChange={e => setForm({ ...form, url: e.target.value })} placeholder="https://… MCP server URL" style={field} />
                <input value={form.auth} onChange={e => setForm({ ...form, auth: e.target.value })} placeholder="Token (optional)" type="password" style={field} />
                <label style={{ fontSize: "12px", display: "flex", gap: "6px", alignItems: "center" }}>
                    <input type="checkbox" checked={form.require_approval} onChange={e => setForm({ ...form, require_approval: e.target.checked })} />
                    Ask me before running its tools
                </label>
                <button onClick={add} disabled={busy || !form.name || !form.url} style={{ ...btn, alignSelf: "flex-start" }}>Add server</button>
                {msg && <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>{msg}</div>}
            </div>
        </div>
    );
}

function ConnectApps({ headers }) {
    const [key, setKey] = useState(null);
    const create = async () => {
        if (!window.confirm("Create a key that lets an app (Claude Code, Cursor…) use SEMBLANCE for a year?")) return;
        const r = await fetch(`${API}/mcp/key`, { method: "POST", headers });
        if (r.ok) setKey(await r.json());
    };
    const Copyable = ({ text }) => (
        <div style={{ position: "relative", marginTop: "6px" }}>
            <pre style={{ ...field, whiteSpace: "pre-wrap", wordBreak: "break-all", fontSize: "11px", margin: 0, paddingRight: "56px" }}>{text}</pre>
            <button onClick={() => copyToClipboard(text)} style={{ ...btn, position: "absolute", top: "4px", right: "4px", padding: "4px 8px" }}>Copy</button>
        </div>
    );
    return (
        <div>
            <div style={label}>USE SEM FROM OTHER APPS (MCP)</div>
            <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>
                Gives Claude Code, Claude Desktop, Cursor or any MCP app Sem's tools: ask, research, co-work, code, images, ads.
            </div>
            {!key && <button onClick={create} style={{ ...btn, marginTop: "8px" }}>Create MCP key</button>}
            {key && (
                <div style={{ fontSize: "12px", marginTop: "8px" }}>
                    <div>Claude Code:</div>
                    <Copyable text={key.claude_code} />
                    <div style={{ marginTop: "8px" }}>Other apps (JSON config):</div>
                    <Copyable text={JSON.stringify(key.json_config, null, 2)} />
                    <div style={{ color: "var(--text-muted)", marginTop: "6px" }}>Shown once. Valid {key.expires_in_days} days; changing SECRET_KEY revokes every key.</div>
                </div>
            )}
        </div>
    );
}

export default function SettingsPage({ token, onBack, onUnauthorized }) {
    const [status, setStatus] = useState(null);
    const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

    useEffect(() => {
        fetch(`${API}/settings/status`, { headers })
            .then(r => { if (r.status === 401) onUnauthorized(); return r.json(); })
            .then(setStatus).catch(() => {});
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    return (
        <div style={{ position: "fixed", inset: 0, background: "var(--bg)", zIndex: 25, display: "flex", flexDirection: "column" }}>
            <div style={{ display: "flex", alignItems: "center", gap: "10px", padding: "14px 16px", borderBottom: "1px solid var(--border)" }}>
                <button onClick={onBack} aria-label="Back" style={{ background: "none", border: "none", cursor: "pointer", fontSize: "18px", color: "var(--text)" }}>←</button>
                <span style={{ fontWeight: 700, color: "var(--text)" }}>Settings</span>
            </div>
            <div style={{ flex: 1, overflowY: "auto", padding: "0 16px 32px" }}>
                <ConnectApps headers={headers} />
                <McpServers headers={headers} />
                {status ? <Features features={status.features} /> : <div style={{ ...label, fontWeight: 400 }}>Loading…</div>}
                {status && (
                    <div style={{ fontSize: "11px", color: "var(--text-muted)", marginTop: "14px" }}>
                        Limits: code {status.limits.code_max_steps} steps · co-work {status.limits.cowork_max_steps} · research {status.limits.research_max_steps} ·
                        {" "}{Math.round(status.limits.agent_timeout_seconds / 60)} min per run. Change with the matching setting (e.g. CODE_MAX_STEPS).
                    </div>
                )}
            </div>
        </div>
    );
}
