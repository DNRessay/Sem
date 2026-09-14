import { useState, useEffect, useRef } from "react";
import ChatWindow from "./components/ChatWindow";
import StatusBar from "./components/StatusBar";
import Drawer from "./components/Drawer";
import Login from "./components/Login";
import { turnsToHistory } from "./utils/toolMarker";

const API = import.meta.env.VITE_API_URL || "";
const TOKEN_KEY = "semblance_token";
const SESSION_KEY = "semblance_session_id";

function newSessionId() {
    return `session_${Date.now()}`;
}

export default function App() {
    const [streaming, setStreaming] = useState(false);
    const [sessionId, setSessionId] = useState(() => {
        try {
            return localStorage.getItem(SESSION_KEY) || newSessionId();
        } catch {
            return newSessionId();
        }
    });
    const [initialHistory, setInitialHistory] = useState([]);
    const [menuOpen, setMenuOpen] = useState(false);
    const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || "");
    const [restoring, setRestoring] = useState(true);
    const sessionIdRef = useRef(sessionId);

    useEffect(() => {
        sessionIdRef.current = sessionId;
        try {
            localStorage.setItem(SESSION_KEY, sessionId);
        } catch {}
    }, [sessionId]);

    // Reloading the page used to drop straight into a brand-new session with
    // no history — sessionId was regenerated fresh on every mount with no
    // persistence at all. Now the id survives a reload (above), and this
    // restores that session's actual messages once, on login/mount, instead
    // of silently landing on the same id but empty.
    useEffect(() => {
        if (!token) { setRestoring(false); return; }
        const restoringId = sessionId;
        let cancelled = false;
        fetch(`${API}/history/${restoringId}`, { headers: { Authorization: `Bearer ${token}` } })
            .then(r => (r.ok ? r.json() : { turns: [] }))
            .then(data => {
                if (cancelled || sessionIdRef.current !== restoringId) return;
                setInitialHistory(turnsToHistory(data.turns));
            })
            .catch(() => {})
            .finally(() => { if (!cancelled) setRestoring(false); });
        return () => { cancelled = true; };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [token]);

    const logout = () => {
        localStorage.removeItem(TOKEN_KEY);
        setToken("");
    };

    const handleLoggedIn = (t) => {
        localStorage.setItem(TOKEN_KEY, t);
        setToken(t);
    };

    const startNewChat = () => {
        setSessionId(newSessionId());
        setInitialHistory([]);
        setMenuOpen(false);
        setRestoring(false);
    };

    const openSession = (id, turns) => {
        setSessionId(id);
        setInitialHistory(turnsToHistory(turns));
        setMenuOpen(false);
        setRestoring(false);
    };

    if (!token) {
        return (
            <div className="app-shell" style={{ display: "flex", flexDirection: "column", background: "var(--bg)" }}>
                <Login onLoggedIn={handleLoggedIn} />
            </div>
        );
    }

    return (
        <div className="app-shell" style={{ display: "flex", flexDirection: "column", background: "var(--bg)" }}>
            <StatusBar sessionId={sessionId} streaming={streaming} onMenu={() => setMenuOpen(true)} />
            <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
                {!restoring && (
                    <ChatWindow
                        key={sessionId}
                        sessionId={sessionId}
                        initialHistory={initialHistory}
                        onStreamChange={setStreaming}
                        onNewChat={startNewChat}
                        token={token}
                        onUnauthorized={logout}
                    />
                )}
            </div>
            <Drawer
                open={menuOpen}
                onClose={() => setMenuOpen(false)}
                currentSessionId={sessionId}
                onNewChat={startNewChat}
                onOpenSession={openSession}
                token={token}
                onLogout={logout}
            />
        </div>
    );
}
