from __future__ import annotations

from typing import Any, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container, Vertical
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from vibe.cli.textual_ui.widgets.no_markup_static import NoMarkupStatic
from vibe.core.agents.models import AgentProfile

_PREVIEW_LINES = 8


def _build_option_text(profile: AgentProfile, is_active: bool) -> Text:
    text = Text(no_wrap=True)
    marker = "› " if is_active else "  "
    style = "bold" if is_active else ""
    text.append(marker, style="green" if is_active else "")
    text.append(profile.name, style=style)
    text.append("  ")
    text.append(f"({profile.agent_type.value})", style="dim")
    model_override = profile.overrides.get("active_model")
    if isinstance(model_override, str) and model_override:
        text.append("  ")
        text.append(f"[{model_override}]", style="cyan")
    if profile.description:
        text.append("  ")
        text.append(profile.description, style="dim")
    return text


def _build_preview(profile: AgentProfile, system_prompt: str | None) -> str:
    header = f"{profile.display_name} · safety={profile.safety.value}"
    if system_prompt is None:
        body = "(system prompt not resolvable for this profile)"
    else:
        lines = system_prompt.splitlines()[:_PREVIEW_LINES]
        body = "\n".join(lines)
        if len(system_prompt.splitlines()) > _PREVIEW_LINES:
            body += "\n…"
    return f"{header}\n\n{body}"


class AgentsPickerApp(Container):
    """Agents picker bottom app for /agents."""

    can_focus_children = True

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("v", "view_full", "View full prompt", show=False),
    ]

    class EditRequested(Message):
        def __init__(self, name: str) -> None:
            self.name = name
            super().__init__()

    class ViewFullRequested(Message):
        def __init__(self, name: str) -> None:
            self.name = name
            super().__init__()

    class Cancelled(Message):
        pass

    def __init__(
        self,
        profiles: list[AgentProfile],
        active_name: str,
        prompts: dict[str, str | None],
        **kwargs: Any,
    ) -> None:
        super().__init__(id="agentspicker-app", **kwargs)
        self._profiles = profiles
        self._active_name = active_name
        self._prompts = prompts

    def compose(self) -> ComposeResult:
        options = [
            Option(_build_option_text(p, p.name == self._active_name), id=p.name)
            for p in self._profiles
        ]
        with Vertical(id="agentspicker-content"):
            yield NoMarkupStatic("Select Agent", classes="agentspicker-title")
            yield OptionList(*options, id="agentspicker-options")
            initial = self._profiles[0] if self._profiles else None
            preview = (
                _build_preview(initial, self._prompts.get(initial.name))
                if initial is not None
                else ""
            )
            yield NoMarkupStatic(preview, classes="agentspicker-preview")
            yield NoMarkupStatic(
                "↑↓ Navigate  Enter Edit  v View full  Esc Cancel",
                classes="agentspicker-help",
            )

    def on_mount(self) -> None:
        option_list = self.query_one(OptionList)
        for i, profile in enumerate(self._profiles):
            if profile.name == self._active_name:
                option_list.highlighted = i
                break
        option_list.focus()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option_id is None:
            return
        profile = next((p for p in self._profiles if p.name == event.option_id), None)
        if profile is None:
            return
        preview = _build_preview(profile, self._prompts.get(profile.name))
        self.query_one(".agentspicker-preview", NoMarkupStatic).update(preview)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self.post_message(self.EditRequested(event.option.id))

    def action_cancel(self) -> None:
        self.post_message(self.Cancelled())

    def action_view_full(self) -> None:
        option_list = self.query_one(OptionList)
        if option_list.highlighted is None:
            return
        option = option_list.get_option_at_index(option_list.highlighted)
        if option.id is None:
            return
        self.post_message(self.ViewFullRequested(option.id))
