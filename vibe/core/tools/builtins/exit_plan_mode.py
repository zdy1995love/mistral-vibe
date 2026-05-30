from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
import re
import time
from typing import ClassVar, cast

from pydantic import BaseModel

from vibe.core.agents.models import BuiltinAgentName
from vibe.core.logger import logger
from vibe.core.paths import PLANS_DIR
from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    InvokeContext,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.builtins.ask_user_question import (
    AskUserQuestionArgs,
    AskUserQuestionResult,
    Choice,
    Question,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData
from vibe.core.utils.io import read_safe

_PLAN_FILE_PATTERN = re.compile(r"^\d{10}-[a-z]+(?:-[a-z]+){2,}\.md$")
_FALLBACK_RECENT_WINDOW_S = 24 * 3600  # 24 hours


def _find_recent_plan_file() -> Path | None:
    """Scan PLANS_DIR for a recent <ts>-<slug>.md file.

    Returns the most-recently-modified plan file in the directory, but only
    if it was modified within the last 24 hours. Used as a defensive fallback
    when `InvokeContext.plan_file_path` doesn't resolve to an existing file
    — there are rare paths (long sessions, certain reset edge cases) where
    the cached `PlanSession.plan_file_path` and the path the LLM actually
    wrote to disagree, and we'd rather recover than block the user.
    """
    plans_dir = PLANS_DIR.path
    if not plans_dir.is_dir():
        return None
    now = time.time()
    candidates: list[tuple[float, Path]] = []
    for entry in plans_dir.iterdir():
        if not entry.is_file() or not _PLAN_FILE_PATTERN.match(entry.name):
            continue
        mtime = entry.stat().st_mtime
        if now - mtime > _FALLBACK_RECENT_WINDOW_S:
            continue
        candidates.append((mtime, entry))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


class ExitPlanModeArgs(BaseModel):
    pass


class ExitPlanModeResult(BaseModel):
    switched: bool
    message: str


class ExitPlanModeConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


class ExitPlanMode(
    BaseTool[ExitPlanModeArgs, ExitPlanModeResult, ExitPlanModeConfig, BaseToolState],
    ToolUIData[ExitPlanModeArgs, ExitPlanModeResult],
):
    description: ClassVar[str] = (
        "Signal that your plan is complete and you are ready to start "
        "implementing. The user is asked to confirm; on approval the "
        "conversation context is wiped and a fresh implementation context "
        "is started with the plan as the first user message. Only call "
        "this after writing the full plan to the plan file path supplied "
        "in the plan-mode system reminder."
    )
    mutates_state: ClassVar[bool] = False

    @classmethod
    def format_call_display(cls, args: ExitPlanModeArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary="Ready to exit plan mode")

    @classmethod
    def format_result_display(cls, result: ExitPlanModeResult) -> ToolResultDisplay:
        return ToolResultDisplay(success=result.switched, message=result.message)

    @classmethod
    def get_status_text(cls) -> str:
        return "Waiting for user confirmation"

    async def run(
        self, args: ExitPlanModeArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[ExitPlanModeResult, None]:
        if ctx is None or ctx.agent_manager is None:
            raise ToolError("ExitPlanMode requires an agent manager context.")

        if ctx.agent_manager.active_profile.name != BuiltinAgentName.PLAN:
            raise ToolError("ExitPlanMode can only be used in plan mode.")

        if ctx.user_input_callback is None:
            raise ToolError("ExitPlanMode requires an interactive UI.")

        plan_path = ctx.plan_file_path
        if plan_path is None or not plan_path.is_file():
            fallback = _find_recent_plan_file()
            if fallback is None:
                raise ToolError(
                    "No plan file found. Write your plan to the plan-mode plan "
                    "file (path is in the plan-mode system reminder) before "
                    "calling ExitPlanMode."
                )
            logger.warning(
                "exit_plan_mode: ctx.plan_file_path=%r missing on disk; "
                "falling back to most-recent plan file %s (mtime within "
                "%ss). This indicates PlanSession state drifted from the "
                "filesystem; investigate if it recurs.",
                str(plan_path) if plan_path else None,
                fallback,
                _FALLBACK_RECENT_WINDOW_S,
            )
            plan_path = fallback
        try:
            plan_content = read_safe(plan_path).text
        except OSError as e:
            raise ToolError(f"Failed to read plan file at {plan_path}: {e}") from e
        if not plan_content.strip():
            raise ToolError(
                "Plan file is empty. Write the plan before calling ExitPlanMode."
            )

        confirmation = AskUserQuestionArgs(
            footer_note=f"Plan: {plan_path} (Ctrl+G to edit)",
            questions=[
                Question(
                    question=(
                        "Plan is complete. Approve and start a fresh "
                        "implementation context with this plan as the seed?"
                    ),
                    header="Plan ready",
                    options=[
                        Choice(
                            label="Yes, and auto approve edits",
                            description=(
                                "Wipe planning context, start fresh with "
                                "auto-approve edits enabled."
                            ),
                        ),
                        Choice(
                            label="Yes, and request approval for edits",
                            description=(
                                "Wipe planning context, start fresh in the "
                                "profile you were in before plan mode."
                            ),
                        ),
                        Choice(
                            label="No",
                            description="Stay in plan mode and continue planning.",
                        ),
                    ],
                )
            ],
        )

        result = await ctx.user_input_callback(confirmation)
        result = cast(AskUserQuestionResult, result)

        if result.cancelled or not result.answers:
            yield ExitPlanModeResult(
                switched=False,
                message=(
                    "User cancelled. Staying in plan mode. Continue refining "
                    "the plan if you have changes to make; otherwise wait "
                    "for the next user message before calling exit_plan_mode "
                    "again."
                ),
            )
            return

        answer = result.answers[0]
        answer_lower = answer.answer.lower()

        if answer_lower == "yes, and auto approve edits":
            target_profile = BuiltinAgentName.ACCEPT_EDITS
        elif answer_lower == "yes, and request approval for edits":
            stashed = ctx.agent_manager.pre_plan_profile
            target_profile = stashed or BuiltinAgentName.DEFAULT
            # Defensive: stashed profile may have been removed mid-plan
            # (e.g., agent toml deleted while user was planning).
            available = getattr(ctx.agent_manager, "available_agents", None)
            if stashed and available is not None and stashed not in available:
                target_profile = BuiltinAgentName.DEFAULT
        elif answer.is_other:
            yield ExitPlanModeResult(
                switched=False,
                message=(
                    f"Staying in plan mode. User feedback: {answer.answer}\n"
                    f"ACTION REQUIRED: update the plan file ({plan_path}) "
                    f"with the requested changes using write_file or "
                    f"search_replace BEFORE calling exit_plan_mode again. "
                    f"Calling exit_plan_mode without addressing the feedback "
                    f"will produce the same plan and the same response."
                ),
            )
            return
        else:
            yield ExitPlanModeResult(
                switched=False,
                message=(
                    "Staying in plan mode. The user declined; continue "
                    "refining the plan if you have ideas to address their "
                    "concern, or wait for the next user message before "
                    "calling exit_plan_mode again."
                ),
            )
            return

        if ctx.request_fork_to_dev_callback is None:
            raise ToolError(
                "Fork-to-dev not available in this context — cannot exit plan mode."
            )
        ctx.request_fork_to_dev_callback(plan_content, plan_path, target_profile)
        yield ExitPlanModeResult(
            switched=True,
            message=(f"Plan approved. Forking to {target_profile} with plan as seed."),
        )
