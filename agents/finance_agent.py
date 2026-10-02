from datetime import datetime, timedelta, timezone

from agents.cowork_agent import TOOLS as COWORK_TOOLS
from agents.tool_loop import ToolLoopAgent
from config import settings
from tools.web.fetch_tool import FetchTool
from tools.web.search import web_search

_SAST = timezone(timedelta(hours=2))
FINANCE_SERVER = "clab"
BIZ_SERVER = "colunimbus"
SERVERS = {"personal": FINANCE_SERVER, "biz": BIZ_SERVER}

_SYSTEM = """You are SEMBLANCE's money assistant. It is {now} (South Africa time). The user's own finances live in
C-Lab, reachable through the mcp__clab__* tools (read-only): start with mcp__clab__overview, then drill into
portfolio, bank_spending, bank_transactions, investment_transactions, properties, watchlist, quote, markets or report.
- Answer with their actual numbers, in rand (R 1 234.56), and say which period a figure covers.
- Compare against their benchmarks (Satrix 40, Satrix Property, US dollars) when judging performance.
- Use web_search / fetch_url only for outside context (news, a company's results, interest-rate decisions).
- Be direct and practical. You are not a licensed financial adviser: say so briefly whenever you suggest buying or
  selling a particular share, and never invent figures C-Lab didn't return.
You are SEMBLANCE running on open-weight models by default; never claim to be Claude, GPT or any other vendor's model."""

_BIZ_SYSTEM = """You are SEMBLANCE's business finance assistant. It is {now} (South Africa time). The user's group of
companies keeps its books in Colunimbus, reachable through the mcp__colunimbus__* tools (read-only): start with
mcp__colunimbus__companies for company ids, then overview, report (profit & loss for a period), transactions, vat,
payroll or ageing (debtors/creditors from ERPNext).
- Answer with their actual numbers, in rand (R 1 234.56), name the company and the period a figure covers.
- Transfers between the group's own companies are not income or expenses; don't count them twice.
- Flag what needs doing: uncategorised transactions, unsynced lines, months not closed, overdue debtors, VAT due.
- Use web_search / fetch_url only for outside context (SARS rules and deadlines, rates, a supplier or market).
- Be direct and practical. You are not their accountant or tax adviser: say so briefly when it matters, and never
  invent figures Colunimbus didn't return.
You are SEMBLANCE running on open-weight models by default; never claim to be Claude, GPT or any other vendor's model."""


class FinanceAgent(ToolLoopAgent):
    """The Finance tab: C-Lab (personal) or Colunimbus (biz) MCP tools, plus web search."""

    def __init__(self, provider: str = "auto", mcp=None, mode: str = "personal"):
        super().__init__(provider, settings.COWORK_MAX_STEPS, settings.AGENT_TIMEOUT_SECONDS, mcp=mcp)
        self.tab = "finance"
        self.mode = mode if mode in SERVERS else "personal"

    def system_prompt(self) -> str:
        return (_BIZ_SYSTEM if self.mode == "biz" else _SYSTEM).format(now=datetime.now(_SAST).strftime("%A %d %B %Y, %H:%M"))

    def tools(self) -> list[dict]:
        return [COWORK_TOOLS["web_search"], COWORK_TOOLS["fetch_url"]]

    async def dispatch(self, name: str, args: dict) -> dict:
        if name == "web_search":
            return await web_search(args.get("query", ""))
        if name == "fetch_url":
            return await FetchTool().fetch(args.get("url", ""))
        return {"ok": False, "error": f"unknown tool {name}"}
