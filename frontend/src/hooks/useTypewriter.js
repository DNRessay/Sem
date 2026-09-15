import { useEffect, useRef, useState } from "react";

// Reveals `fullText` gradually instead of the raw text popping in the
// instant it arrives — noticeable two ways: a cache hit (useStream/
// query_engine.stream_llm yields the whole cached reply as one chunk) and
// a tool-driven reply (_bypass_with_reply streams ~400-char chunks as fast
// as the network allows) both used to dump a wall of text in one frame,
// which read as a burst of output rather than something being "said."
// Two-speed pace: an ordinary reply reveals at a fixed, readable typing
// rate (baseCharsPerTick per tick) so it visibly "types" rather than
// snapping in; a genuinely large backlog (a cache hit on a long reply, a
// repo/web dump) switches to a proportional catch-up above
// catchUpThreshold so a multi-thousand-character dump doesn't take a
// minute to finish revealing. Ordinary token-by-token streaming is
// already slower than the base rate most of the time, so this only ever
// slows down bursts, never the real stream.
export function useTypewriter(fullText, { tickMs = 26, baseCharsPerTick = 2, catchUpThreshold = 400, catchUpFraction = 0.12 } = {}) {
    const [revealed, setRevealed] = useState("");
    const fullRef = useRef(fullText);
    fullRef.current = fullText;

    // A brand-new message resets fullText to "" (useStream.send clears
    // `chunks` at the start of every call) before the first chunk of the
    // next reply arrives — that's the signal to start this message's
    // reveal over from scratch rather than carrying over stale progress.
    useEffect(() => {
        if (fullText.length === 0) setRevealed("");
    }, [fullText.length === 0]);

    useEffect(() => {
        const id = setInterval(() => {
            setRevealed(r => {
                const target = fullRef.current;
                const remaining = target.length - r.length;
                if (remaining <= 0) return r;
                const step = remaining > catchUpThreshold
                    ? Math.ceil(remaining * catchUpFraction)
                    : baseCharsPerTick;
                return target.slice(0, r.length + step);
            });
        }, tickMs);
        return () => clearInterval(id);
    }, [tickMs, baseCharsPerTick, catchUpThreshold, catchUpFraction]);

    return revealed;
}
