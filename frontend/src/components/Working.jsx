import { useEffect, useRef, useState } from "react";

const WORDS = ["Thinking", "Pondering", "Mulling it over", "Sleuthing", "Working on it", "Piecing it together"];

// Sem's "working" mark: a shiny gold S with a light sweep, gently breathing.
export function GoldS({ size = 21 }) {
    return (
        <svg className="sem-s" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" style={{ flexShrink: 0, display: "block" }}>
            <defs>
                <linearGradient id="semSGold" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0" stopColor="#fff3b0" />
                    <stop offset="0.35" stopColor="#ffd34d" />
                    <stop offset="0.7" stopColor="#f5b800" />
                    <stop offset="1" stopColor="#c98a00" />
                </linearGradient>
                <linearGradient id="semSShine" x1="0" y1="0" x2="1" y2="0">
                    <stop offset="0" stopColor="#fff" stopOpacity="0" />
                    <stop offset="0.5" stopColor="#fff" stopOpacity="0.9" />
                    <stop offset="1" stopColor="#fff" stopOpacity="0" />
                    <animateTransform attributeName="gradientTransform" type="translate" values="-1 0; 1 0" dur="1.6s" repeatCount="indefinite" />
                </linearGradient>
            </defs>
            <text x="12" y="19" textAnchor="middle" fontSize="22" fontWeight="800" fontFamily="Georgia, 'Times New Roman', serif" fill="url(#semSGold)">S</text>
            <text x="12" y="19" textAnchor="middle" fontSize="22" fontWeight="800" fontFamily="Georgia, 'Times New Roman', serif" fill="url(#semSShine)">S</text>
        </svg>
    );
}

// One clock per wait, reset only when a new wait starts.
export function useElapsedSeconds(active) {
    const [elapsed, setElapsed] = useState(0);
    const startRef = useRef(null);
    useEffect(() => {
        if (!active) return;
        startRef.current = Date.now();
        setElapsed(0);
        const id = setInterval(() => setElapsed(Math.round((Date.now() - startRef.current) / 1000)), 1000);
        return () => clearInterval(id);
    }, [active]);
    return elapsed;
}

export function formatTokens(n) {
    if (!n) return "";
    return n >= 1000 ? `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}k tokens` : `${n} tokens`;
}

// "[S] 12s · 1.2k tokens · Pondering…" — `status` replaces the rotating word (e.g. "Searching the web").
export function WorkingLine({ elapsed, status, icon, tokens }) {
    const [i, setI] = useState(0);
    useEffect(() => {
        const id = setInterval(() => setI(v => (v + 1) % WORDS.length), 1100);
        return () => clearInterval(id);
    }, []);
    return (
        <span style={{ display: "inline-flex", alignItems: "center", gap: "6px", color: "var(--text-muted)", fontSize: "14px", margin: "8px 0" }}>
            <GoldS />
            {icon}
            {elapsed}s{tokens ? ` · ${formatTokens(tokens)}` : ""} · {status || `${WORDS[i]}…`}
        </span>
    );
}

// For tabs: a self-timing working line shown while `active`.
export function TabWorking({ active, status, tokens }) {
    const elapsed = useElapsedSeconds(!!active);
    if (!active) return null;
    return <div><WorkingLine elapsed={elapsed} status={status} tokens={tokens} /></div>;
}
