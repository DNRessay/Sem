import { useState } from "react";
import ChatWindow from "./components/ChatWindow";
import AgentFeed from "./components/AgentFeed";
import StatusBar from "./components/StatusBar";

const SESSION = `session_${Date.now()}`;

export default function App() {
    const [streaming, setStreaming] = useState(false);

    return (
        <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "var(--bg)" }}>
            <StatusBar sessionId={SESSION} streaming={streaming} />
            <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>
                <ChatWindow sessionId={SESSION} onStreamChange={setStreaming} />
                <AgentFeed sessionId={SESSION} />
            </div>
        </div>
    );
}
