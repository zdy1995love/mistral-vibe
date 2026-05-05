from __future__ import annotations

from vibe.core.skills.builtins.superpowers import load_superpowers_skills
from vibe.core.skills.builtins.vibe import SKILL as VIBE_SKILL
from vibe.core.skills.models import SkillInfo

_ALL_SKILLS: list[SkillInfo] = [VIBE_SKILL, *load_superpowers_skills()]
BUILTIN_SKILLS: dict[str, SkillInfo] = {skill.name: skill for skill in _ALL_SKILLS}
