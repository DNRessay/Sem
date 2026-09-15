export async function copyToClipboard(text) {
    try {
        await navigator.clipboard.writeText(text);
        return;
    } catch {
        // Fallback for a context where the Clipboard API is unavailable
        // (some in-app/webview browsers) — a hidden textarea + execCommand
        // still works almost everywhere the Clipboard API doesn't.
        const ta = document.createElement("textarea");
        ta.value = text;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
    }
}
