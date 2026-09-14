import { Component } from "react";

// Without this, an uncaught error anywhere in the chat's render (a bad SSE
// payload, a markdown edge case, anything) unmounts the whole React tree —
// the entire page goes blank with no way back except a manual reload. This
// catches it and shows something recoverable instead; messages are already
// safe server-side, so reloading brings the conversation right back.
export default class ErrorBoundary extends Component {
    constructor(props) {
        super(props);
        this.state = { error: null };
    }

    static getDerivedStateFromError(error) {
        return { error };
    }

    componentDidCatch(error, info) {
        console.error("SEMBLANCE UI crashed:", error, info);
    }

    render() {
        if (this.state.error) {
            return (
                <div style={{
                    display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
                    flex: 1, gap: "12px", padding: "24px", textAlign: "center", color: "var(--text)",
                }}>
                    <div style={{ fontSize: "15px" }}>Something went wrong displaying this chat.</div>
                    <div style={{ fontSize: "12px", color: "var(--text-muted)" }}>
                        Your messages are saved — reloading will bring them back.
                    </div>
                    <button
                        onClick={() => window.location.reload()}
                        style={{
                            padding: "8px 16px", borderRadius: "8px", border: "none",
                            background: "var(--accent)", color: "var(--accent-contrast)",
                            fontSize: "13px", fontWeight: "600", cursor: "pointer",
                        }}
                    >
                        Reload
                    </button>
                </div>
            );
        }
        return this.props.children;
    }
}
