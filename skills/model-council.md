---
name: Model Council
description: Multi-model consensus — send a query to 3+ LLMs via OpenRouter in parallel, then have a judge model pick a winner, explain why, and synthesize a best answer. For important decisions, code review, and research verification.
triggers: model council, second opinion, multiple models, consensus, cross-check, ask the council, compare models, openrouter, judge model
---

# Model Council 🏛️

Send a query to 3+ different LLMs simultaneously via OpenRouter. A judge model evaluates all responses and produces a winner, reasoning, and a synthesized best answer.

> **Requires the runner script.** This skill is instructions for driving
> `scripts/model_council.py`, which is not in this repo. Without it, SEMBLANCE
> can only explain the pattern — it can't run the council. Add the script (or a
> backend endpoint that does the same fan-out) before relying on this.

## When to use

- **Important decisions** — don't trust one model's opinion
- **Code review** — multiple perspectives on architecture choices
- **Research verification** — cross-check facts across models
- **Creative work** — compare writing styles and pick the best
- **Debugging** — when one model is stuck, others might see the issue

## How it works

```
Your Question
    ├──→ Model A  ──→ Response A
    ├──→ Model B  ──→ Response B
    └──→ Model C  ──→ Response C
                          │
                    Judge evaluates all
                          │
                    ├── Winner + reasoning
                    ├── Synthesized best answer
                    └── Cost breakdown
```

## Usage

```bash
# Basic
python3 scripts/model_council.py "What's the best database for a real-time analytics dashboard?"

# Custom models
python3 scripts/model_council.py --models "anthropic/claude-sonnet-4,openai/gpt-4o,google/gemini-2.5-pro" "Your question"

# Custom judge
python3 scripts/model_council.py --judge "openai/gpt-4o" "Your question"

# JSON output
python3 scripts/model_council.py --json "Your question"

# Cap tokens per response
python3 scripts/model_council.py --max-tokens 2000 "Your question"
```

## Configuration

| Flag | Default | Description |
|------|---------|-------------|
| `--models` | claude-sonnet-4, gpt-4o, gemini-2.0-flash | Comma-separated model list |
| `--judge` | anthropic/claude-opus-4-6 | Judge model |
| `--max-tokens` | 1024 | Max tokens per council member |
| `--json` | false | Output as JSON |
| `--timeout` | 60 | Timeout per model (seconds) |

## Environment

Requires the `OPENROUTER_API_KEY` environment variable.

## Output shape

```
═══ MODEL COUNCIL RESULTS ═══

Question: <the question>

── Council Member Responses ──

🤖 <model>  ($cost)
<response>

── Judge Verdict (<judge model>, $cost) ──

🏆 Winner: <model>
Reasoning: <why>

📝 Synthesized Answer:
<combined best answer>

💰 Total Cost: $<total>
```

---

Original skill by M. Abidi — agxntsix.ai — part of the AgxntSix Skill Suite for
OpenClaw agents. MIT licensed. Reformatted here for SEMBLANCE's `skills/` loader.
