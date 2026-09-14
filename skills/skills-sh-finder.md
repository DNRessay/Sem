---
name: Skills.sh Finder
description: Points the user at existing community-built agent skills on skills.sh before they build one from scratch — how to search it, how to read results, and how to install what they find.
triggers: skills.sh, skill for this, find me a skill, pre-built skill, community skill, existing skill, agent skill, npx skills add, is there a skill
---

# Skills.sh Finder

Skills.sh is the open community directory of reusable agent skills — 90,000+ covering frameworks, SaaS integrations, design workflows, marketing, testing, and more.

The point: **before writing a new skill, prompt, or workflow from scratch, check whether someone already built one.** Casting a wide net is the goal — false positives are cheap, missed matches are costly.

> Note for SEMBLANCE: this skill has no live search. It tells the user how to search and what to look for, and gives them the exact URLs and commands to run themselves. Don't claim to have searched — hand them the query.

## When this applies

- The user is starting something they might want to repeat (a workflow, a content series, a recurring report).
- The task involves a named tool, framework, SaaS product, or API ("build something with Supabase," "set up Stripe," "write a Next.js component").
- The task is in a domain with rich existing tooling (design, marketing, SEO, testing, agent workflows, deployment).
- The user hints at building a skill or workflow ("I want to make a skill that…", "I keep doing X manually").
- The user explicitly asks — "search skills.sh," "is there a skill for this," "anything pre-built for X."

**Does not apply** to trivial one-shot tasks, simple factual questions, casual conversation, or anything handleable in one turn with no repeatable value.

## How to search

**Primary method — Google with the `site:` operator.** Returns rich descriptive snippets, often including the install command.

```
site:skills.sh <query>
```

Examples:
- `site:skills.sh seo audit`
- `site:skills.sh stripe payments`
- `site:skills.sh next.js auth`
- `site:skills.sh video editing`

**Query construction tips:**
- Use the domain noun, not the verb. "stripe payments" beats "set up payments."
- Include the framework/tool name when there is one. "next.js auth" beats "auth."
- Search the workflow noun for broad tasks: "seo audit," "design system," "react component."
- If the first query returns nothing useful, try a broader synonym before giving up.
- For wide-net searches, run 2-3 related queries rather than one super-broad one.

**Alternate method — the REST API:**

```
GET https://skills.sh/api/v1/skills/search?q=<query>&limit=10     # search, returns JSON
GET https://skills.sh/api/v1/skills/<owner>/<repo>/<slug>          # full SKILL.md contents
GET https://skills.sh/api/v1/skills/audit/<owner>/<repo>/<slug>    # security audit results
```

Use the API when structured data is needed programmatically, or to read a skill's full contents before installing.

**Filtering rules:**
- Skip results where the URL or snippet indicates a duplicate/fork of another skill.
- Skills from `anthropics/*`, `vercel-labs/*`, `supabase/*`, `firebase/*`, `microsoft/*` and other first-party publishers are higher trust — flag them as "official" when relevant.
- Don't fabricate install counts. If the snippet doesn't show one, omit it.

## How to present results

Surface 3-5 matches by default, more for a wide net. Include adjacent skills, not just exact matches — breadth beats precision here.

Format each as:

```
**[Skill Name]** — `owner/repo` [· official, if applicable]
[One sentence, in plain language, on what it does and when it'd help — concrete to the task at hand, not a copy of the listing's first line.]
🔗 https://skills.sh/owner/repo/skill-slug
📦 `npx skills add owner/repo/skill-slug`
```

Notes:
- The description is *your* synthesis, not a verbatim quote — make it useful for this specific task.
- Prefer the specific skill path (`owner/repo/skill-slug`) over the whole repo so the user doesn't install dozens of unrelated skills from a multi-skill repo.
- Group multiple skills from the same source repo under one heading.
- Order by **relevance to the task**, not install count. Install count is a tiebreaker.

If nothing useful turns up, say so directly. Then offer to either help build a custom skill, or try a different query.

## Security audit check

For skills from less-known publishers, check the audit endpoint before recommending install. If status is `warn` or `fail` for any audit partner, surface that clearly. A 404 just means it hasn't been audited yet — not a red flag on its own, but worth mentioning for unknown publishers.

## Installation context

`npx skills add ...` is for code-environment agents (Claude Code, Cursor, etc.). To use a found skill in SEMBLANCE instead: copy its SKILL.md body, convert the frontmatter to this repo's `name` / `description` / `triggers` format, drop anything about invoking tools SEMBLANCE doesn't have, and commit it as a new file in `skills/`.

## Examples

**Good trigger:**
> User: "Help me build a marketing landing page in Next.js"
> Action: Suggest `site:skills.sh next.js landing page`. If something strong exists, mention it briefly before starting. If not, just build the page.

**Good on-demand trigger:**
> User: "Is there a skill on skills.sh for doing SEO audits?"
> Action: Point them at `site:skills.sh seo audit`, and show the result format to expect.

**Bad trigger (do not activate):**
> User: "What's the capital of France?"
> Action: Just answer.

**Wide-net behavior:**
> User: "I want to make videos with AI."
> Action: Cast wide — `ai video`, `video generation`, `video edit`. Surface AI video gen, video editing, and adjacent tools like image-to-video and motion graphics, not just the closest match.
