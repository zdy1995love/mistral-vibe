from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

from vibe.core.hooks.models import HookMessageSeverity

if TYPE_CHECKING:
    from vibe.cli.textual_ui.app import ChatScroll

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from vibe.cli.textual_ui.ansi_markdown import AnsiMarkdown as Markdown
from vibe.cli.textual_ui.widgets.no_markup_static import NoMarkupStatic
from vibe.cli.textual_ui.widgets.spinner import SpinnerMixin, SpinnerType

# Throttle window for streaming Static.update() flushes. Even after dropping
# the per-chunk Markdown reparse, plain-text refresh still does an O(N)
# re-render per call; coalescing sub-frame deltas keeps UI thread cost
# bounded under high token rates. 33ms ≈ 30fps, below human flicker.
_STREAM_FLUSH_INTERVAL_S: float = 0.033


class _PlainTextStreamAdapter:
    """Mimics Textual's `MarkdownStream` write/stop API but accumulates plain
    text into a `NoMarkupStatic`. Used during streaming so each chunk costs
    only a Static.update (no markdown parse, no syntax highlight). The body
    is upgraded to a real `Markdown` widget once at `stop_stream()` —
    paying parse cost O(N) once instead of per-chunk."""

    def __init__(self, static: NoMarkupStatic) -> None:
        self._static = static
        self._buffer = ""
        self._stopped = False

    async def write(self, fragment: str) -> None:
        if self._stopped:
            raise RuntimeError("Can't write to the stream after it has stopped.")
        if not fragment:
            return
        self._buffer += fragment
        self._static.update(self._buffer)

    async def stop(self) -> None:
        self._stopped = True

    @property
    def buffer(self) -> str:
        return self._buffer

    def reset_to(self, content: str) -> None:
        """Reset the visible content and internal buffer to `content`. Used
        when ReasoningMessage uncollapses mid-stream and needs to replay
        the accumulated content the user couldn't see while collapsed."""
        self._buffer = content
        self._static.update(content)


class NonSelectableStatic(NoMarkupStatic):
    @property
    def text_selection(self) -> None:
        return None

    @text_selection.setter
    def text_selection(self, value: Any) -> None:
        pass

    def get_selection(self, selection: Any) -> None:
        return None


class ExpandingBorder(NonSelectableStatic):
    def render(self) -> str:
        height = self.size.height
        return "\n".join(["⎢"] * (height - 1) + ["⎣"])

    def on_resize(self) -> None:
        self.refresh()


class UserMessage(Static):
    def __init__(
        self, content: str, pending: bool = False, message_index: int | None = None
    ) -> None:
        super().__init__()
        self.add_class("user-message")
        self._content = content
        self._pending = pending
        self.message_index: int | None = message_index

    def get_content(self) -> str:
        return self._content

    def compose(self) -> ComposeResult:
        with Horizontal(classes="user-message-container"):
            yield NoMarkupStatic(self._content, classes="user-message-content")
            if self._pending:
                self.add_class("pending")

    async def set_pending(self, pending: bool) -> None:
        if pending == self._pending:
            return

        self._pending = pending

        if pending:
            self.add_class("pending")
            return

        self.remove_class("pending")


