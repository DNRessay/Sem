BUFFER = 13_000
SUMMARY_TARGET = 20_000
CIRCUIT_BREAKER = 3

_failures = 0


class CTXPressure:
    def apply(self, ctx: str) -> str:
        global _failures
        if len(ctx) <= SUMMARY_TARGET:
            return ctx
        strategies = [
            self.budget,
            self.microcompact,
            self.collapse,
            self.autocompact,
            self.prune_and_index,
        ]
        for fn in strategies:
            try:
                ctx = fn(ctx)
                if len(ctx) <= SUMMARY_TARGET:
                    _failures = 0
                    return ctx
            except Exception:
                _failures += 1
                if _failures >= CIRCUIT_BREAKER:
                    break
        return ctx[:SUMMARY_TARGET]

    def budget(self, ctx: str) -> str:
        return ctx[:SUMMARY_TARGET + BUFFER]

    def microcompact(self, ctx: str) -> str:
        lines = [line for line in ctx.splitlines() if line.strip()]
        return "\n".join(lines)

    def collapse(self, ctx: str) -> str:
        seen, out = set(), []
        for line in ctx.splitlines():
            if line not in seen:
                seen.add(line)
                out.append(line)
        return "\n".join(out)

    def autocompact(self, ctx: str) -> str:
        # In production: LLM-assisted summarisation via Groq
        return ctx[:SUMMARY_TARGET]

    def prune_and_index(self, ctx: str) -> str:
        return ctx[:SUMMARY_TARGET]
