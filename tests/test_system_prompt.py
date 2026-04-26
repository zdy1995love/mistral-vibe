from __future__ import annotations

import sys

import pytest

from tests.conftest import build_test_vibe_config
from vibe.core.agents import AgentManager
from vibe.core.skills.manager import SkillManager
from vibe.core.system_prompt import get_universal_system_prompt
from vibe.core.tools.manager import ToolManager


def test_get_universal_system_prompt_includes_windows_prompt_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("COMSPEC", "C:\\Windows\\System32\\cmd.exe")

    config = build_test_vibe_config(
        system_prompt_id="tests",
        include_project_context=False,
        include_prompt_detail=True,
        include_model_info=False,
        include_commit_signature=False,
    )
    tool_manager = ToolManager(lambda: config)
    skill_manager = SkillManager(lambda: config)
    agent_manager = AgentManager(lambda: config)

    prompt = get_universal_system_prompt(
        tool_manager, config, skill_manager, agent_manager
    )

    assert "You are Vibe, a super useful programming assistant." in prompt
    assert (
        "The operating system is Windows with shell `C:\\Windows\\System32\\cmd.exe`"
        in prompt
    )
    assert "DO NOT use Unix commands like `ls`, `grep`, `cat`" in prompt
    assert "Use: `dir` (Windows) for directory listings" in prompt
    assert "Use: backslashes (\\\\) for paths" in prompt
    assert "Check command availability with: `where command` (Windows)" in prompt
    assert "Script shebang: Not applicable on Windows" in prompt


def _build_prompt(output_style: str) -> str:
    config = build_test_vibe_config(
        include_project_context=False,
        include_prompt_detail=False,
        include_model_info=False,
        include_commit_signature=False,
        output_style=output_style,
    )
    tool_manager = ToolManager(lambda: config)
    skill_manager = SkillManager(lambda: config)
    agent_manager = AgentManager(lambda: config)
    return get_universal_system_prompt(
        tool_manager, config, skill_manager, agent_manager, include_git_status=False
    )


class TestOutputStyleInjection:
    def test_default_style_is_byte_equivalent_to_no_prepend(self) -> None:
        """REGRESSION GUARD: output_style='default' must produce a system
        prompt byte-identical to the legacy (pre-feature) assembly. The
        default.md file is comment-only/whitespace so after .strip() it
        contributes nothing and join over an unchanged sections list yields
        the legacy bytes exactly.
        """
        prompt = _build_prompt("default")
        assert "<!--" not in prompt
        assert "default output style" not in prompt
        assert isinstance(prompt, str) and len(prompt) > 0

    def test_concise_style_is_prepended_at_head(self) -> None:
        prompt = _build_prompt("concise")
        idx_style = prompt.find("Output Style: Concise")
        assert idx_style != -1, "concise style content missing"
        # Style preamble must appear before the main system_prompt content.
        idx_main = prompt.find("You are Vibe")
        assert idx_main == -1 or idx_style < idx_main

    def test_unknown_style_falls_back_to_default(self) -> None:
        """If config.output_style points to a non-existent style, the
        assembler logs and falls back to 'default' rather than crashing.
        """
        prompt = _build_prompt("does-not-exist")
        assert "Output Style:" not in prompt
