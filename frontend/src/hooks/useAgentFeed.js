import { useCallback, useEffect, useRef, useState } from "react";

const API = import.meta.env.VITE_API_URL || "";

// Lifted out of AgentFeed.jsx so both the feed panel (renders the list) and
// StatusBar (renders the error dot on the lightning bolt) share one poller
// instead of two separately drifting ones. Polls /status/{id}/events?since=
// — every event since the last one seen, not just the single latest one
// /status alone returns, so a burst of several tool calls within one turn
// (a memory search followed by a web search, say) isn't dropped between 3s
// polls the way it used to be.
export default function useAgentFeed(sessionId, token) {
    const [events, setEvents] = useState([]);
    const [hasError, setHasError] = useState(false);
    const cursorRef = useRef(0);

    // A new session has its own event history — start the cursor over so
    // the first poll fetches from the beginning instead of picking up
    // wherever the previous session's cursor happened to land.
    useEffect(() => {
        cursorRef.current = 0;
        setEvents([]);
        setHasError(false);
    }, [sessionId]);

    useEffect(() => {
        if (!token) return;
        let cancelled = false;
        const poll = async () => {
            try {
                const r = await fetch(`${API}/status/${sessionId}/events?since=${cursorRef.current}`, {
                    headers: token ? { Authorization: `Bearer ${token}` } : {},
                });
                const data = await r.json();
                const fresh = data.events || [];
                if (cancelled || fresh.length === 0) return;
                cursorRef.current = fresh[fresh.length - 1].id;
                if (fresh.some(e => (e.action || "").startsWith("blocked:"))) setHasError(true);
                setEvents(prev => [...fresh].reverse().concat(prev).slice(0, 50));
            } catch {}
        };
        poll();
        const interval = setInterval(poll, 3000);
        return () => { cancelled = true; clearInterval(interval); };
    }, [sessionId, token]);

    // Called when the user opens the feed panel — seeing what went wrong
    // is the acknowledgment; the dot shouldn't keep showing after that.
    const acknowledgeErrors = useCallback(() => setHasError(false), []);

    return { events, hasError, acknowledgeErrors };
}
