import { parseToolMarker } from "./toolMarker";

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
    doc.text(title || "SEMBLANCE chat", marginX, y);
    y += 26;

    doc.setFontSize(10);
    for (const turn of turns || []) {
        const label = turn.role === "user" ? "You" : "SEMBLANCE";
        const { content } = turn.role === "assistant" ? parseToolMarker(turn.content) : { content: turn.content };
        const lines = doc.splitTextToSize(`${label}: ${content || ""}`, maxWidth);
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
