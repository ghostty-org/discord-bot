import asyncio
import re
import subprocess
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterable

    from githubkit.typing import Missing
    from githubkit.versions.latest.models import SimpleUser

__all__ = (
    "URL_REGEX",
    "aenumerate",
    "async_process_check_output",
    "format_diff_note",
    "truncate",
)

type EmbedColor = Literal["green", "red", "purple", "gray", "orange", "blue"]

COLOR_PALETTE: dict[EmbedColor, int] = {
    "green": 0x3FB950,
    "red": 0xF85149,
    "blue": 0x4C8CED,
    "purple": 0xAB7DF8,
    "gray": 0x9198A1,
    "orange": 0xEDB74A,
}

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


def format_event_sender(sender: Missing[SimpleUser]) -> str:
    return f"@{sender.login}" if sender else "?"
