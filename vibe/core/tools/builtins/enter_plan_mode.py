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


class EnterPlanModeArgs(BaseModel):
    pass


class EnterPlanModeResult(BaseModel):
    switched: bool
    message: str


class EnterPlanModeConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


class EnterPlanMode(
    BaseTool[
        EnterPlanModeArgs, EnterPlanModeResult, EnterPlanModeConfig, BaseToolState
    ],
    ToolUIData[EnterPlanModeArgs, EnterPlanModeResult],
):
    description: ClassVar[str] = (
        "Switch the conversation into read-only plan mode. While plan mode is "
        "active, write/execute tools (Bash, WriteFile, SearchReplace, Skill, "
        "Task, MCP tools) are blocked and only exploration tools work. Use this "
        "when the user asks to discuss or plan before executing changes."
    )
    mutates_state: ClassVar[bool] = False

    @classmethod
    def format_call_display(cls, args: EnterPlanModeArgs) -> ToolCallDisplay:
        return ToolCallDisplay(summary="Requesting to enter plan mode")

    @classmethod
    def format_result_display(cls, result: EnterPlanModeResult) -> ToolResultDisplay:
        return ToolResultDisplay(success=result.switched, message=result.message)

    @classmethod
    def get_status_text(cls) -> str:
        return "Waiting for user confirmation"

    async def run(
        self, args: EnterPlanModeArgs, ctx: InvokeContext | None = None
    ) -> AsyncGenerator[EnterPlanModeResult, None]:
        if ctx is None or ctx.agent_manager is None:
            raise ToolError("EnterPlanMode requires an agent manager context.")

        if ctx.agent_manager.active_profile.name == BuiltinAgentName.PLAN:
            raise ToolError("Already in plan mode.")

        if ctx.user_input_callback is None:
            raise ToolError("EnterPlanMode requires an interactive UI.")

        confirmation = AskUserQuestionArgs(
            questions=[
                Question(
                    question=(
                        "Switch to plan mode? Write/exec tools will be blocked "
                        "until you /exit_plan_mode or accept-edits."
                    ),
                    header="Plan mode",
                    options=[
                        Choice(
                            label="Yes, enter plan mode",
                            description=(
                                "Switch active profile to plan; only read-only "
                                "tools will run."
                            ),
                        ),
                        Choice(label="No", description="Stay in the current profile."),
                    ],
                )
            ]
        )

        result = await ctx.user_input_callback(confirmation)
        result = cast(AskUserQuestionResult, result)

        if result.cancelled or not result.answers:
            yield EnterPlanModeResult(
                switched=False,
                message="User cancelled. Staying in the current profile.",
            )
            return

        answer = result.answers[0]
        if answer.answer.lower().startswith("yes"):
            if ctx.switch_agent_callback:
                await ctx.switch_agent_callback(BuiltinAgentName.PLAN)
            else:
                ctx.agent_manager.switch_profile(BuiltinAgentName.PLAN)
            yield EnterPlanModeResult(
                switched=True,
                message=(
                    "Switched to plan mode. Use ExitPlanMode when ready to implement."
                ),
            )
            return

        yield EnterPlanModeResult(
            switched=False, message="Staying in the current profile."
        )
