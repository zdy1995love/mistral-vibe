from __future__ import annotations

from vibe.core.paths import PLANS_DIR
from vibe.core.plan_session import PlanSession


class TestPlanSession:
    def test_lazy_initialization(self) -> None:
        session = PlanSession()
        assert session._plan_file_path is None

    def test_stable_path(self) -> None:
        session = PlanSession()
        first = session.plan_file_path
        second = session.plan_file_path
        assert first == second

    def test_md_extension(self) -> None:
        session = PlanSession()
        assert session.plan_file_path.suffix == ".md"

    def test_name_format(self) -> None:
        session = PlanSession()
        stem = session.plan_file_path.stem
        parts = stem.split("-", 1)
        assert len(parts) == 2
        timestamp_str, slug = parts
        assert timestamp_str.isdigit()
        assert len(slug.split("-")) == 3

    def test_plan_file_path_str_matches(self) -> None:
        session = PlanSession()
        assert session.plan_file_path_str == str(session.plan_file_path)

    def test_path_under_plans_dir(self) -> None:
        session = PlanSession()
        assert session.plan_file_path.parent == PLANS_DIR.path

    def test_different_sessions_get_different_paths(self) -> None:
        session1 = PlanSession()
        session2 = PlanSession()
        assert session1.plan_file_path != session2.plan_file_path


class TestPlansDirIsCwdLocal:
    """PLANS_DIR is project-local (resolved from cwd) — NOT under VIBE_HOME.

    Co-locates plans with the code they describe; multiple projects don't
    collide on slug names; a plan stays with its repo.
    """

    def test_plans_dir_is_under_cwd(self, tmp_working_directory) -> None:
        # tmp_working_directory fixture chdir's to an isolated path; PLANS_DIR
        # must resolve under it, not under the global config dir.
        assert PLANS_DIR.path == tmp_working_directory / ".vibe" / "plans"

    def test_plans_dir_not_under_vibe_home(
        self, tmp_working_directory, config_dir
    ) -> None:
        # config_dir is the monkeypatched VIBE_HOME for this test. PLANS_DIR
        # is intentionally NOT under it.
        from vibe.core.paths import VIBE_HOME

        assert PLANS_DIR.path != VIBE_HOME.path / "plans"
        assert not str(PLANS_DIR.path).startswith(str(config_dir))
