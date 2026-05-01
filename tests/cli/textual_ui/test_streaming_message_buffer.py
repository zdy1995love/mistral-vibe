from __future__ import annotations

import pytest

from vibe.cli.textual_ui.widgets.messages import StreamingMessageBase


class FakeStream:
    def __init__(self) -> None:
        self.written: list[str] = []
        self.stopped = False

    async def write(self, content: str) -> None:
        self.written.append(content)

    async def stop(self) -> None:
        self.stopped = True

    @property
    def all_written(self) -> str:
        return "".join(self.written)


class MessageTestDouble(StreamingMessageBase):
    """Minimal test double for StreamingMessageBase that bypasses Textual internals."""

    # Disable the streaming throttle for unit-level tests — they assert
    # the underlying direct-write/buffer semantics, not the timing
    # coalescing applied at the live UI layer.
    _flush_interval_s = 0.0

    def __init__(self, at_bottom: bool = True, should_write: bool = True) -> None:
        # Initialise only the fields used by the buffer logic — no Textual setup.
        self._content = ""
        self._content_initialized = False
        self._to_write_buffer = ""
        self._last_flush_monotonic = 0.0
        self._stream = None
        self._markdown = None
        self._at_bottom = at_bottom
        self._should_write = should_write
        self._fake_stream: FakeStream = FakeStream()

    # --- overrides used by the buffer logic ---

    def _ensure_stream(self) -> FakeStream:  # type: ignore[override]
        if self._stream is None:
            self._stream = self._fake_stream  # type: ignore[assignment]
        return self._fake_stream

    def _is_chat_at_bottom(self) -> bool:
        return self._at_bottom

    def _should_write_content(self) -> bool:
        return self._should_write


def make_msg(*, at_bottom: bool = True, should_write: bool = True) -> MessageTestDouble:
    return MessageTestDouble(at_bottom=at_bottom, should_write=should_write)


class TestAppendContent:
    @pytest.mark.asyncio
    async def test_at_bottom_writes_directly_no_buffer(self) -> None:
        msg = make_msg(at_bottom=True)

        await msg.append_content("hello")

        assert msg._fake_stream.all_written == "hello"
        assert msg._to_write_buffer == ""

    @pytest.mark.asyncio
    async def test_scrolled_away_buffers_without_writing(self) -> None:
        msg = make_msg(at_bottom=False)

        await msg.append_content("hello")

        assert msg._fake_stream.all_written == ""
        assert msg._to_write_buffer == "hello"

    @pytest.mark.asyncio
    async def test_multiple_chunks_scrolled_away_accumulate(self) -> None:
        msg = make_msg(at_bottom=False)

        await msg.append_content("foo")
        await msg.append_content(" bar")

        assert msg._fake_stream.all_written == ""
        assert msg._to_write_buffer == "foo bar"

    @pytest.mark.asyncio
    async def test_scroll_back_flushes_buffer_with_new_chunk(self) -> None:
        msg = make_msg(at_bottom=False)
        await msg.append_content("buffered")

        msg._at_bottom = True
        await msg.append_content(" new")

        # Both buffered and new chunk written together in one write call.
        assert msg._fake_stream.all_written == "buffered new"
        assert msg._to_write_buffer == ""

    @pytest.mark.asyncio
    async def test_scroll_back_subsequent_chunks_written_directly(self) -> None:
        msg = make_msg(at_bottom=False)
        await msg.append_content("a")
        await msg.append_content("b")

        msg._at_bottom = True
        await msg.append_content("c")
        await msg.append_content("d")

        assert msg._fake_stream.all_written == "abc" + "d"
        assert msg._to_write_buffer == ""

    @pytest.mark.asyncio
    async def test_empty_content_is_ignored(self) -> None:
        msg = make_msg()

        await msg.append_content("")

        assert msg._fake_stream.all_written == ""
        assert msg._to_write_buffer == ""

    @pytest.mark.asyncio
    async def test_should_write_false_skips_stream_and_buffer(self) -> None:
        msg = make_msg(should_write=False)

        await msg.append_content("invisible")

        assert msg._fake_stream.all_written == ""
        assert msg._to_write_buffer == ""
        # Content still accumulates in _content for later full-replay.
        assert msg._content == "invisible"


