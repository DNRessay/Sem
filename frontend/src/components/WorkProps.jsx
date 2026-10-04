// What Sem is doing, acted out while it works: a laptop when it searches the web, a newspaper for the news, a book
// when it reads files, email, notes or its memory, a palette when it draws, and a thought bubble (hand to head)
// while it's just thinking. Driven by the chat's live status line ("Searching the web…").

export function activityFrom(status, busy) {
    if (!busy) return null;
    const s = (status || "").toLowerCase();
    if (/news|headline/.test(s)) return "newspaper";
    if (/image|picture|draw|paint|design/.test(s)) return "paint";
    if (/search|web|look(ing)? up|research|google|browse|fetch|price|weather|market/.test(s)) return "laptop";
    if (/read|repo|file|document|drive|memory|remember|note|email|gmail|inbox|calendar|reminder|plan|skill/.test(s)) return "book";
    return "thinking";
}

export const ACTIVITY_LABEL = {
    laptop: "Searching…", newspaper: "Reading the news…", book: "Reading…", paint: "Drawing…", thinking: "Thinking…",
};

const CSS = `
@keyframes wp-in { from { opacity: 0; transform: translateY(14px) scale(.9) } to { opacity: 1; transform: none } }
@keyframes wp-type { 0%,100% { opacity: .35 } 50% { opacity: 1 } }
@keyframes wp-line { from { width: 8% } to { width: 78% } }
@keyframes wp-flip { 0% { transform: rotateY(0) } 45%,100% { transform: rotateY(-180deg) } }
@keyframes wp-rustle { 0%,100% { transform: rotate(-2deg) } 50% { transform: rotate(2deg) } }
@keyframes wp-float { 0%,100% { transform: translateY(0) } 50% { transform: translateY(-6px) } }
@keyframes wp-dot { 0%,100% { opacity: .2 } 50% { opacity: 1 } }
@keyframes wp-scratch { 0%,100% { transform: rotate(-14deg) translateY(0) } 50% { transform: rotate(10deg) translateY(-4px) } }
@keyframes wp-stroke { from { stroke-dashoffset: 120 } to { stroke-dashoffset: 0 } }
.wp { animation: wp-in .35s ease-out both; filter: drop-shadow(0 6px 14px rgba(0,0,0,.25)); }
`;

function Laptop() {
    return (
        <svg viewBox="0 0 160 110" width="100%" height="100%" aria-hidden="true">
            <rect x="22" y="8" width="116" height="74" rx="6" fill="#1f2430" stroke="#c9a227" strokeWidth="2" />
            <rect x="30" y="16" width="100" height="58" rx="3" fill="#0e1320" />
            {[0, 1, 2, 3].map(i => (
                <rect key={i} x="36" y={22 + i * 12} height="5" rx="2" fill={i === 0 ? "#f5c542" : "#7aa2ff"}
                    style={{ animation: `wp-line ${1.4 + i * 0.35}s ${i * 0.3}s ease-in-out infinite alternate` }} />
            ))}
            <circle cx="122" cy="68" r="3" fill="#34d399" style={{ animation: "wp-type .8s infinite" }} />
            <path d="M8 84h144l-10 16H18z" fill="#2b3140" stroke="#c9a227" strokeWidth="2" />
            {[0, 1, 2, 3, 4, 5].map(i => (
                <rect key={i} x={36 + i * 15} y="88" width="11" height="4" rx="1" fill="#9aa3b5"
                    style={{ animation: `wp-type ${0.5 + (i % 3) * 0.2}s ${i * 0.11}s infinite` }} />
            ))}
        </svg>
    );
}

function Book() {
    return (
        <svg viewBox="0 0 160 110" width="100%" height="100%" aria-hidden="true" style={{ perspective: "400px" }}>
            <path d="M10 20 Q45 10 80 22 Q115 10 150 20 V98 Q115 88 80 100 Q45 88 10 98z" fill="#7a4b1f" />
            <path d="M16 22 Q46 14 79 25 V94 Q46 84 16 92z" fill="#fbf6e9" />
            <path d="M81 25 Q114 14 144 22 V92 Q114 84 81 94z" fill="#fbf6e9" />
            {[0, 1, 2, 3, 4].map(i => <rect key={i} x="24" y={34 + i * 11} width="46" height="3" rx="1" fill="#c9bfa5" />)}
            {[0, 1, 2, 3, 4].map(i => <rect key={i} x="90" y={34 + i * 11} width="46" height="3" rx="1" fill="#c9bfa5" />)}
            <g style={{ transformOrigin: "80px 60px", transformBox: "view-box", animation: "wp-flip 2.4s ease-in-out infinite" }}>
                <path d="M81 25 Q114 14 144 22 V92 Q114 84 81 94z" fill="#fffdf6" stroke="#e7dcc0" />
            </g>
        </svg>
    );
}

