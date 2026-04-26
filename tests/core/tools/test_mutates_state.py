from __future__ import annotations

from typing import ClassVar

import pytest

from vibe.core.tools.base import BaseTool, BaseToolConfig, BaseToolState


class TestBaseToolMutatesStateDefault:
    def test_base_tool_defaults_to_true(self) -> None:
        assert BaseTool.mutates_state is True

    def test_subclass_inherits_default_true(self) -> None:
        from pydantic import BaseModel

        class _Args(BaseModel):
            pass

        class _Result(BaseModel):
            ok: bool = True

        class FakeWriter(BaseTool[_Args, _Result, BaseToolConfig, BaseToolState]):
            description: ClassVar[str] = "fake"

            async def run(self, args, ctx=None):  # type: ignore[no-untyped-def]
                yield _Result()

        assert FakeWriter.mutates_state is True

    def test_subclass_can_override_to_false(self) -> None:
        from pydantic import BaseModel

        class _Args(BaseModel):
            pass

        class _Result(BaseModel):
            ok: bool = True

        class FakeReader(BaseTool[_Args, _Result, BaseToolConfig, BaseToolState]):
            description: ClassVar[str] = "fake"
            mutates_state: ClassVar[bool] = False

            async def run(self, args, ctx=None):  # type: ignore[no-untyped-def]
                yield _Result()

        assert FakeReader.mutates_state is False
