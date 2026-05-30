from __future__ import annotations

from pathlib import Path

from tests.conftest import build_test_vibe_config
from vibe.core.skills.manager import SkillManager


def _write_skill(skill_dir: Path, name: str) -> None:
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "test skill {name}"\n---\n\nbody of {name}\n',
        encoding="utf-8",
    )


def _manager() -> SkillManager:
    return SkillManager(lambda: build_test_vibe_config())


def test_flat_skill_discovery_unchanged(tmp_path: Path) -> None:
    """A skill with SKILL.md directly under the search dir still loads."""
    _write_skill(tmp_path / "my-skill", "my-skill")
    found = _manager()._discover_skills_in_dir(tmp_path)
    assert "my-skill" in found
    assert found["my-skill"].skill_path.parent.name == "my-skill"


def test_namespace_folder_discovery(tmp_path: Path) -> None:
    """A folder with no SKILL.md but skill subfolders is a namespace: nested
    skills load one level down, keyed by their own frontmatter name (so the
    subfolder name may differ from the skill name without a warning).
    """
    _write_skill(tmp_path / "flat-skill", "flat-skill")
    _write_skill(tmp_path / "superpowers" / "brainstorming", "superpowers-brainstorming")
    _write_skill(tmp_path / "superpowers" / "writing-plans", "superpowers-writing-plans")

    found = _manager()._discover_skills_in_dir(tmp_path)

    assert set(found) == {
        "flat-skill",
        "superpowers-brainstorming",
        "superpowers-writing-plans",
    }
    # registered by frontmatter name; skill_path points at the nested file
    info = found["superpowers-brainstorming"]
    assert info.skill_path.parent.name == "brainstorming"
    assert info.skill_path.parent.parent.name == "superpowers"


def test_namespace_recursion_is_one_level_only(tmp_path: Path) -> None:
    """Discovery descends exactly one level into a namespace folder — a skill
    buried two levels deep is not picked up.
    """
    _write_skill(tmp_path / "ns" / "deep" / "buried", "buried")
    found = _manager()._discover_skills_in_dir(tmp_path)
    assert "buried" not in found