function Newspaper() {
    return (
        <svg viewBox="0 0 160 110" width="100%" height="100%" aria-hidden="true">
            <g style={{ transformOrigin: "80px 100px", animation: "wp-rustle 1.6s ease-in-out infinite" }}>
                <rect x="14" y="8" width="132" height="94" rx="3" fill="#f3f1ea" stroke="#9c9a92" />
                <rect x="22" y="14" width="116" height="12" fill="#222" />
                <text x="80" y="24" textAnchor="middle" fontSize="9" fontFamily="Georgia, serif" fill="#fff">THE DAILY SEM</text>
                <rect x="22" y="32" width="52" height="34" fill="#cfcabd" />
                {[0, 1, 2, 3, 4].map(i => <rect key={i} x="80" y={33 + i * 7} width="58" height="3" fill="#8c887d" />)}
                {[0, 1, 2, 3].map(i => <rect key={i} x="22" y={72 + i * 7} width="116" height="3" fill="#8c887d" />)}
                <line x1="80" y1="8" x2="80" y2="102" stroke="#d9d5ca" />
            </g>
        </svg>
    );
}

function Palette() {
    return (
        <svg viewBox="0 0 160 110" width="100%" height="100%" aria-hidden="true">
            <path d="M30 60 C30 25 90 10 120 30 C145 47 130 70 112 66 C100 64 104 82 92 90 C70 104 30 92 30 60z" fill="#e8d3a8" stroke="#a3824a" strokeWidth="2" />
            {[["#e74c3c", 56, 42], ["#f1c40f", 78, 32], ["#2ecc71", 102, 38], ["#3498db", 52, 66]].map(([c, x, y], i) => (
                <circle key={i} cx={x} cy={y} r="8" fill={c} style={{ animation: `wp-type 1.2s ${i * 0.2}s infinite` }} />
            ))}
            <path d="M70 80 q20 -18 46 -4" fill="none" stroke="#9b59b6" strokeWidth="5" strokeLinecap="round" strokeDasharray="120"
                style={{ animation: "wp-stroke 1.4s ease-in-out infinite alternate" }} />
        </svg>
    );
}

function Thinking() {
    return (
        <svg viewBox="0 0 160 110" width="100%" height="100%" aria-hidden="true">
            <g style={{ animation: "wp-float 2.2s ease-in-out infinite" }}>
                <ellipse cx="96" cy="38" rx="52" ry="30" fill="#fff" stroke="#c9a227" strokeWidth="2" />
                <circle cx="44" cy="74" r="8" fill="#fff" stroke="#c9a227" strokeWidth="2" />
                <circle cx="30" cy="92" r="5" fill="#fff" stroke="#c9a227" strokeWidth="2" />
                {[0, 1, 2].map(i => <circle key={i} cx={76 + i * 20} cy="38" r="6" fill="#c9a227" style={{ animation: `wp-dot 1.2s ${i * 0.25}s infinite` }} />)}
            </g>
            <text x="140" y="100" fontSize="30" style={{ transformOrigin: "140px 92px", animation: "wp-scratch .9s ease-in-out infinite" }}>🤔</text>
        </svg>
    );
}

const PROPS = { laptop: Laptop, book: Book, newspaper: Newspaper, paint: Palette, thinking: Thinking };

// The prop itself; place it over the avatar's hands (or beside the orb).
export default function WorkProp({ kind, size = 150, style }) {
    const Prop = PROPS[kind];
    if (!Prop) return null;
    return (
        <div className="wp" key={kind} role="img" aria-label={ACTIVITY_LABEL[kind]} style={{ width: size, height: size * 0.7, ...style }}>
            <style>{CSS}</style>
            <Prop />
        </div>
    );
}
