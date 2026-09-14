from pathlib import Path

from pipeline.skill_files import load_skill_files, parse_skill_file


def _write(path: Path, text: str) -> Path:
    path.write_text(text)
    return path


def test_parse_skill_file_extracts_frontmatter_and_body(tmp_path):
    f = _write(tmp_path / "my-skill.md", (
        "---\n"
        "name: My Skill\n"
        "description: Does a thing\n"
        "triggers: alpha, Beta ,  gamma\n"
        "---\n"
        "\n"
        "Full instructions here.\n"
        "Second line.\n"
    ))
    skill = parse_skill_file(f)
    assert skill == {
        "id": "repo-my-skill",
        "name": "My Skill",
        "description": "Does a thing",
        "triggers": ["alpha", "beta", "gamma"],
        "content": "Full instructions here.\nSecond line.",
    }


def test_parse_skill_file_returns_none_without_frontmatter(tmp_path):
    f = _write(tmp_path / "plain.md", "Just a regular markdown file, no frontmatter.\n")
    assert parse_skill_file(f) is None


def test_parse_skill_file_returns_none_without_a_name_field(tmp_path):
    f = _write(tmp_path / "no-name.md", "---\ndescription: x\n---\nbody\n")
    assert parse_skill_file(f) is None


def test_parse_skill_file_defaults_missing_description_and_triggers(tmp_path):
    f = _write(tmp_path / "minimal.md", "---\nname: Minimal\n---\nbody text\n")
    skill = parse_skill_file(f)
    assert skill["description"] == ""
    assert skill["triggers"] == []


def test_parse_skill_file_slugifies_the_filename_into_the_id(tmp_path):
    f = _write(tmp_path / "WhatsApp Bot Help.md", "---\nname: X\n---\nbody\n")
    assert parse_skill_file(f)["id"] == "repo-whatsapp-bot-help"


def test_load_skill_files_returns_empty_list_for_a_missing_directory(tmp_path):
    assert load_skill_files(str(tmp_path / "does-not-exist")) == []


def test_load_skill_files_skips_readme_and_malformed_files(tmp_path):
    _write(tmp_path / "README.md", "# Format docs, not a skill\n")
    _write(tmp_path / "broken.md", "no frontmatter at all\n")
    _write(tmp_path / "good.md", "---\nname: Good\ndescription: d\ntriggers: t\n---\ncontent\n")

    skills = load_skill_files(str(tmp_path))
    assert [s["id"] for s in skills] == ["repo-good"]


def test_load_skill_files_returns_sorted_by_filename(tmp_path):
    _write(tmp_path / "b.md", "---\nname: B\n---\nb\n")
    _write(tmp_path / "a.md", "---\nname: A\n---\na\n")

    skills = load_skill_files(str(tmp_path))
    assert [s["id"] for s in skills] == ["repo-a", "repo-b"]


def test_the_real_skills_directory_parses_without_error():
    """Smoke test against the actual skills/ folder shipped in this repo —
    if whatsapp-bot-help.md (or any other real skill file) ever drifts out
    of the documented format, this catches it instead of only failing
    silently in production. Uses this test file's own location to find the
    repo root rather than a bare relative "skills" path — CI checks the
    repo out to a different absolute path than a local dev sandbox (see
    test_explore_agent.py's near-identical comment, and the CI failure it's
    guarding against)."""
    repo_root = Path(__file__).resolve().parent.parent
    skills = load_skill_files(str(repo_root / "skills"))
    assert any(s["id"] == "repo-whatsapp-bot-help" for s in skills)
