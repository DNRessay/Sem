import { useState } from "react";
import ChatWindow from "./components/ChatWindow";
import StatusBar from "./components/StatusBar";
import Drawer from "./components/Drawer";

function newSessionId() {
    return `session_${Date.now()}`;
}

export default function App() {
    const [streaming, setStreaming] = useState(false);
    const [sessionId, setSessionId] = useState(newSessionId());
    const [initialHistory, setInitialHistory] = useState([]);
    const [menuOpen, setMenuOpen] = useState(false);

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

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "var(--bg)" }}>
            <StatusBar sessionId={sessionId} streaming={streaming} onMenu={() => setMenuOpen(true)} />
            <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
                <ChatWindow
                    key={sessionId}
                    sessionId={sessionId}
                    initialHistory={initialHistory}
                    onStreamChange={setStreaming}
                />
            </div>
            <Drawer
                open={menuOpen}
                onClose={() => setMenuOpen(false)}
                currentSessionId={sessionId}
                onNewChat={startNewChat}
                onOpenSession={openSession}
            />
        </div>
    );
}
