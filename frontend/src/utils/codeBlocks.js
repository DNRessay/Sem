import JSZip from "jszip";

// Fenced code blocks only — an unclosed fence (still streaming) simply
// won't match yet, which is fine: it'll pick up once the closing ``` lands
// in a later chunk, same as marked's own fence parsing already handles.
const FENCE_RE = /```([^\n`]*)\n([\s\S]*?)```/g;

export function extractCodeBlocks(markdown) {
    const blocks = [];
    const re = new RegExp(FENCE_RE);
    let m;
    while ((m = re.exec(markdown)) !== null) {
        const code = m[2].replace(/\n$/, "");
        if (code.trim()) blocks.push({ lang: (m[1] || "").trim(), code });
    }
    return blocks;
}

const EXT_BY_LANG = {
    python: "py", py: "py", javascript: "js", js: "js", jsx: "jsx",
    typescript: "ts", ts: "ts", tsx: "tsx", json: "json", html: "html",
    css: "css", scss: "scss", bash: "sh", sh: "sh", shell: "sh", zsh: "sh",
    sql: "sql", yaml: "yaml", yml: "yaml", markdown: "md", md: "md",
    go: "go", rust: "rs", rs: "rs", java: "java", c: "c", cpp: "cpp",
    "c++": "cpp", csharp: "cs", cs: "cs", ruby: "rb", rb: "rb", php: "php",
    swift: "swift", kotlin: "kt", kt: "kt", xml: "xml", toml: "toml",
    dockerfile: "Dockerfile", diff: "diff", txt: "txt", text: "txt",
};

export function extFor(lang) {
    return EXT_BY_LANG[(lang || "").toLowerCase()] || "txt";
}

export function filenameFor(lang, index) {
    return `snippet-${index + 1}.${extFor(lang)}`;
}

export function downloadText(filename, content) {
    const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

function timestampedZipName() {
    // Local time, filesystem-safe (no colons) — 2026-09-14_18-52-03.zip
    const d = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const stamp = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
        + `_${pad(d.getHours())}-${pad(d.getMinutes())}-${pad(d.getSeconds())}`;
    return `semblance-${stamp}.zip`;
}

export async function downloadAllAsZip(blocks) {
    const zip = new JSZip();
    const usedNames = new Set();
    blocks.forEach((b, i) => {
        let name = filenameFor(b.lang, i);
        // Two blocks of the same language in one message would otherwise
        // collide on the same snippet-N.ext — keep both instead of
        // silently letting the second overwrite the first in the zip.
        while (usedNames.has(name)) {
            name = name.replace(/(\.\w+)$/, `-${Math.random().toString(36).slice(2, 5)}$1`);
        }
        usedNames.add(name);
        zip.file(name, b.code);
    });
    const blob = await zip.generateAsync({ type: "blob" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = timestampedZipName();
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}
