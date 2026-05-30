from __future__ import annotations

from opentelemetry import trace
import pytest

from tests.conftest import build_test_agent_loop, build_test_vibe_config
from vibe.core.llm.format import ResolvedToolCall
from vibe.core.tools.builtins.write_file import WriteFile, WriteFileArgs

_TRACER = trace.get_tracer("test")


async def _run_gate(loop, path: str):
    """Drive _execute_tool_call for a write_file to `path`; return the joined
    error text of any ToolResultEvent (empty string if none).
    """
    rtc = ResolvedToolCall(
        tool_name="write_file",
        tool_class=WriteFile,
        validated_args=WriteFileArgs(path=path, content="# plan\n"),
        call_id="t1",
    )
    errs: list[str] = []
    span = _TRACER.start_span("t")
    async for event in loop._execute_tool_call(span, rtc):
        err = getattr(event, "error", None)
        if err:
            errs.append(err)
    return "\n".join(errs)


@pytest.mark.asyncio
async def test_plan_gate_allows_write_to_plan_file(tmp_path) -> None:
    """In PLAN mode, write_file to the current plan file must NOT be blocked by
    the plan-mode write gate (regression: it was blocked when the plans
    allowlist failed to resolve to ALWAYS at gate time).
    """
    loop = build_test_agent_loop(config=build_test_vibe_config(), agent_name="plan")
    plan_path = loop._plan_session.plan_file_path
    plan_path.parent.mkdir(parents=True, exist_ok=True)

    errs = await _run_gate(loop, str(plan_path))
    assert "Plan mode: write operations disabled" not in errs
    assert plan_path.read_text().startswith("# plan")


@pytest.mark.asyncio
async def test_plan_gate_blocks_write_outside_plan_file(tmp_path) -> None:
    """The gate must still block writes to non-plan paths in PLAN mode."""
    loop = build_test_agent_loop(config=build_test_vibe_config(), agent_name="plan")
    target = tmp_path / "not-the-plan.py"

    errs = await _run_gate(loop, str(target))
    assert "Plan mode: write operations disabled" in errs
    assert not target.exists()
