import re
from typing import TYPE_CHECKING, final

import pytest

from app.common.linker import ItemActions, MessageLinker, ProcessedMessage

if TYPE_CHECKING:
    from collections.abc import Callable

    import discord as dc


NUM_PAT = re.compile(r"\b\d+\b")

linker = pytest.fixture(lambda: MessageLinker())


async def extract_numbers_then_hex(msg: dc.Message) -> ProcessedMessage:
    matches = NUM_PAT.findall(msg.content)
    nums = " ".join(map(hex, map(int, matches)))
    return ProcessedMessage(item_count=len(matches), content=nums)


async def print_hex_nums(msg: dc.Message) -> None:
    print((await extract_numbers_then_hex(msg)).content)  # noqa: T201


@final
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


@final
class EditHook:
    def __init__(self, linker: MessageLinker) -> None:
        self.linker = linker
        self.message_processor = TrackedCallable(extract_numbers_then_hex)
        self.interactor = TrackedCallable(print_hex_nums)

    async def __call__(self, before: dc.Message, after: dc.Message) -> None:
        return await self.linker.edit(
            before,
            after,
            message_processor=self.message_processor,
            interactor=self.interactor,
            view_type=ItemActions,
            view_timeout=0,
        )


@pytest.fixture
def edit_hook(linker: MessageLinker) -> EditHook:
    return EditHook(linker=linker)
