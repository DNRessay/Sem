import { useState, useCallback, useRef } from "react";

export function useStream(baseUrl = "", token = "", onUnauthorized) {
    const [chunks, setChunks] = useState([]);
    const [status, setStatus] = useState(null);
    const [tool, setTool] = useState(null);
    const [streaming, setStreaming] = useState(false);
    const [error, setError] = useState(null);
    const abortRef = useRef(null);

    const send = useCallback(async (message, sessionId = "default", history = [], attachments = []) => {
        setChunks([]);
        setStatus(null);
        setTool(null);
        setError(null);
        setStreaming(true);
        abortRef.current = new AbortController();

        // Built locally rather than read back from state: state updates are
        // async, so a caller awaiting send() and then reading state would
        // see stale (often empty) values. Returning the accumulated result
        // directly is the only way to get the *final* response reliably.
        let full = "";
        let toolLocal = null;

        try {
            const res = await fetch(`${baseUrl}/chat`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    ...(token ? { Authorization: `Bearer ${token}` } : {}),
                },
                body: JSON.stringify({ message, session_id: sessionId, history, attachments }),
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
            // A tool event's `detail` can carry many KB of fetched/searched
            // text, easily spanning more than one network chunk — reading
            // one chunk at a time and splitting it in isolation (the
            // previous version) silently truncated/dropped any SSE line
            // that landed across a chunk boundary. Buffering across reads
            // and only processing complete lines (keeping the trailing
            // partial one for the next read) is the standard fix.
            let buffer = "";

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split("\n");
                buffer = lines.pop() ?? "";
                for (const line of lines) {
                    if (!line.startsWith("data: ")) continue;
                    const data = line.slice(6);
                    if (data === "[DONE]") continue;
                    try {
                        const parsed = JSON.parse(data);
                        if (parsed.tool) {
                            toolLocal = parsed.tool;
                            setTool(parsed.tool);
                            setStatus(null); // the search/fetch is done — the chip replaces the breadcrumb
                        } else if (parsed.status) {
                            setStatus(parsed.status);
                        } else if (parsed.chunk) {
                            full += parsed.chunk;
                            setChunks(c => [...c, parsed.chunk]);
                            setStatus(null);
                        }
                    } catch {}
                }
            }
        } catch (e) {
            if (e.name !== "AbortError") setError(e.message);
        } finally {
            setStreaming(false);
        }

        return { reply: full, tool: toolLocal };
    }, [baseUrl, token, onUnauthorized]);

    const abort = useCallback(() => abortRef.current?.abort(), []);

    return { chunks, streaming, error, status, tool, send, abort };
}
