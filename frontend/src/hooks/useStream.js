import { useState, useCallback, useRef } from "react";

export function useStream(baseUrl = "", token = "", onUnauthorized) {
    const [chunks, setChunks] = useState([]);
    const [streaming, setStreaming] = useState(false);
    const [error, setError] = useState(null);
    const abortRef = useRef(null);

    const send = useCallback(async (message, sessionId = "default", history = []) => {
        setChunks([]);
        setError(null);
        setStreaming(true);
        abortRef.current = new AbortController();

        // Built locally rather than read back from state: state updates are
        // async, so a caller awaiting send() and then reading `chunks` would
        // see a stale (often empty) value. Returning the accumulated string
        // directly is the only way to get the *final* response reliably.
        let full = "";

        try {
            const res = await fetch(`${baseUrl}/chat`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {}),
                },
                body: JSON.stringify({ message, session_id: sessionId, history }),
                signal: abortRef.current.signal,
            });

            if (res.status === 401) {
                onUnauthorized?.();
                throw new Error("Session expired — please log in again");
            }
            if (!res.ok || !res.body) {
                throw new Error(`Request failed: ${res.status}`);
            }

            const reader = res.body.getReader();
            const decoder = new TextDecoder();

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                const lines = decoder.decode(value).split("\n").filter(Boolean);
                for (const line of lines) {
                    if (line.startsWith("data: ")) {
                        const data = line.slice(6);
                        if (data === "[DONE]") break;
                        try {
                            const parsed = JSON.parse(data);
                            if (parsed.chunk) {
                                full += parsed.chunk;
                                setChunks(c => [...c, parsed.chunk]);
                            }
                        } catch {}
                    }
                }
            }
        } catch (e) {
            if (e.name !== "AbortError") setError(e.message);
        } finally {
            setStreaming(false);
        }

        return full;
    }, [baseUrl, token, onUnauthorized]);

    const abort = useCallback(() => abortRef.current?.abort(), []);

    return { chunks, streaming, error, send, abort };
}
