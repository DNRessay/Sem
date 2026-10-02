import { useEffect } from "react";
import { readLines } from "./sse";

// Agent runs that survive the phone locking or switching apps. The server keeps a run going after the
// connection drops and saves every event (pipeline/runs.py); here we stream live, and whenever the stream
// breaks or the page comes back into view we fetch what we missed from /runs/{id}. Events reach onEvent
// exactly once, in order.

const API = import.meta.env.VITE_API_URL || "";
const POLL_MS = 1500;
const PAGE = 100;
const LOST = { type: "error", text: "This run was interrupted before it finished. Send it again to retry." };
const active = new Set(); // runs this page is already following, so a remount doesn't follow twice
const sleep = ms => new Promise(r => setTimeout(r, ms));

export function newRunId() {
    return (globalThis.crypto?.randomUUID?.() || `${Date.now()}${Math.random().toString(36).slice(2)}`).replace(/-/g, "");
}

async function follow(runId, state, headers, onEvent, lostEvent) {
    let missing = 0;
    while (!state.finished && !state.stopped) {
        let d = null;
        try {
            const r = await fetch(`${API}/runs/${runId}?after=${state.seq}`, { headers });
            if (r.status === 404) {
                // Not recorded (yet): the request may still be landing, or the server couldn't save it.
                if (++missing >= 4) { state.finished = true; state.unknown = true; break; }
            } else if (r.ok) d = await r.json();
        } catch { /* offline for now: keep trying */ }
        if (!d) { await sleep(POLL_MS); continue; }
        for (const e of d.events) {
            if (e.seq <= state.seq || state.stopped) continue;
            state.seq = e.seq;
            state.onSeq?.(e.seq);
            onEvent(e.event);
        }
        if (d.events.length >= PAGE) continue;
        if (d.status !== "running") {
            if (d.status === "lost" && lostEvent) onEvent(lostEvent);
            state.finished = true;
        } else await sleep(POLL_MS);
    }
}

// POSTs body (plus a run_id) to path and streams the run. Returns { status, error } like a response check:
// status 401 → log in again; error → show it. A user abort (signal) cancels the run on the server too and
// rethrows AbortError. onRun(runId, seq) fires as events arrive, for saving progress with the chat.
export async function runStream(path, { headers, body, signal, onEvent, onRun, lostEvent = LOST }) {
    const runId = body.run_id || newRunId();
    const state = { seq: 0, finished: false, stopped: false, onSeq: seq => onRun?.(runId, seq) };
    const ctrl = new AbortController();
    let follower = null, started = false;
    const startFollow = () => {
        if (follower || state.finished || state.stopped) return;
        follower = follow(runId, state, headers, onEvent, lostEvent).finally(() => {
            follower = null;
            if (state.finished) ctrl.abort(); // unblock a live read that silently died
        });
    };
    const onAbort = () => {
        state.stopped = true;
        ctrl.abort();
        fetch(`${API}/runs/${runId}/cancel`, { method: "POST", headers }).catch(() => {});
    };
    const onVisible = () => { if (started && document.visibilityState === "visible") startFollow(); };
    const cleanup = () => {
        active.delete(runId);
        signal?.removeEventListener("abort", onAbort);
        document.removeEventListener("visibilitychange", onVisible);
    };
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    signal?.addEventListener("abort", onAbort);
    document.addEventListener("visibilitychange", onVisible);
    active.add(runId);
    onRun?.(runId, 0);

    try {
        let res = null;
        try {
            res = await fetch(`${API}${path}`, { method: "POST", headers, signal: ctrl.signal, body: JSON.stringify({ ...body, run_id: runId }) });
        } catch (e) {
            if (state.stopped) throw e;
        }
        started = true;
        if (res && (!res.ok || !res.body)) {
            const d = await res.json().catch(() => ({}));
            state.finished = true;
            return { status: res.status, error: typeof d.detail === "string" ? d.detail : `Request failed: ${res.status}` };
        }
        if (res) {
            let live = 0;
            try {
                await readLines(res, (line) => {
                    if (line === "data: [DONE]") { state.finished = true; return; }
                    if (!line.startsWith("data: ")) return;
                    live += 1;
                    if (live !== state.seq + 1 || state.stopped) return; // already delivered by the follower
                    state.seq = live;
                    state.onSeq(live);
                    try { onEvent(JSON.parse(line.slice(6))); } catch { /* skip a malformed event */ }
                });
            } catch (e) {
                if (state.stopped) throw e;
            }
        }
        // The stream ended early (connection dropped, or the request never got an answer): catch up.
        if (!state.finished && !state.stopped) startFollow();
        while (follower) await follower;
        if (state.stopped) throw new DOMException("Aborted", "AbortError");
        if (state.unknown && state.seq === 0) return { status: 0, error: "Couldn't reach SEMBLANCE. Check your connection and send it again." };
        return { status: 200 };
    } finally {
        cleanup();
    }
}

// Picks a chat's unfinished run back up after the page was reloaded (Android discards background tabs).
// pending is { id, seq } as saved by onRun; apply(event) handles one event; done() runs at the end.
export function useResumeRun(chatId, pending, { headers, apply, onStart, onSeq, done, lostEvent = LOST }) {
    useEffect(() => {
        if (!pending?.id || active.has(pending.id)) return;
        const state = { seq: pending.seq || 0, finished: false, stopped: false, onSeq };
        active.add(pending.id);
        onStart?.();
        follow(pending.id, state, headers, apply, lostEvent).finally(() => {
            active.delete(pending.id);
            if (!state.stopped) done?.();
        });
        return () => { state.stopped = true; active.delete(pending.id); };
    }, [chatId, pending?.id]); // eslint-disable-line react-hooks/exhaustive-deps
}
