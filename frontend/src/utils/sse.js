// Reads a `data: {...}` server-sent-event stream, calling onEvent for each
// JSON event. Buffers across network chunks so an event split over two
// reads isn't lost.
export async function readEvents(res, onEvent) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const handle = (line) => {
        if (!line.startsWith("data: ") || line === "data: [DONE]") return;
        try { onEvent(JSON.parse(line.slice(6))); } catch {}
    };
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        lines.forEach(handle);
    }
    if (buffer) handle(buffer);
}

// Calls onLine for every complete line of a streamed response (the raw "data: …" lines, [DONE] included).
export async function readLines(res, onLine) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        lines.forEach(onLine);
    }
    if (buffer) onLine(buffer);
}