class TestStopStream:
    @pytest.mark.asyncio
    async def test_flushes_remaining_buffer(self) -> None:
        msg = make_msg(at_bottom=False)
        await msg.append_content("pending")

        await msg.stop_stream()

        assert msg._fake_stream.all_written == "pending"
        assert msg._to_write_buffer == ""

    @pytest.mark.asyncio
    async def test_stops_the_stream(self) -> None:
        msg = make_msg(at_bottom=False)
        await msg.append_content("x")
        await msg.stop_stream()

        assert msg._fake_stream.stopped is True

    @pytest.mark.asyncio
    async def test_idempotent_no_double_write(self) -> None:
        msg = make_msg(at_bottom=False)
        await msg.append_content("once")

        await msg.stop_stream()
        await msg.stop_stream()

        assert msg._fake_stream.all_written == "once"

    @pytest.mark.asyncio
    async def test_does_not_write_when_should_write_false(self) -> None:
        msg = make_msg(at_bottom=True, should_write=False)
        # Manually poke the buffer to verify the guard is respected.
        msg._to_write_buffer = "invisible"

        await msg.stop_stream()

        assert msg._fake_stream.all_written == ""
        assert msg._to_write_buffer == ""

    @pytest.mark.asyncio
    async def test_empty_buffer_no_extra_write(self) -> None:
        msg = make_msg()
        await msg.append_content("live")  # written directly, buffer stays empty

        await msg.stop_stream()

        # Only the original direct write, no spurious extra write from stop_stream.
        assert msg._fake_stream.written == ["live"]


class TestWriteInitialContent:
    @pytest.mark.asyncio
    async def test_writes_accumulated_content(self) -> None:
        msg = make_msg()
        msg._content = "full content"

        await msg.write_initial_content()

        assert msg._fake_stream.all_written == "full content"

    @pytest.mark.asyncio
    async def test_is_idempotent_second_call_writes_nothing(self) -> None:
        msg = make_msg()
        msg._content = "content"

        await msg.write_initial_content()
        await msg.write_initial_content()

        assert msg._fake_stream.all_written == "content"

    @pytest.mark.asyncio
    async def test_already_initialized_flag_is_noop(self) -> None:
        msg = make_msg()
        msg._content = "something"
        msg._content_initialized = True

        await msg.write_initial_content()

        assert msg._fake_stream.all_written == ""

    @pytest.mark.asyncio
    async def test_empty_content_writes_nothing(self) -> None:
        msg = make_msg()

        await msg.write_initial_content()

        assert msg._fake_stream.all_written == ""

    @pytest.mark.asyncio
    async def test_should_write_false_writes_nothing(self) -> None:
        msg = make_msg(should_write=False)
        msg._content = "hidden"

        await msg.write_initial_content()

        assert msg._fake_stream.all_written == ""

    @pytest.mark.asyncio
    async def test_clears_buffer_after_writing(self) -> None:
        msg = make_msg(at_bottom=False)
        await msg.append_content("buffered chunk")

        await msg.write_initial_content()

        assert msg._to_write_buffer == ""


