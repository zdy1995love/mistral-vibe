from __future__ import annotations

from vibe.core.middleware import ConversationContext, MiddlewareResult, ResetReason
from vibe.core.types import AgentStats, MessageList, Role

CLEARABLE_TOOLS: frozenset[str] = frozenset(
    {"bash", "read_file", "write_file", "search_replace", "grep", "web_fetch", "web_search"}
)

_CLEARED_MARKER = "[Old tool result cleared"


def micro_compact(
    messages: MessageList,
    threshold: int,
    micro_compact_ratio: float,
    micro_keep_last: int,
    stats: AgentStats,
) -> int:
    """Clear old tool results to free context. Returns estimated tokens reclaimed."""
    micro_threshold = int(threshold * micro_compact_ratio)
    if stats.context_tokens < micro_threshold:
        return 0

    target_water = int(threshold * 0.5)
    tokens_to_save = stats.context_tokens - target_water
    if tokens_to_save <= 0:
        return 0

    # Find last N indices per tool name → protected set
    tool_indices: dict[str, list[int]] = {}
    for i, msg in enumerate(messages):
        if msg.role == Role.tool and msg.name in CLEARABLE_TOOLS:
            tool_indices.setdefault(msg.name, []).append(i)

    # Guard against Python slicing quirk: list[-0:] returns the whole list,
    # so an unguarded `indices[-micro_keep_last:]` with keep_last=0 would
    # protect everything instead of nothing.
    protected: set[int] = set()
    if micro_keep_last > 0:
        for indices in tool_indices.values():
            for idx in indices[-micro_keep_last:]:
                protected.add(idx)

    # Build clearable candidates: (index, token_estimate)
    candidates: list[tuple[int, int]] = []
    for i, msg in enumerate(messages):
        if i in protected:
            continue
        if (
            msg.role == Role.tool
            and msg.name in CLEARABLE_TOOLS
            and msg.content
            and _CLEARED_MARKER not in msg.content
        ):
            candidates.append((i, len(msg.content) // 4))

    # Greedy: largest savings first, ties broken oldest-first (lower index)
    candidates.sort(key=lambda x: (-x[1], x[0]))

    tokens_reclaimed = 0
    cleared_count = 0
    # `silent()` is defensive: today MessageList._observer only fires on
    # `append()`, so direct attribute mutation below does NOT trigger it.
    # Keeping the wrapper so future refactors that go through append-based
    # replacement won't accidentally re-notify and confuse rewind/TUI state.
    with messages.silent():
        for i, token_est in candidates:
            if tokens_reclaimed >= tokens_to_save:
                break
            messages[i].content = f"{_CLEARED_MARKER} — {token_est} tokens reclaimed]"
            tokens_reclaimed += token_est
            cleared_count += 1

    if cleared_count > 0:
        stats.cleared_tool_results += cleared_count
        # Ephemeral mutation: the next LLM response handler overwrites
        # context_tokens from LLMUsage.input_tokens. We set it here so
        # AutoCompactMiddleware (which runs right after us in the same turn)
        # observes the post-clearance count and skips full compact.
        stats.context_tokens = max(0, stats.context_tokens - tokens_reclaimed)

    return tokens_reclaimed


class MicroCompactMiddleware:
    async def before_turn(self, context: ConversationContext) -> MiddlewareResult:
        threshold = context.config.get_active_model().auto_compact_threshold
        if threshold <= 0:
            return MiddlewareResult()
        micro_compact(
            context.messages,
            threshold,
            context.config.micro_compact_ratio,
            context.config.micro_keep_last,
            context.stats,
        )
        return MiddlewareResult()

    def reset(self, reset_reason: ResetReason = ResetReason.STOP) -> None:
        pass
