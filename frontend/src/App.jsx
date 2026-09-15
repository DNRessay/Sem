import { useState, useEffect, useRef } from "react";
import ChatWindow from "./components/ChatWindow";
import StatusBar from "./components/StatusBar";
import Drawer from "./components/Drawer";
import AgentFeedPanel from "./components/AgentFeedPanel";
import AllChatsPage from "./components/AllChatsPage";
import Login from "./components/Login";
import ErrorBoundary from "./components/ErrorBoundary";
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
    const [sessionTitle, setSessionTitle] = useState("");
    const [menuOpen, setMenuOpen] = useState(false);
    const [agentFeedOpen, setAgentFeedOpen] = useState(false);
    const [view, setView] = useState("chat"); // "chat" | "allChats"
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
                setSessionTitle(data.title || "");
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
        setSessionTitle("");
        setMenuOpen(false);
        setRestoring(false);
    };

    const openSession = (id, turns, title) => {
        setSessionId(id);
        setInitialHistory(turnsToHistory(turns));
        setSessionTitle(title || "");
        setMenuOpen(false);
        setView("chat");
        setRestoring(false);
    };

    // Only applied if the title's session is still the one showing — a
    // slow title-generation response landing after the user already
    // switched sessions shouldn't overwrite what's on screen.
    const handleTitle = (id, title) => {
        if (id === sessionIdRef.current) setSessionTitle(title);
    };

    // A rename/delete can happen to the session currently on screen (from
    // either Drawer's recent-5 list or the full AllChatsPage) — this keeps
    // the header and chat area in sync with whatever the list did.
    const handleSessionRenamed = (id, title) => {
        if (id === sessionIdRef.current) setSessionTitle(title);
    };

    const handleSessionDeleted = (id) => {
        if (id === sessionIdRef.current) startNewChat();
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
            <StatusBar
                sessionId={sessionId}
                title={sessionTitle}
                streaming={streaming}
                onMenu={() => setMenuOpen(true)}
                onTitleClick={startNewChat}
                onFeed={() => setAgentFeedOpen(true)}
            />
            <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
                {!restoring && (
                    <ErrorBoundary key={sessionId}>
                        <ChatWindow
                            sessionId={sessionId}
                            initialHistory={initialHistory}
                            onStreamChange={setStreaming}
                            onNewChat={startNewChat}
                            onTitle={handleTitle}
                            token={token}
                            onUnauthorized={logout}
                        />
                    </ErrorBoundary>
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
                onViewAllChats={() => { setMenuOpen(false); setView("allChats"); }}
                onSessionRenamed={handleSessionRenamed}
                onSessionDeleted={handleSessionDeleted}
            />
            <AgentFeedPanel
                open={agentFeedOpen}
                onClose={() => setAgentFeedOpen(false)}
                sessionId={sessionId}
                token={token}
            />
            {view === "allChats" && (
                <AllChatsPage
                    token={token}
                    currentSessionId={sessionId}
                    onOpenSession={openSession}
                    onBack={() => setView("chat")}
                    onLogout={logout}
                    onSessionRenamed={handleSessionRenamed}
                    onSessionDeleted={handleSessionDeleted}
                />
            )}
        </div>
    );
}
