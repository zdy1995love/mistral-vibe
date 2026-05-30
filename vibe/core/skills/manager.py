from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

from vibe.core.config.harness_files import get_harness_files_manager
from vibe.core.logger import logger
from vibe.core.skills.builtins import BUILTIN_SKILLS
from vibe.core.skills.models import ParsedSkillCommand, SkillInfo, SkillMetadata
from vibe.core.skills.parser import SkillParseError, parse_skill_markdown
from vibe.core.utils import name_matches
from vibe.core.utils.io import read_safe

if TYPE_CHECKING:
    from vibe.core.config import VibeConfig


class SkillManager:
    def __init__(self, config_getter: Callable[[], VibeConfig]) -> None:
        self._config_getter = config_getter
        self._search_paths = self._compute_search_paths(self._config)
        self.available_skills: Mapping[str, SkillInfo] = MappingProxyType(
            self._apply_filters(self._discover_skills())
        )

        if self.available_skills:
            logger.info(
                "Discovered %d skill(s) from %d search path(s)",
                len(self.available_skills),
                len(self._search_paths),
            )

    @property
    def _config(self) -> VibeConfig:
        return self._config_getter()

    def _apply_filters(self, skills: dict[str, SkillInfo]) -> dict[str, SkillInfo]:
        if self._config.enabled_skills:
            return {
                name: info
                for name, info in skills.items()
                if name_matches(name, self._config.enabled_skills)
            }
        if self._config.disabled_skills:
            return {
                name: info
                for name, info in skills.items()
                if not name_matches(name, self._config.disabled_skills)
            }
        return dict(skills)

    @staticmethod
    def _compute_search_paths(config: VibeConfig) -> list[Path]:
        paths: list[Path] = []

        for path in config.skill_paths:
            if path.is_dir():
                paths.append(path)

        mgr = get_harness_files_manager()
        paths.extend(mgr.project_skills_dirs)
        paths.extend(mgr.user_skills_dirs)

        unique: list[Path] = []
        for p in paths:
            rp = p.resolve()
            if rp not in unique:
                unique.append(rp)

        return unique

    def _discover_skills(self) -> dict[str, SkillInfo]:
        skills: dict[str, SkillInfo] = {**BUILTIN_SKILLS}
        for base in self._search_paths:
            if not base.is_dir():
                continue
            for name, info in self._discover_skills_in_dir(base).items():
                if name not in skills:
                    skills[name] = info
                else:
                    logger.debug(
                        "Skipping duplicate skill '%s' at %s (already loaded from %s)",
                        name,
                        info.skill_path,
                        skills[name].skill_path,
                    )
        return skills

    def _discover_skills_in_dir(self, base: Path) -> dict[str, SkillInfo]:
        skills: dict[str, SkillInfo] = {}
        for entry in base.iterdir():
            if not entry.is_dir():
                continue
            skill_file = entry / "SKILL.md"
            if skill_file.is_file():
                info = self._try_load_skill(skill_file)
                if info is not None:
                    self._register_skill(skills, info)
                continue
            # No SKILL.md directly under ``entry``: treat it as a namespace
            # folder and load skills one level down (e.g.
            # ``superpowers/brainstorming/SKILL.md``). Each skill keeps the name
            # from its own frontmatter, so cross-references between bundled
            # skills stay valid; the directory name is purely organizational and
            # need not match the skill name.
            for nested in entry.iterdir():
                if not nested.is_dir():
                    continue
                nested_file = nested / "SKILL.md"
                if not nested_file.is_file():
                    continue
                info = self._try_load_skill(nested_file, validate_dirname=False)
                if info is not None:
                    self._register_skill(skills, info)
        return skills

    def _register_skill(
        self, skills: dict[str, SkillInfo], skill_info: SkillInfo
    ) -> None:
        if skill_info.name in BUILTIN_SKILLS:
            logger.debug(
                "Skipping skill '%s' at %s because builtin skill names are reserved",
                skill_info.name,
                skill_info.skill_path,
            )
            return
        if skill_info.name in skills:
            logger.debug(
                "Skipping duplicate skill '%s' at %s (already loaded from %s)",
                skill_info.name,
                skill_info.skill_path,
                skills[skill_info.name].skill_path,
            )
            return
        skills[skill_info.name] = skill_info

    def _try_load_skill(
        self, skill_file: Path, *, validate_dirname: bool = True
    ) -> SkillInfo | None:
        try:
            skill_info = self._parse_skill_file(
                skill_file, validate_dirname=validate_dirname
            )
        except Exception as e:
            logger.warning("Failed to parse skill at %s: %s", skill_file, e)
            return None
        return skill_info

    def _parse_skill_file(
        self, skill_path: Path, *, validate_dirname: bool = True
    ) -> SkillInfo:
        try:
            content = read_safe(skill_path).text
        except OSError as e:
            raise SkillParseError(f"Cannot read file: {e}") from e

        frontmatter, body = parse_skill_markdown(content)
        metadata = SkillMetadata.model_validate(frontmatter)

        skill_name_from_dir = skill_path.parent.name
        if validate_dirname and metadata.name != skill_name_from_dir:
            logger.warning(
                "Skill name '%s' doesn't match directory name '%s' at %s",
                metadata.name,
                skill_name_from_dir,
                skill_path,
            )

        return SkillInfo.from_metadata(metadata, skill_path, prompt=body.strip())

    @property
    def custom_skills_count(self) -> int:
        return sum(name not in BUILTIN_SKILLS for name in self.available_skills)

    def get_skill(self, name: str) -> SkillInfo | None:
        return self.available_skills.get(name)

    def parse_skill_command(self, text_prompt: str) -> ParsedSkillCommand | None:
        stripped = text_prompt.strip()
        if not stripped.startswith("/"):
            return None

        parts = stripped[1:].split(None, 1)
        if not parts:
            return None

        skill_name = parts[0].lower()
        skill_info = self.get_skill(skill_name)
        if skill_info is None:
            return None

        extra_instructions = parts[1] if len(parts) > 1 else None

        return ParsedSkillCommand(
            name=skill_name,
            content=skill_info.prompt,
            extra_instructions=extra_instructions,
        )

    @staticmethod
    def build_skill_prompt(text_prompt: str, parsed: ParsedSkillCommand) -> str:
        if parsed.extra_instructions is not None:
            return f"{text_prompt}\n\n{parsed.content}"
        return parsed.content