class StreamingMessageBase(Static):
    # Throttle window for streaming Static.update() flushes — overridable in
    # tests so the original direct-write semantics still hold under unit
    # tests that don't care about throttling.
    _flush_interval_s: float = _STREAM_FLUSH_INTERVAL_S

    # Class-level defaults so test doubles that bypass __init__ can still
    # use the new fields without tripping AttributeError.
    _streaming_static: NoMarkupStatic | None = None
    _finalized: bool = False

    def __init__(self, content: str) -> None:
        super().__init__()
        self._content = content
        self._streaming_static: NoMarkupStatic | None = None
        self._markdown: Markdown | None = None
        self._stream: _PlainTextStreamAdapter | None = None
        self._content_initialized = False
        self._to_write_buffer = ""
        self._last_flush_monotonic: float = 0.0
        self._finalized = False

    def _create_streaming_static(self, *, classes: str = "") -> NoMarkupStatic:
        """Build the plain-text body widget yielded by `compose`. Subclasses
        call this once and yield the result."""
        widget = NoMarkupStatic("", classes=classes)
        self._streaming_static = widget
        return widget

    def _build_markdown_widget(self, content: str) -> Markdown:
        """Build the final Markdown widget that replaces the streaming static
        on `_finalize_to_markdown`. Subclasses override to set classes."""
        return Markdown(content)

    def _ensure_stream(self) -> _PlainTextStreamAdapter:
        if self._stream is None:
            if self._streaming_static is None:
                raise RuntimeError(
                    "Streaming static not initialized. compose() must be called first."
                )
            self._stream = _PlainTextStreamAdapter(self._streaming_static)
        return self._stream

    def _is_chat_at_bottom(self) -> bool:
        try:
            chat = cast("ChatScroll", self.app.query_one("#chat"))
            return chat.is_at_bottom
        except Exception:
            return True

    async def append_content(self, content: str) -> None:
        if not content:
            return

        self._content += content

        if not self._should_write_content():
            return

        if not self._is_chat_at_bottom():
            # Scrolled away from bottom — keep buffering; will flush in
            # write_initial_content / stop_stream / next at-bottom append.
            self._to_write_buffer += content
            return

        # Coalesce sub-frame deltas: under the flush interval, accumulate
        # and let a later chunk (or stop_stream) drive the actual write.
        now = time.monotonic()
        self._to_write_buffer += content
        if now - self._last_flush_monotonic < self._flush_interval_s:
            return

        to_write = self._to_write_buffer
        self._to_write_buffer = ""
        self._last_flush_monotonic = now
        stream = self._ensure_stream()
        await stream.write(to_write)

    async def write_initial_content(self) -> None:
        if self._content_initialized:
            return
        self._content_initialized = True
        if self._content and self._should_write_content():
            stream = self._ensure_stream()
            await stream.write(self._content)
            self._to_write_buffer = ""

    async def stop_stream(self) -> None:
        if self._to_write_buffer and self._should_write_content():
            stream = self._ensure_stream()
            await stream.write(self._to_write_buffer)
        self._to_write_buffer = ""

        if self._stream is not None:
            await self._stream.stop()
            self._stream = None

        if self._finalized:
            return
        await self._finalize_to_markdown()

    async def _finalize_to_markdown(self) -> None:
        """Replace the plain-text streaming widget with a Markdown widget
        carrying the full accumulated content. Pays the parse cost once."""
        self._finalized = True

        if self._streaming_static is None:
            return

        parent = self._streaming_static.parent
        if parent is None:
            # Not mounted (unit tests or never composed) — nothing to swap.
            return

        if not self._content:
            # Nothing to render as Markdown — leave the static in place.
            return

        markdown = self._build_markdown_widget("")
        # Hide the new widget while it parses to avoid an empty-flash, then
        # reveal once the content is loaded (or keep hidden if collapsed).
        markdown.display = False
        await parent.mount(markdown, after=self._streaming_static)
        await markdown.update(self._content)
        markdown.display = self._should_write_content()
        self._markdown = markdown
        await self._streaming_static.remove()
        self._streaming_static = None

    def _should_write_content(self) -> bool:
        return True

    def get_content(self) -> str:
        return self._content

    def is_stripped_content_empty(self) -> bool:
        return self._content.strip() == ""


class AssistantMessage(StreamingMessageBase):
    def __init__(self, content: str) -> None:
        super().__init__(content)
        self.add_class("assistant-message")

    def compose(self) -> ComposeResult:
        yield self._create_streaming_static()


