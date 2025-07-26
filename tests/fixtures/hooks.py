from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

from app.common.hooks import (
    ItemActions,
    MessageLinker,
    ProcessedMessage,
    create_delete_hook,
    create_edit_hook,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import discord as dc

    type DeleteHook = Callable[[dc.Message], Awaitable[None]]

NUM_PAT = re.compile(r"\b\d+\b")

linker = pytest.fixture(lambda: MessageLinker())


@pytest.fixture
def delete_hook(linker: MessageLinker) -> DeleteHook:
    return create_delete_hook(linker=linker)


async def extract_numbers_then_hex(msg: dc.Message) -> ProcessedMessage:
    matches = NUM_PAT.findall(msg.content)
    nums = " ".join(map(hex, map(int, matches)))
    return ProcessedMessage(item_count=len(matches), content=nums)


async def print_hex_nums(msg: dc.Message) -> None:
    print((await extract_numbers_then_hex(msg)).content)


class TrackedCallable[**P, R]:
    def __init__(self, callable_: Callable[P, R]) -> None:
        self._callable = callable_
        self.calls = 0

    @property
    def called(self) -> bool:
        return self.calls > 0

    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R:
        self.calls += 1
        return self._callable(*args, **kwargs)


class EditHook:
    def __init__(self, linker: MessageLinker) -> None:
        self.message_processor = TrackedCallable(extract_numbers_then_hex)
        self.interactor = TrackedCallable(print_hex_nums)
        self._hook = create_edit_hook(
            linker=linker,
            message_processor=self.message_processor,
            interactor=self.interactor,
            view_type=ItemActions,
            view_timeout=0,
        )

    async def __call__(self, before: dc.Message, after: dc.Message) -> None:
        return await self._hook(before, after)


@pytest.fixture
def edit_hook(linker: MessageLinker) -> EditHook:
    return EditHook(linker=linker)
