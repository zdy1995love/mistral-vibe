from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import ClassVar, cast

from pydantic import BaseModel

from vibe.core.agents.models import BuiltinAgentName
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

        if ctx.plan_file_path is None or not ctx.plan_file_path.is_file():
            raise ToolError(
                "No plan file found. Write your plan to the plan-mode plan "
                "file (path is in the plan-mode system reminder) before "
                "calling ExitPlanMode."
            )
        try:
            plan_content = read_safe(ctx.plan_file_path).text
        except OSError as e:
            raise ToolError(
                f"Failed to read plan file at {ctx.plan_file_path}: {e}"
            ) from e
        if not plan_content.strip():
            raise ToolError(
                "Plan file is empty. Write the plan before calling ExitPlanMode."
            )

        confirmation = AskUserQuestionArgs(
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
            content_preview=plan_content,
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
                    f"ACTION REQUIRED: update the plan file ({ctx.plan_file_path}) "
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
        ctx.request_fork_to_dev_callback(
            plan_content, ctx.plan_file_path, target_profile
        )
        yield ExitPlanModeResult(
            switched=True,
            message=(f"Plan approved. Forking to {target_profile} with plan as seed."),
        )