class ReasoningMessage(SpinnerMixin, StreamingMessageBase):
    SPINNER_TYPE = SpinnerType.PULSE
    SPINNING_TEXT = "Thinking"
    COMPLETED_TEXT = "Thought"

    def __init__(self, content: str, collapsed: bool = True) -> None:
        super().__init__(content)
        self.add_class("reasoning-message")
        self.collapsed = collapsed
        self._indicator_widget: Static | None = None
        self._triangle_widget: Static | None = None
        self.init_spinner()

    def compose(self) -> ComposeResult:
        with Vertical(classes="reasoning-message-wrapper"):
            with Horizontal(classes="reasoning-message-header"):
                self._indicator_widget = NonSelectableStatic(
                    self._spinner.current_frame(), classes="reasoning-indicator"
                )
                yield self._indicator_widget
                self._status_text_widget = NoMarkupStatic(
                    self.SPINNING_TEXT, classes="reasoning-collapsed-text"
                )
                yield self._status_text_widget
                self._triangle_widget = NonSelectableStatic(
                    "▶" if self.collapsed else "▼", classes="reasoning-triangle"
                )
                yield self._triangle_widget
            body = self._create_streaming_static(classes="reasoning-message-content")
            body.display = not self.collapsed
            yield body

    def _build_markdown_widget(self, content: str) -> Markdown:
        return Markdown(content, classes="reasoning-message-content")

    def on_mount(self) -> None:
        self.start_spinner_timer()

    def on_resize(self) -> None:
        self.refresh_spinner()

    async def on_click(self) -> None:
        await self._toggle_collapsed()

    async def _toggle_collapsed(self) -> None:
        await self.set_collapsed(not self.collapsed)

    def _should_write_content(self) -> bool:
        return not self.collapsed

    async def set_collapsed(self, collapsed: bool) -> None:
        if self.collapsed == collapsed:
            return

        self.collapsed = collapsed
        if self._triangle_widget:
            self._triangle_widget.update("▶" if collapsed else "▼")

        # Post-stream: Markdown widget already exists, just toggle visibility.
        if self._markdown is not None:
            self._markdown.display = not collapsed
            return

        # Mid-stream: streaming static is the body. Toggle display, and on
        # uncollapse replay accumulated content (writes were skipped while
        # collapsed via _should_write_content gate).
        if self._streaming_static is None:
            return

        self._streaming_static.display = not collapsed
        if not collapsed and self._content:
            stream = self._ensure_stream()
            stream.reset_to(self._content)
            self._to_write_buffer = ""


class UserCommandMessage(Static):
    def __init__(self, content: str) -> None:
        super().__init__()
        self.add_class("user-command-message")
        self._content = content

    def compose(self) -> ComposeResult:
        with Horizontal(classes="user-command-container"):
            yield ExpandingBorder(classes="user-command-border")
            with Vertical(classes="user-command-content"):
                yield Markdown(self._content)


class WhatsNewMessage(Static):
    def __init__(self, content: str) -> None:
        super().__init__()
        self.add_class("whats-new-message")
        self._content = content

    def compose(self) -> ComposeResult:
        yield Markdown(self._content)


class InterruptMessage(Static):
    def __init__(self) -> None:
        super().__init__()
        self.add_class("interrupt-message")

    def compose(self) -> ComposeResult:
        with Horizontal(classes="interrupt-container"):
            yield ExpandingBorder(classes="interrupt-border")
            yield NoMarkupStatic(
                "Interrupted · What should Vibe do instead?",
                classes="interrupt-content",
            )


