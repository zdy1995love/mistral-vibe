from __future__ import annotations

from enum import Enum, auto
import json
import re
import secrets
import string

_VALID_TOOL_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,127}$")


class _State(Enum):
    BEFORE = auto()
    IN_NAME = auto()
    IN_ARGS = auto()


class CompletedToolCall:
    __slots__ = ("id", "index", "name", "arguments")

    def __init__(self, id: str, index: int, name: str, arguments: str) -> None:
        self.id = id
        self.index = index
        self.name = name
        self.arguments = arguments


class MistralToolCallTextExtractor:
    """Stateful recovery of Mistral tool calls leaked as plain text in streams.

    Some self-hosted backends (vLLM ``--tool-call-parser mistral`` with HF
    tokenizer, prior to vLLM 0.20.0) fail to convert
    ``[TOOL_CALLS]<name>{<json>}`` text into structured ``delta.tool_calls``
    during streaming and instead emit it byte-by-byte into ``delta.content``.
    See vLLM issues #9059, #16958, and PR #39294.

    This extractor scans incremental content, suppresses the leaked literal
    text, and synthesizes ``tool_calls`` once each call's JSON arguments are
    complete (matching brace depth, string-aware).

    Wire formats handled:
      * v11+ Tekken: ``[TOOL_CALLS]<name>{<args>}`` (also tolerates
        ``[ARGS]`` separator if present, by stripping it)
      * Multiple back-to-back: ``[TOOL_CALLS]a{1}[TOOL_CALLS]b{2}``

    Wire formats NOT handled (returns text as content unchanged):
      * Pre-v11 array form: ``[TOOL_CALLS][{...}, {...}]``
        (this format isn't observed in practice for current Mistral models
        served via vLLM HF tokenizer; if needed, add a branch in IN_NAME.)

    Safety: if ``[TOOL_CALLS]`` appears in legitimate content (e.g. user
    asking the model to explain the format) and is not followed by a JSON
    object within ``MAX_NAME_CHARS`` chars, the marker is re-emitted as
    content rather than being silently swallowed.
    """

    BOT = "[TOOL_CALLS]"
    ARGS_SEP = "[ARGS]"
    MAX_NAME_CHARS = 256

    def __init__(self) -> None:
        self._buffer = ""
        self._state = _State.BEFORE
        self._name = ""
        self._args = ""
        self._brace_depth = 0
        self._in_string = False
        self._escape = False
        self._index = 0

    def feed(self, text: str) -> tuple[str, list[CompletedToolCall]]:
        """Feed an incremental content delta.

        Returns ``(content_to_emit, completed_calls)``. ``content_to_emit``
        is the portion of ``text`` that is genuine assistant content (with
        any leaked tool-call text removed). ``completed_calls`` is the list
        of tool calls whose JSON arguments closed within this chunk.
        """
        if not text:
            return ("", [])
        self._buffer += text
        content_parts: list[str] = []
        completed: list[CompletedToolCall] = []

        while self._buffer:
            if self._state is _State.BEFORE:
                idx = self._buffer.find(self.BOT)
                if idx >= 0:
                    if idx > 0:
                        content_parts.append(self._buffer[:idx])
                    self._buffer = self._buffer[idx + len(self.BOT) :]
                    self._state = _State.IN_NAME
                    self._name = ""
                    continue
                partial = self._longest_partial_suffix(self._buffer, self.BOT)
                if partial:
                    if len(self._buffer) > partial:
                        content_parts.append(self._buffer[:-partial])
                    self._buffer = self._buffer[-partial:]
                else:
                    content_parts.append(self._buffer)
                    self._buffer = ""
                break

            if self._state is _State.IN_NAME:
                brace_idx = self._buffer.find("{")
                if brace_idx >= 0:
                    self._name += self._buffer[:brace_idx]
                    self._buffer = self._buffer[brace_idx:]
                    self._name = self._name.replace(self.ARGS_SEP, "").strip()
                    if not self._name:
                        content_parts.append(self.BOT)
                        self._state = _State.BEFORE
                        continue
                    self._state = _State.IN_ARGS
                    self._brace_depth = 0
                    self._in_string = False
                    self._escape = False
                    self._args = ""
                    continue
                if len(self._name) + len(self._buffer) > self.MAX_NAME_CHARS:
                    content_parts.append(self.BOT + self._name + self._buffer)
                    self._buffer = ""
                    self._name = ""
                    self._state = _State.BEFORE
                    break
                self._name += self._buffer
                self._buffer = ""
                break

            # _State.IN_ARGS
            consumed = self._consume_args(self._buffer)
            if consumed is None:
                self._args += self._buffer
                self._buffer = ""
                break
            self._args += self._buffer[:consumed]
            self._buffer = self._buffer[consumed:]
            if self._is_valid_tool_call(self._name, self._args):
                completed.append(
                    CompletedToolCall(
                        id=self._gen_id(),
                        index=self._index,
                        name=self._name,
                        arguments=self._args,
                    )
                )
                self._index += 1
            else:
                # False positive (e.g. model wrote literal example text like
                # `[TOOL_CALLS]<name>{<args>}` for documentation). Re-emit as
                # content rather than dispatching a malformed tool call.
                content_parts.append(self.BOT + self._name + self._args)
            self._reset_call_state()

        return ("".join(content_parts), completed)

    def flush(self) -> tuple[str, list[CompletedToolCall]]:
        """End-of-stream call. Re-emit any unrecoverable buffered text."""
        if self._state is _State.IN_NAME:
            leftover = self.BOT + self._name + self._buffer
            self._reset_call_state()
            self._state = _State.BEFORE
            self._buffer = ""
            return (leftover, [])
        if self._state is _State.IN_ARGS:
            self._reset_call_state()
            self._state = _State.BEFORE
            self._buffer = ""
            return ("", [])
        leftover = self._buffer
        self._buffer = ""
        return (leftover, [])

    def _reset_call_state(self) -> None:
        self._name = ""
        self._args = ""
        self._brace_depth = 0
        self._in_string = False
        self._escape = False
        self._state = _State.BEFORE

    def _consume_args(self, s: str) -> int | None:
        for i, ch in enumerate(s):
            if self._escape:
                self._escape = False
                continue
            if self._in_string:
                if ch == "\\":
                    self._escape = True
                    continue
                if ch == '"':
                    self._in_string = False
                continue
            if ch == '"':
                self._in_string = True
                continue
            if ch == "{":
                self._brace_depth += 1
                continue
            if ch == "}":
                self._brace_depth -= 1
                if self._brace_depth == 0:
                    return i + 1
        return None

    @staticmethod
    def _is_valid_tool_call(name: str, args: str) -> bool:
        """Sanity-check a candidate match before promoting it to a tool call.

        Guards against false positives when the model writes literal example
        text like `[TOOL_CALLS]<name>{<args>}` mid-conversation: name must
        look like a real identifier and args must be valid JSON.
        """
        if not _VALID_TOOL_NAME_RE.match(name):
            return False
        try:
            json.loads(args)
        except json.JSONDecodeError:
            return False
        return True

    @staticmethod
    def _gen_id() -> str:
        alphabet = string.ascii_letters + string.digits
        return "".join(secrets.choice(alphabet) for _ in range(9))

    @staticmethod
    def _longest_partial_suffix(text: str, target: str) -> int:
        max_check = min(len(text), len(target) - 1)
        for i in range(max_check, 0, -1):
            if target.startswith(text[-i:]):
                return i
        return 0
