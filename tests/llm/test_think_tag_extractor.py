from __future__ import annotations

from vibe.core.llm.backend.think_tag_extractor import ThinkTagExtractor


class TestNormalFraming:
    def test_paired_tags_extract_reasoning_and_content(self) -> None:
        ext = ThinkTagExtractor()
        r, c = ext.feed("[THINK]reasoning here[/THINK]visible reply")
        assert r == "reasoning here"
        assert c == "visible reply"
        rt, ct = ext.flush()
        assert rt == "" and ct == ""

    def test_no_tags_passes_content_through(self) -> None:
        ext = ThinkTagExtractor()
        r, c = ext.feed("just plain content")
        assert r == "" and c == "just plain content"

    def test_open_only_keeps_in_think_until_close_arrives(self) -> None:
        ext = ThinkTagExtractor()
        r, c = ext.feed("[THINK]partial reasoning")
        assert r == "partial reasoning" and c == ""
        r, c = ext.feed(" more reasoning[/THINK]done")
        assert r == " more reasoning" and c == "done"

    def test_split_across_chunks_at_open_tag(self) -> None:
        ext = ThinkTagExtractor()
        r, c = ext.feed("hello [THI")
        assert r == "" and c == "hello "  # buffer partial
        r, c = ext.feed("NK]reason[/THINK]done")
        assert r == "reason" and c == "done"

    def test_split_across_chunks_at_close_tag(self) -> None:
        ext = ThinkTagExtractor()
        r, c = ext.feed("[THINK]reasoning [/T")
        assert r == "reasoning " and c == ""  # partial close buffered
        r, c = ext.feed("HINK]final")
        assert r == "" and c == "final"


class TestOrphanCloseTag:
    """Mistral-style models occasionally emit [/THINK] without a preceding
    [THINK] (the open token gets consumed by vLLM as a special token while
    the close leaks as text). The extractor must silently swallow the
    orphan close so the visible content stays clean.
    """

    def test_orphan_close_in_middle_is_swallowed(self) -> None:
        ext = ThinkTagExtractor()
        r, c = ext.feed("visible reply [/THINK] more visible")
        assert r == ""
        assert c == "visible reply  more visible"

    def test_orphan_close_at_end_is_swallowed(self) -> None:
        ext = ThinkTagExtractor()
        r, c = ext.feed("answer text[/THINK]")
        assert r == ""
        assert c == "answer text"

    def test_orphan_close_followed_by_inline_tool_text(self) -> None:
        # Real-world case from the user's broken session.
        ext = ThinkTagExtractor()
        r, c = ext.feed('plan summary[/THINK]write_file{"path": "/tmp/x"}')
        assert r == ""
        assert c == 'plan summarywrite_file{"path": "/tmp/x"}'

    def test_orphan_close_then_proper_pair(self) -> None:
        ext = ThinkTagExtractor()
        r, c = ext.feed("hi[/THINK]then [THINK]r[/THINK]end")
        assert r == "r"
        assert c == "hithen end"

    def test_orphan_close_split_across_chunks(self) -> None:
        ext = ThinkTagExtractor()
        r, c = ext.feed("hello [/T")
        assert r == "" and c == "hello "
        r, c = ext.feed("HINK]world")
        assert r == "" and c == "world"

    def test_multiple_orphan_closes_all_stripped(self) -> None:
        ext = ThinkTagExtractor()
        r, c = ext.feed("a[/THINK]b[/THINK]c")
        assert r == ""
        assert c == "abc"


class TestFlush:
    def test_flush_emits_buffered_partial_in_think(self) -> None:
        ext = ThinkTagExtractor()
        ext.feed("[THINK]reason [/T")  # partial close buffered
        # If the stream truncates here without sending the rest of [/THINK],
        # flush must drain the buffered prefix as reasoning so callers
        # don't lose it.
        r, c = ext.flush()
        assert r == "[/T"
        assert c == ""

    def test_flush_emits_buffered_partial_outside_think(self) -> None:
        ext = ThinkTagExtractor()
        ext.feed("hello [TH")
        r, c = ext.flush()
        assert r == "" and c == "[TH"
