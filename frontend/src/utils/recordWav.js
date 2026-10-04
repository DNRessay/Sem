// Records one utterance from the mic as a 16 kHz mono WAV (what Whistle reads), for browsers without built-in
// speech recognition. Ends by itself after a short silence once you've spoken, or when stop() is called.
const API = import.meta.env.VITE_API_URL || "";
const TARGET_RATE = 16000;

export const canRecord = () => !!(navigator.mediaDevices?.getUserMedia && (window.AudioContext || window.webkitAudioContext));

function downsample(chunks, from) {
    const total = chunks.reduce((n, c) => n + c.length, 0);
    const input = new Float32Array(total);
    let o = 0;
    for (const c of chunks) { input.set(c, o); o += c.length; }
    if (from === TARGET_RATE) return input;
    const ratio = from / TARGET_RATE, out = new Float32Array(Math.floor(total / ratio));
    for (let i = 0; i < out.length; i++) {
        const x = i * ratio, j = Math.floor(x), f = x - j;
        out[i] = input[j] * (1 - f) + (input[j + 1] ?? input[j]) * f;
    }
    return out;
}

function wavBase64(samples) {
    const buf = new ArrayBuffer(44 + samples.length * 2), v = new DataView(buf);
    const str = (at, s) => [...s].forEach((ch, i) => v.setUint8(at + i, ch.charCodeAt(0)));
    str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVEfmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, TARGET_RATE, true); v.setUint32(28, TARGET_RATE * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    str(36, "data"); v.setUint32(40, samples.length * 2, true);
    for (let i = 0; i < samples.length; i++) v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, samples[i])) * 0x7fff, true);
    let bin = "";
    const bytes = new Uint8Array(buf);
    for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(bin);
}

// { stop(), abort(), done: Promise<base64 WAV | ""> } — "" when nothing was said or it was aborted.
export function recordUtterance({ silenceMs = 700, maxMs = 28000, waitMs = 8000, autoStop = true, onLevel } = {}) {
    let finish;
    const done = new Promise(resolve => { finish = resolve; });
    const state = { chunks: [], spoke: false, quietSince: 0, aborted: false, ended: false, cleanup: () => {} };
    const end = () => {
        if (state.ended) return;
        state.ended = true;
        const rate = state.rate;
        state.cleanup();
        finish(state.aborted || !state.spoke || !rate ? "" : wavBase64(downsample(state.chunks, rate)));
    };
    (async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
            const ac = new (window.AudioContext || window.webkitAudioContext)();
            const src = ac.createMediaStreamSource(stream);
            const node = ac.createScriptProcessor(4096, 1, 1);
            state.rate = ac.sampleRate;
            const started = Date.now();
            node.onaudioprocess = (e) => {
                if (state.ended) return;
                const data = e.inputBuffer.getChannelData(0);
                state.chunks.push(new Float32Array(data));
                let sum = 0;
                for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
                const rms = Math.sqrt(sum / data.length), now = Date.now();
                onLevel?.(rms);
                if (rms > 0.02) { state.spoke = true; state.quietSince = 0; } else if (!state.quietSince) state.quietSince = now;
                if (now - started > maxMs) end();
                else if (autoStop && state.spoke && state.quietSince && now - state.quietSince > silenceMs) end();
                else if (autoStop && !state.spoke && now - started > waitMs) end();
            };
            src.connect(node); node.connect(ac.destination);
            state.cleanup = () => { node.disconnect(); src.disconnect(); stream.getTracks().forEach(t => t.stop()); ac.close(); };
            if (state.ended) state.cleanup();
        } catch {
            state.aborted = true; end();
        }
    })();
    return { stop: end, abort: () => { state.aborted = true; end(); }, done };
}

export async function transcribe(token, audio, keywords = []) {
    const r = await fetch(`${API}/media/transcribe`, {
        method: "POST", headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ audio, keywords }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.detail || `Couldn't transcribe (${r.status})`);
    return (d.text || "").trim();
}
