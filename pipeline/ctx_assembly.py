from pathlib import Path

MAX_CTX_CHARS = 40_000
HIERARCHY = ["global", "user", "project", "local"]


class CTXAssembly:
    def load_hierarchy(self) -> str:
        parts = []
        for level in HIERARCHY:
            path = Path(f"{level}/SEMBLANCE.md")
            if path.exists():
                parts.append(path.read_text())
        ctx = "\n\n".join(parts)
        return self.validate_length(ctx)

    def inject_tau_context(self, ctx: str, tau_context: str) -> str:
        if not tau_context:
            return ctx
        return f"{ctx}\n\n<tau_context>\n{tau_context}\n</tau_context>"

    def validate_length(self, ctx: str) -> str:
        if len(ctx) > MAX_CTX_CHARS:
            return ctx[:MAX_CTX_CHARS]
        return ctx
