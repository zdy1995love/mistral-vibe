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
    def test_default_style_is_byte_equivalent_to_no_prepend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """REGRESSION GUARD: building a prompt with output_style='default'
        must be byte-identical to a build where _resolve_output_style_section
        is forced to skip prepending entirely.

        The earlier version of this test stubbed StyleManager.load to return
        "" and compared against the real default.md run. Both paths hit the
        resolver's `visible == ""` → `return ()` branch, so the comparison
        was trivially `prompt == prompt`. A regression that made the
        resolver unconditionally prepend would NOT have been caught.

        This version patches _resolve_output_style_section itself to always
        return (), giving us a true "no-prepend" baseline. If anyone ever
        lets visible content into default.md or changes the resolver to
        always prepend for "default", the assertion fails.
        """
        prompt_default = _build_prompt("default")

        from vibe.core import system_prompt

        monkeypatch.setattr(
            system_prompt, "_resolve_output_style_section", lambda config: ()
        )
        prompt_baseline = _build_prompt("default")

        assert prompt_default == prompt_baseline

    def test_concise_style_is_prepended_at_head(self) -> None:
        prompt = _build_prompt("concise")
        idx_style = prompt.find("Output Style: Concise")
        assert idx_style != -1, "concise style content missing"
        # Style preamble must appear before the main system_prompt content.
        # The default cli system prompt opens with "You are Mistral Vibe".
        idx_main = prompt.find("You are Mistral Vibe")
        assert idx_main != -1, "main system prompt content missing"
        assert idx_style < idx_main, "style preamble must appear BEFORE the main prompt"

    def test_unknown_style_falls_back_to_default(self) -> None:
        """If config.output_style points to a non-existent style, the
        assembler logs and falls back to 'default' rather than crashing.
        """
        prompt = _build_prompt("does-not-exist")
        assert "Output Style:" not in prompt

    def test_unreadable_style_file_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A corrupt user style file (OSError / non-UTF-8 bytes) must not
        crash system-prompt assembly — the prompt is rebuilt on every turn,
        so any uncaught exception would brick the whole session.
        """
        from vibe.core.output_styles import StyleManager, StyleNotFoundError

        real_load = StyleManager.load

        def _fake_load(self: StyleManager, name: str) -> str:
            if name == "concise":
                raise OSError("permission denied")
            return real_load(self, name)

        monkeypatch.setattr(StyleManager, "load", _fake_load)
        prompt = _build_prompt("concise")
        assert isinstance(prompt, str) and len(prompt) > 0
        assert "Output Style: Concise" not in prompt
        # And StyleNotFoundError is unrelated; just confirm import works.
        assert StyleNotFoundError is not None

    def test_undecodable_style_file_falls_back_to_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.core.output_styles import StyleManager

        real_load = StyleManager.load

        def _fake_load(self: StyleManager, name: str) -> str:
            if name == "concise":
                raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad byte")
            return real_load(self, name)

        monkeypatch.setattr(StyleManager, "load", _fake_load)
        prompt = _build_prompt("concise")
        assert isinstance(prompt, str) and len(prompt) > 0
        assert "Output Style: Concise" not in prompt

    def test_unknown_style_with_unreadable_default_does_not_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The asymmetric edge case the original fix didn't cover: typo'd
        config.output_style triggers StyleNotFoundError, AND the shipped
        default.md is unreadable on this install. Both fallbacks must
        degrade silently rather than crash per-turn assembly.
        """
        from vibe.core.output_styles import StyleManager, StyleNotFoundError

        def _fake_load(self: StyleManager, name: str) -> str:
            if name == "default":
                raise OSError("default.md somehow unreadable")
            raise StyleNotFoundError(name)

        monkeypatch.setattr(StyleManager, "load", _fake_load)
        prompt = _build_prompt("nonexistent-style")
        assert isinstance(prompt, str) and len(prompt) > 0
        assert "Output Style:" not in prompt

    def test_unreadable_user_style_with_unreadable_default_does_not_crash(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Same as above but with OSError on the user style instead of
        StyleNotFoundError. The OSError-fallback path was already covered;
        this asserts symmetry with the StyleNotFoundError path.
        """
        from vibe.core.output_styles import StyleManager

        def _fake_load(self: StyleManager, name: str) -> str:
            raise OSError(f"{name}.md unreadable")

        monkeypatch.setattr(StyleManager, "load", _fake_load)
        prompt = _build_prompt("concise")
        assert isinstance(prompt, str) and len(prompt) > 0
        assert "Output Style:" not in prompt
