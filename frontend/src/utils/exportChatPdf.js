import { parseToolMarker } from "./toolMarker";

// jsPDF's default fonts (Helvetica etc.) only cover WinAnsi/Latin-1 —
// asking them to render a character outside that range (an arrow, an em
// dash, a smart quote) doesn't just drop that one character, it corrupts
// the whole line into letter-spaced garbage (confirmed on a real export
// of a reply containing "29.25%→76%" and PIPELINE's "→"-joined stages).
// Swapping the common offenders for ASCII equivalents first, then
// replacing anything still outside Latin-1 with "?" as a catch-all,
// keeps every line intact instead of only fixing the specific characters
// SEMBLANCE's own text happens to use today.
const UNICODE_REPLACEMENTS = {
    "→": "->", "←": "<-", "–": "-", "—": "--",
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "…": "...", "×": "x", "•": "-", "·": "-",
};

function sanitizeForPdf(text) {
    let out = text || "";
    for (const [char, replacement] of Object.entries(UNICODE_REPLACEMENTS)) {
        out = out.split(char).join(replacement);
    }
    return out.replace(/[^\x00-\xFF]/g, "?");
}

// jspdf is dynamically imported so it's only pulled into a loaded chunk
// when someone actually exports a chat, not added to the app's initial
// bundle for a feature most sessions never touch.
export async function exportChatPdf(title, turns) {
    const { jsPDF } = await import("jspdf");
    const doc = new jsPDF({ unit: "pt", format: "a4" });
    const marginX = 40;
    const pageHeight = doc.internal.pageSize.getHeight();
    const maxWidth = doc.internal.pageSize.getWidth() - marginX * 2;
    let y = 50;

    doc.setFontSize(16);
    doc.text(sanitizeForPdf(title) || "SEMBLANCE chat", marginX, y);
    y += 26;

    doc.setFontSize(10);
    for (const turn of turns || []) {
        const label = turn.role === "user" ? "You" : "SEMBLANCE";
        const { content } = turn.role === "assistant" ? parseToolMarker(turn.content) : { content: turn.content };
        const lines = doc.splitTextToSize(`${label}: ${sanitizeForPdf(content)}`, maxWidth);
        for (const line of lines) {
            if (y > pageHeight - 40) {
                doc.addPage();
                y = 50;
            }
            doc.text(line, marginX, y);
            y += 14;
        }
        y += 10;
    }

    doc.save(`${slugify(title)}.pdf`);
}

function slugify(text) {
    const s = (text || "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "").slice(0, 60);
    return s || "semblance-chat";
}
