"""Built-in superpowers skills.

The 14 skills under ``skills/`` are vendored from
https://github.com/obra/superpowers (MIT, see ``LICENSE.upstream``) and
translated for mistral-vibe. They are loaded at import time so they appear
in ``BUILTIN_SKILLS`` and are first-class slash commands plus model-callable
via the ``skill`` tool.

Sub-files inside each skill directory (e.g. ``brainstorming/visual-companion.md``,
``subagent-driven-development/implementer-prompt.md``) are reachable via
``read_file`` because ``SkillInfo.skill_path`` points at the bundled path.
"""

from __future__ import annotations

from pathlib import Path

from vibe.core.logger import logger
from vibe.core.skills.models import SkillInfo, SkillMetadata
from vibe.core.skills.parser import SkillParseError, parse_skill_markdown

_SKILLS_DIR = Path(__file__).parent / "skills"


def _load_one(skill_dir: Path) -> SkillInfo | None:
    skill_file = skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return None
    try:
        content = skill_file.read_text(encoding="utf-8")
        frontmatter, body = parse_skill_markdown(content)
        metadata = SkillMetadata.model_validate(frontmatter)
    except (OSError, SkillParseError, ValueError) as exc:
        logger.warning("Failed to load bundled skill at %s: %s", skill_file, exc)
        return None
    return SkillInfo.from_metadata(metadata, skill_file, prompt=body.strip())


def load_superpowers_skills() -> list[SkillInfo]:
    """Discover and parse every bundled superpowers SKILL.md.

    Returns a sorted-by-name list. Failures are logged and skipped — a single
    malformed skill must not prevent the rest of the bundle from loading.
    """
    if not _SKILLS_DIR.is_dir():
        return []
    skills: list[SkillInfo] = []
    for skill_dir in sorted(_SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        info = _load_one(skill_dir)
        if info is not None:
            skills.append(info)
    return skills


__all__ = ["load_superpowers_skills"]
