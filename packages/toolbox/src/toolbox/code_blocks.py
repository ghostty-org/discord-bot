# Roughly based on extraction logic from zig-codeblocks:
# https://github.com/trag1c/zig-codeblocks/blob/main/src/parse.rs
import re
from typing import NamedTuple, override

_INLINE_CODE_PATTERN = re.compile(r"(?<!`)(``?)(?:[^`]|[^`].*?[^`])\1(?!`)")
_CODE_BLOCK_PATTERN = re.compile(
    r"(?s)```(?:([A-Za-z0-9\-_\+\.#]+)(?:\r?\n)+([^\r\n].*?)|(.*?))```"
)


class CodeBlock(NamedTuple):
    lang: str | None
    body: str

    @override
    def __str__(self) -> str:
        if self.lang is not None:
            return f"```{self.lang}\n{self.body}```"
        return f"```{self.body}```"


def extract_codeblocks(source: str) -> list[CodeBlock]:
    source = _INLINE_CODE_PATTERN.sub(lambda m: "" if "```" in m[0] else m[0], source)
    return [
        CodeBlock(m[1], m[2]) if m[1] is not None else CodeBlock(None, m[3])
        for m in _CODE_BLOCK_PATTERN.finditer(source)
    ]
