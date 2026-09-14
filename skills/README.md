# SEMBLANCE Skill Files

Drop a `.md` file in this folder to add a skill SEMBLANCE picks up
automatically — no need to use the app's Skills panel for these. On every
backend deploy (more precisely: the first request each fresh Lambda
container handles), the backend reads every `.md` file here and syncs it
into the database.

## Format

```
---
name: Short Skill Name
description: One-line summary — shown to the model on every turn, even before any trigger matches
triggers: keyword one, keyword two, keyword three
---

Full instructions, in plain markdown. This block is only loaded into the
model's context on a turn where the user's message contains one of the
trigger words above (case-insensitive substring match) — same two-tier
disclosure as the description-always-visible / full-content-on-trigger
shape Claude's own Skills use.
```

## Rules

- The filename becomes the skill's stable id (`repo-<filename-without-extension>`,
  lowercased, spaces → dashes). Renaming the file creates a new skill
  rather than updating the old one — don't rename casually once a skill
  is live.
- A skill from this folder syncs on every deploy — edit the file and push,
  no separate action needed. It always overwrites the DB row with the
  file's current content, so the file is the real source of truth.
- It shows up read-only in the app's Skills panel (labeled "from repo").
  Editing or deleting it there won't stick — the next deploy re-syncs it
  from the file. To change or remove it, edit or delete the file instead.
- Skills created through the app's Skills panel (or the 5 starter skills
  seeded automatically into an empty database) are never touched by this
  sync — it only ever writes ids it created itself (`repo-*`).
- A `.md` file with no `---` frontmatter block, or no `name:` field, is
  silently skipped rather than breaking the sync for every other file.

## Finding skills to add

If you've found a skill written for Claude (e.g. from
[skills.sh](https://skills.sh)) that you want SEMBLANCE to use too, ask
Claude Code to adapt it into this format — the instructional core usually
translates directly; anything about invoking Claude-specific tools doesn't
apply here and should be dropped, since SEMBLANCE's model has no real
tool-calling and only ever sees this content as plain injected text.
