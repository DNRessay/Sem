import re
from pathlib import Path

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.S)


def _slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def parse_skill_file(path: Path) -> dict | None:
    """Parses one skill .md file (see skills/README.md for the format): a
    flat `key: value` frontmatter block between `---` markers, then the
    skill's full content below it. Returns None for a file that isn't
    actually in this shape (no frontmatter, or no `name:` field) so a
    stray README or unrelated .md file in the folder is silently skipped
    rather than breaking the sync."""
    text = path.read_text(encoding="utf-8")
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None

    fields = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        fields[key.strip().lower()] = value.strip()

    name = fields.get("name")
    if not name:
        return None

    triggers = [t.strip().lower() for t in fields.get("triggers", "").split(",") if t.strip()]
    return {
        "id": f"repo-{_slugify(path.stem)}",
        "name": name,
        "description": fields.get("description", ""),
        "triggers": triggers,
        "content": m.group(2).strip(),
    }


def load_skill_files(directory: str = "skills") -> list[dict]:
    """Parses every .md file in `directory` (relative to the process's cwd
    — same convention pipeline/ctx_assembly.py uses for SEMBLANCE.md, which
    works in the deployed Lambda since CodeUri is the repo root). A file
    that fails to parse is skipped rather than aborting the whole sync —
    one bad file shouldn't take down every other skill. Returns [] if the
    folder doesn't exist at all, so a repo without a skills/ directory
    (or an environment where cwd isn't the repo root, e.g. some local dev
    setups) degrades to "no repo skills," never a startup crash."""
    folder = Path(directory)
    if not folder.is_dir():
        return []
    skills = []
    for path in sorted(folder.glob("*.md")):
        if path.stem.lower() == "readme":
            continue
        try:
            skill = parse_skill_file(path)
        except Exception:
            skill = None
        if skill:
            skills.append(skill)
    return skills
