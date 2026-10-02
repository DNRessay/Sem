import { useState, useCallback, useRef } from "react";
import { runStream } from "../utils/runs";

export function useStream(baseUrl = "", token = "", onUnauthorized) {
    const [chunks, setChunks] = useState([]);
    const [status, setStatus] = useState(null);
    const [usage, setUsage] = useState(0);
    const [tool, setTool] = useState(null);
    const [streaming, setStreaming] = useState(false);
    const [error, setError] = useState(null);
    const abortRef = useRef(null);

    const send = useCallback(async (message, sessionId = "default", history = [], attachments = [], webSearchEnabled = true, model = "auto", research = false) => {
        setChunks([]);
        setStatus(null);
        setUsage(0);
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
        let titleLocal = null;
        let handoffLocal = null;
        let suggestLocal = null;

        try {
            const onEvent = (parsed) => {
                if (parsed.usage) {
                    setUsage(parsed.usage);
                } else if (parsed.tool) {
                    toolLocal = parsed.tool;
                    setTool(parsed.tool);
                    setStatus(null); // the search/fetch is done — the chip replaces the breadcrumb
                } else if (parsed.suggest_model) {
                    suggestLocal = parsed.suggest_model;
                } else if (parsed.handoff) {
                    handoffLocal = parsed.handoff;
                } else if (parsed.title) {
                    titleLocal = parsed.title;
                } else if (parsed.status) {
                    setStatus(parsed.status);
                } else if (parsed.chunk) {
                    full += parsed.chunk;
                    setChunks(c => [...c, parsed.chunk]);
                    setStatus(null);
                } else if (parsed.type === "error" && parsed.text !== "Stopped.") {
                    setError(parsed.text);
                }
            };
            // runStream keeps the reply coming if the phone locks or switches apps mid-answer: the server
            // finishes it and the missed part is fetched when the page is back (utils/runs.js).
            const r = await runStream("/chat", {
                headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
                body: { message, session_id: sessionId, history, attachments, web_search_enabled: webSearchEnabled, model, research },
                signal: abortRef.current.signal,
                onEvent,
            });
            if (r.status === 401) {
                onUnauthorized?.();
                throw new Error("Session expired — please log in again");
            }
            if (r.error) throw new Error(r.error);
        } catch (e) {
            if (e.name !== "AbortError") setError(e.message);
        } finally {
            setStreaming(false);
        }

        return { reply: full, tool: toolLocal, title: titleLocal, handoff: handoffLocal, suggest: suggestLocal };
    }, [baseUrl, token, onUnauthorized]);

    const abort = useCallback(() => abortRef.current?.abort(), []);

    return { usage, chunks, streaming, error, status, tool, send, abort };
}
