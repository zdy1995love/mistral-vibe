from __future__ import annotations

from pathlib import Path
import re

import pytest

from vibe import VIBE_ROOT

BUILTIN_STYLES_DIR = VIBE_ROOT / "core" / "prompts" / "styles"


class TestBuiltinStyleFiles:
    def test_default_md_exists(self) -> None:
        assert (BUILTIN_STYLES_DIR / "default.md").is_file()

    def test_concise_md_exists(self) -> None:
        assert (BUILTIN_STYLES_DIR / "concise.md").is_file()

    def test_learner_md_exists(self) -> None:
        assert (BUILTIN_STYLES_DIR / "learner.md").is_file()

    def test_default_md_is_blank_after_strip(self) -> None:
        """default.md must be comment-only/blank so output_style='default'
        produces a system prompt byte-identical to the pre-upgrade output.
        """
        text = (BUILTIN_STYLES_DIR / "default.md").read_text(encoding="utf-8")
        body = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()
        assert body == "", f"default.md must contribute no visible text, got: {body!r}"

    def test_concise_md_has_content(self) -> None:
        text = (BUILTIN_STYLES_DIR / "concise.md").read_text(encoding="utf-8")
        assert text.strip(), "concise.md must contain non-empty guidance"
        assert "concise" in text.lower() or "brief" in text.lower()

    def test_learner_md_has_content(self) -> None:
        text = (BUILTIN_STYLES_DIR / "learner.md").read_text(encoding="utf-8")
        assert text.strip(), "learner.md must contain non-empty guidance"
        lowered = text.lower()
        assert any(kw in lowered for kw in ("explain", "teach", "learn", "why"))


from vibe.core.output_styles import StyleManager, StyleNotFoundError


def _make_style_manager_with_user_dir(user_dir: Path) -> StyleManager:
    """Construct a StyleManager with an explicit user_dir to avoid monkeypatching
    VIBE_HOME (GlobalPath has no refresh() method).
    """
    return StyleManager(user_dir=user_dir)


class TestStyleManagerListing:
    def test_list_returns_builtin_names(self) -> None:
        mgr = StyleManager()
        names = mgr.list_styles()
        assert "default" in names
        assert "concise" in names
        assert "learner" in names

    def test_list_is_sorted_and_deduped(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "styles"
        user_dir.mkdir()
        (user_dir / "concise.md").write_text("user concise override", encoding="utf-8")
        (user_dir / "myteam.md").write_text("custom", encoding="utf-8")

        mgr = _make_style_manager_with_user_dir(user_dir)
        names = mgr.list_styles()

        assert names.count("concise") == 1
        assert "myteam" in names
        assert names == sorted(names)

    def test_list_marks_active(self) -> None:
        mgr = StyleManager()
        listing = mgr.list_styles_with_metadata(active="concise")
        active = [item for item in listing if item.is_active]
        assert len(active) == 1
        assert active[0].name == "concise"


class TestStyleManagerLoad:
    def test_load_default_returns_comment_only(self) -> None:
        mgr = StyleManager()
        text = mgr.load("default")
        body = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL).strip()
        assert body == ""

    def test_load_concise_returns_builtin(self) -> None:
        mgr = StyleManager()
        text = mgr.load("concise")
        assert "concise" in text.lower()

    def test_user_override_wins_on_collision(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "styles"
        user_dir.mkdir()
        (user_dir / "concise.md").write_text(
            "USER OVERRIDE CONCISE STYLE BODY", encoding="utf-8"
        )

        mgr = _make_style_manager_with_user_dir(user_dir)
        text = mgr.load("concise")
        assert text.strip() == "USER OVERRIDE CONCISE STYLE BODY"

    def test_user_can_add_brand_new_style(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "styles"
        user_dir.mkdir()
        (user_dir / "myteam.md").write_text("team prompt body", encoding="utf-8")

        mgr = _make_style_manager_with_user_dir(user_dir)
        assert "myteam" in mgr.list_styles()
        assert mgr.load("myteam").strip() == "team prompt body"

    def test_load_unknown_raises(self) -> None:
        mgr = StyleManager()
        with pytest.raises(StyleNotFoundError):
            mgr.load("does-not-exist")

    def test_load_strips_outer_whitespace(self, tmp_path: Path) -> None:
        user_dir = tmp_path / "styles"
        user_dir.mkdir()
        (user_dir / "padded.md").write_text(
            "\n\n   body\nwith blanks   \n\n", encoding="utf-8"
        )
        mgr = _make_style_manager_with_user_dir(user_dir)
        assert mgr.load("padded") == "body\nwith blanks"