class BashOutputMessage(Static):
    def __init__(
        self,
        command: str,
        cwd: str,
        output: str = "",
        exit_code: int = 0,
        *,
        pending: bool = False,
    ) -> None:
        super().__init__()
        self.add_class("bash-output-message")
        self._command = command
        self._cwd = cwd
        self._output = output.rstrip("\n")
        self._exit_code = exit_code
        self._pending = pending
        self._output_widget: NoMarkupStatic | None = None
        self._output_container: Horizontal | None = None
        self._prompt_widget: NonSelectableStatic | None = None

    def compose(self) -> ComposeResult:
        status_class = (
            "bash-error"
            if not self._pending and self._exit_code != 0
            else "bash-success"
        )
        self.add_class(status_class)
        with Horizontal(classes="bash-command-line"):
            self._prompt_widget = NonSelectableStatic(
                "$ ", classes=f"bash-prompt {status_class}"
            )
            yield self._prompt_widget
            yield NoMarkupStatic(self._command, classes="bash-command")
        if not self._pending:
            self._output_container = Horizontal(classes="bash-output-container")
            with self._output_container:
                yield ExpandingBorder(classes="bash-output-border")
                self._output_widget = NoMarkupStatic(
                    self._output, classes="bash-output"
                )
                yield self._output_widget

    async def _ensure_output_container(self) -> None:
        if self._output_container is not None:
            return
        self._output_widget = NoMarkupStatic("", classes="bash-output")
        self._output_container = Horizontal(
            ExpandingBorder(classes="bash-output-border"),
            self._output_widget,
            classes="bash-output-container",
        )
        await self.mount(self._output_container)

    async def append_output(self, text: str) -> None:
        await self._ensure_output_container()
        self._output += text
        if self._output_widget:
            self._output_widget.update(self._output.rstrip("\n"))

    async def finish(self, exit_code: int, *, interrupted: bool = False) -> None:
        self._exit_code = exit_code
        self._pending = False
        if interrupted:
            self.remove_class("bash-success")
            self.add_class("bash-interrupted")
            if self._prompt_widget:
                self._prompt_widget.remove_class("bash-success")
                self._prompt_widget.add_class("bash-interrupted")
        elif exit_code != 0:
            self.remove_class("bash-success")
            self.add_class("bash-error")
            if self._prompt_widget:
                self._prompt_widget.remove_class("bash-success")
                self._prompt_widget.add_class("bash-error")
        if interrupted:
            suffix = (
                "\n(interrupted)"
                if self._output and not self._output.endswith("\n")
                else "(interrupted)"
            )
            self._output += suffix
        if not self._output:
            self._output = "(no output)"
        await self._ensure_output_container()
        if self._output_widget:
            self._output_widget.update(self._output.rstrip("\n"))


class ErrorMessage(Static):
    def __init__(self, error: str, collapsed: bool = False) -> None:
        super().__init__()
        self.add_class("error-message")
        self._error = error
        self.collapsed = collapsed
        self._content_widget: Static | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(classes="error-container"):
            yield ExpandingBorder(classes="error-border")
            self._content_widget = NoMarkupStatic(
                f"Error: {self._error}", classes="error-content"
            )
            yield self._content_widget

    def set_collapsed(self, collapsed: bool) -> None:
        pass


class HookRunContainer(Vertical):
    def __init__(self) -> None:
        super().__init__(classes="hook-run-container")
        self.display = False

    async def add_message(self, widget: HookSystemMessageLine) -> None:
        await self.mount(widget)
        self.display = True


_HOOK_SEVERITY_ICONS: dict[HookMessageSeverity, str] = {
    HookMessageSeverity.OK: "✓",
    HookMessageSeverity.WARNING: "⚠",
    HookMessageSeverity.ERROR: "✗",
}


class HookSystemMessageLine(Static):
    def __init__(
        self,
        hook_name: str,
        content: str,
        severity: HookMessageSeverity = HookMessageSeverity.WARNING,
    ) -> None:
        super().__init__()
        self.add_class("hook-system-message")
        self.add_class(f"hook-severity-{severity}")
        self._hook_name = hook_name
        self._content = content
        self._severity = severity

    def compose(self) -> ComposeResult:
        icon = _HOOK_SEVERITY_ICONS.get(
            self._severity, _HOOK_SEVERITY_ICONS[HookMessageSeverity.WARNING]
        )
        with Horizontal(classes="hook-system-container"):
            yield NonSelectableStatic(icon, classes="hook-system-icon")
            yield NoMarkupStatic(
                f"[{self._hook_name}] {self._content}", classes="hook-system-content"
            )


class WarningMessage(Static):
    def __init__(self, message: str, show_border: bool = True) -> None:
        super().__init__()
        self.add_class("warning-message")
        self._message = message
        self._show_border = show_border

    def compose(self) -> ComposeResult:
        with Horizontal(classes="warning-container"):
            if self._show_border:
                yield ExpandingBorder(classes="warning-border")
            yield NoMarkupStatic(self._message, classes="warning-content")
