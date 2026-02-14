import asyncio
import re
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterable

__all__ = (
    "URL_REGEX",
    "aenumerate",
    "async_process_check_output",
    "format_diff_note",
    "truncate",
)

URL_REGEX = re.compile(
    r"https?:\/\/(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b"
    r"(?:[-a-zA-Z0-9()@:%_\+.~#?&//=]*)"
)


def truncate(s: str, length: int, *, suffix: str = "…") -> str:
    if len(s) <= length:
        return s
    return s[: length - len(suffix)] + suffix


async def aenumerate[T](
    it: AsyncIterable[T], start: int = 0
) -> AsyncGenerator[tuple[int, T]]:
    i = start
    async for x in it:
        yield i, x
        i += 1


def format_diff_note(additions: int, deletions: int, changed_files: int) -> str | None:
    if not (changed_files and (additions or deletions)):
        return None  # Diff size unavailable
    return f"diff size: `+{additions}` `-{deletions}` ({changed_files} files changed)"


async def async_process_check_output(program: str, *args: str, **kwargs: Any) -> str:
    if "stdout" in kwargs:
        msg = "stdout argument not allowed, it will be overridden."
        raise ValueError(msg)
    proc = await asyncio.create_subprocess_exec(
        program, *args, stdout=subprocess.PIPE, **kwargs
    )
    assert proc.stdout is not None  # set to PIPE above
    if rc := await proc.wait():
        raise subprocess.CalledProcessError(
            returncode=rc,
            cmd=[program, *args],
            output=await proc.stdout.read(),
            stderr=proc.stderr and await proc.stderr.read(),
        )
    return (await proc.stdout.read()).decode()
