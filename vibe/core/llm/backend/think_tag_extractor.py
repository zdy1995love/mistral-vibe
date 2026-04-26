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
            target = self.CLOSE if self.in_think else self.OPEN
            idx = text.find(target)
            if idx >= 0:
                pre = text[:idx]
                (reasoning_parts if self.in_think else content_parts).append(pre)
                text = text[idx + len(target) :]
                self.in_think = not self.in_think
                continue

            partial = self._longest_partial_suffix(text, target)
            if partial:
                emit = text[:-partial]
                self.pending = text[-partial:]
            else:
                emit = text
            (reasoning_parts if self.in_think else content_parts).append(emit)
            break

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
