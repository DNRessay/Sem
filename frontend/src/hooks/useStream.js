import { useState, useCallback, useRef } from "react";

export function useStream(baseUrl = "") {
    const [chunks, setChunks] = useState([]);
    const [streaming, setStreaming] = useState(false);
    const [error, setError] = useState(null);
    const abortRef = useRef(null);

    const send = useCallback(async (message, sessionId = "default", history = []) => {
        setChunks([]);
        setError(null);
        setStreaming(true);
        abortRef.current = new AbortController();

        try {
            const res = await fetch(`${baseUrl}/chat`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message, session_id: sessionId, history }),
                signal: abortRef.current.signal,
            });

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
                            if (parsed.chunk) setChunks(c => [...c, parsed.chunk]);
                        } catch {}
                    }
                }
            }
        } catch (e) {
            if (e.name !== "AbortError") setError(e.message);
        } finally {
            setStreaming(false);
        }
    }, [baseUrl]);

    const abort = useCallback(() => abortRef.current?.abort(), []);

    return { chunks, streaming, error, send, abort };
}