class TestNoDoubleWrite:
    @pytest.mark.asyncio
    async def test_write_initial_then_stop_stream_no_duplication(self) -> None:
        """Regression: buffer must be cleared after write_initial_content so
        stop_stream does not re-write the same content.
        """
        msg = make_msg(at_bottom=False)
        await msg.append_content("part one ")
        await msg.append_content("part two")

        await msg.write_initial_content()
        await msg.stop_stream()

        written = msg._fake_stream.all_written
        assert written == "part one part two", (
            f"Expected content written exactly once, got: {written!r}"
        )

    @pytest.mark.asyncio
    async def test_write_initial_before_streaming_then_buffered_then_stop(self) -> None:
        """Reflects the real call order: write_initial_content is called once at
        mount time (stream is pristine, _content is empty), then streaming begins.
        Buffered content must be flushed exactly once by stop_stream.

        Note: calling write_initial_content AFTER live content has already been
        written to the stream is not a supported usage — it would duplicate the
        already-written portion because write_initial_content replays the full
        _content. In practice this never occurs because _mount_and_scroll calls
        write_initial_content immediately on mount, before streaming starts.
        """
        msg = make_msg(at_bottom=False)

        # At mount time content is empty — write_initial_content is a no-op
        # but arms _content_initialized so it can never write again.
        await msg.write_initial_content()

        await msg.append_content("buffered chunk one ")
        await msg.append_content("buffered chunk two")

        await msg.stop_stream()

        written = msg._fake_stream.all_written
        assert written == "buffered chunk one buffered chunk two", (
            f"Expected buffered content written exactly once, got: {written!r}"
        )

    @pytest.mark.asyncio
    async def test_write_initial_before_streaming_at_bottom_then_stop(self) -> None:
        """write_initial_content at mount (no-op), streaming at bottom writes
        directly, stop_stream has nothing extra to flush.
        """
        msg = make_msg(at_bottom=True)

        await msg.write_initial_content()

        await msg.append_content("live one ")
        await msg.append_content("live two")

        await msg.stop_stream()

        assert msg._fake_stream.all_written == "live one live two"

    @pytest.mark.asyncio
    async def test_stop_stream_twice_no_double_write(self) -> None:
        msg = make_msg(at_bottom=False)
        await msg.append_content("data")

        await msg.stop_stream()
        await msg.stop_stream()

        assert msg._fake_stream.all_written == "data"

    @pytest.mark.asyncio
    async def test_write_initial_twice_no_double_write(self) -> None:
        msg = make_msg()
        msg._content = "once"

        await msg.write_initial_content()
        await msg.write_initial_content()

        assert msg._fake_stream.all_written == "once"


class TestFlushThrottle:
    """The Markdown.append re-parse cost in Textual 8.x grows with the
    response length, so streaming chunks at sub-frame intervals must be
    coalesced into a single flush. The throttle is gated by a class-level
    `_flush_interval_s`; setting it >0 in a subclass enables coalescing.
    """

    @pytest.mark.asyncio
    async def test_throttle_buffers_burst_until_interval_passes(self) -> None:
        # Drive the throttle deterministically: fixed wall clock = 100s, so
        # neither chunk crosses the 50ms threshold.
        import vibe.cli.textual_ui.widgets.messages as messages_mod

        msg = make_msg(at_bottom=True)
        msg._flush_interval_s = 0.05  # 50ms throttle window
        msg._last_flush_monotonic = 100.0

        original_monotonic = messages_mod.time.monotonic
        messages_mod.time.monotonic = lambda: 100.0  # type: ignore[assignment]
        try:
            await msg.append_content("a")
            await msg.append_content("b")
            await msg.append_content("c")
        finally:
            messages_mod.time.monotonic = original_monotonic

        # All three writes elapsed under the throttle window — buffer holds
        # everything, fake stream got no writes yet.
        assert msg._fake_stream.all_written == ""
        assert msg._to_write_buffer == "abc"

        # stop_stream must always flush the residual.
        await msg.stop_stream()
        assert msg._fake_stream.all_written == "abc"

    @pytest.mark.asyncio
    async def test_throttle_flushes_when_interval_elapsed(self) -> None:
        import vibe.cli.textual_ui.widgets.messages as messages_mod

        msg = make_msg(at_bottom=True)
        msg._flush_interval_s = 0.05

        # First append at t=100, second at t=100.2 (200ms > 50ms) — second
        # call must flush both buffered content and the new chunk.
        clock = {"t": 100.0}
        original_monotonic = messages_mod.time.monotonic
        messages_mod.time.monotonic = lambda: clock["t"]  # type: ignore[assignment]
        try:
            await msg.append_content("first")
            clock["t"] = 100.2
            await msg.append_content("second")
        finally:
            messages_mod.time.monotonic = original_monotonic

        assert msg._fake_stream.all_written == "firstsecond"
        assert msg._to_write_buffer == ""
