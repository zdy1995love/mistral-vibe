from __future__ import annotations


class ThinkTagExtractor:
    """Stateful splitter for `[THINK]...[/THINK]` markers in streamed content.

    Some self-hosted backends (e.g. vLLM with `--reasoning-parser mistral`)
    fail to extract `[THINK]` blocks into a separate `reasoning` field when
    the input itself contains `[THINK]` blocks (history). This extractor
    recovers correctness on the client side by routing characters between a
    reasoning bucket and a content bucket as the stream arrives, while
    buffering trailing partial-tag matches across chunks.
    """

    OPEN = "[THINK]"
    CLOSE = "[/THINK]"

    def __init__(self) -> None:
        self.in_think = False
        self.pending = ""

    def feed(self, text: str) -> tuple[str, str]:
        text = self.pending + (text or "")
        self.pending = ""
        reasoning_parts: list[str] = []
        content_parts: list[str] = []

        while text:
            if self.in_think:
                # Inside a think block — only [/THINK] flips state.
                idx = text.find(self.CLOSE)
                if idx >= 0:
                    reasoning_parts.append(text[:idx])
                    text = text[idx + len(self.CLOSE) :]
                    self.in_think = False
                    continue
                partial = self._longest_partial_suffix(text, self.CLOSE)
                if partial:
                    reasoning_parts.append(text[:-partial])
                    self.pending = text[-partial:]
                else:
                    reasoning_parts.append(text)
                break

            # Outside a think block — accept either [THINK] (enter think)
            # or [/THINK] (orphan close, silently swallow). Orphan close
            # tags are a known token-level glitch under reasoning_effort=
            # high in long contexts: the model emits a `[/THINK]` without
            # a preceding `[THINK]` because vLLM's reasoning parser has
            # already terminated the first think block, and the model's
            # second-block opening got consumed as a special token. Strip
            # the leftover close tag so the visible content stays clean.
            open_idx = text.find(self.OPEN)
            close_idx = text.find(self.CLOSE)
            if open_idx == -1 and close_idx == -1:
                # No full marker. Buffer the longer partial suffix of
                # either marker so we don't split a tag across chunks.
                p_open = self._longest_partial_suffix(text, self.OPEN)
                p_close = self._longest_partial_suffix(text, self.CLOSE)
                partial = max(p_open, p_close)
                if partial:
                    content_parts.append(text[:-partial])
                    self.pending = text[-partial:]
                else:
                    content_parts.append(text)
                break

            # Pick whichever marker comes first.
            if open_idx == -1:
                first_idx, marker, enter = close_idx, self.CLOSE, False
            elif close_idx == -1:
                first_idx, marker, enter = open_idx, self.OPEN, True
            elif open_idx < close_idx:
                first_idx, marker, enter = open_idx, self.OPEN, True
            else:
                first_idx, marker, enter = close_idx, self.CLOSE, False

            content_parts.append(text[:first_idx])
            text = text[first_idx + len(marker) :]
            if enter:
                self.in_think = True
            # Else: orphan close — silently swallow, no state change.

        return "".join(reasoning_parts), "".join(content_parts)

    def flush(self) -> tuple[str, str]:
        if not self.pending:
            return "", ""
        leftover = self.pending
        self.pending = ""
        return (leftover, "") if self.in_think else ("", leftover)

    @staticmethod
    def _longest_partial_suffix(text: str, target: str) -> int:
        max_check = min(len(text), len(target) - 1)
        for i in range(max_check, 0, -1):
            if target.startswith(text[-i:]):
                return i
        return 0
