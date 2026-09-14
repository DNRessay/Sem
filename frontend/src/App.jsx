import { useState } from "react";
import ChatWindow from "./components/ChatWindow";
import StatusBar from "./components/StatusBar";
import Drawer from "./components/Drawer";
import Login from "./components/Login";

const TOKEN_KEY = "semblance_token";

function newSessionId() {
    return `session_${Date.now()}`;
}

export default function App() {
    const [streaming, setStreaming] = useState(false);
    const [sessionId, setSessionId] = useState(newSessionId());
    const [initialHistory, setInitialHistory] = useState([]);
    const [menuOpen, setMenuOpen] = useState(false);
    const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY) || "");

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
    };

    const openSession = (id, turns) => {
        setSessionId(id);
        setInitialHistory(turns.map(t => ({ role: t.role, content: t.content })));
        setMenuOpen(false);
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
                <ChatWindow
                    key={sessionId}
                    sessionId={sessionId}
                    initialHistory={initialHistory}
                    onStreamChange={setStreaming}
                    onNewChat={startNewChat}
                    token={token}
                    onUnauthorized={logout}
                />
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
