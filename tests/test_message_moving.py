from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from app.utils.webhooks import (
    _find_snowflake,  # pyright: ignore [reportPrivateUsage]
    get_moved_message_author_id,
)

if TYPE_CHECKING:
    import discord


@pytest.mark.parametrize(
    ("content", "type_", "result"),
    [
        ("<@1234123>", "@", (1234123, 0)),
        ("foo <@1234123>", "@", (1234123, 4)),
        ("foo <#1234123>", "@", (None, None)),
        ("foo <#1234123>", "#", (1234123, 4)),
        ("foo <*1234123>", "*", (1234123, 4)),
        ("lorem ipsum <*1234123>", "*", (1234123, 12)),
        ("lorem ipsum <*1234123 <#128381723>", "#", (128381723, 22)),
        ("lorem ipsum <#1234123 <#128381723>", "#", (128381723, 22)),
        ("join vc @ <#!12749128401294>!!", "#", (None, None)),
        ("join vc @ <#!12749128401294>", "#!", (12749128401294, 10)),
        ("join vc @ <#!12749128401294>", "", (None, None)),
        ("join vc @ <12749128401294> :D", "", (12749128401294, 10)),
        ("join vc @ <#!12749128401294>", "@", (None, None)),
        (
            f"the quick brown fox <@{'7294857392283743' * 16}> jumps over the lazy dog",
            "@",
            (int("7294857392283743" * 16), 20),
        ),
        ("<@<@1234869>", "@", (1234869, 2)),
        ("<@>", "@", (None, None)),
        ("<>", "", (None, None)),
        ("", "", (None, None)),
        ("hi", "", (None, None)),
        ("", "@", (None, None)),
        # *Technically* not a false positive, but Discord won't treat it as
        # special, so it's a false positive in the context that this function
        # is used in. This would have to be handled by the caller, and won't be
        # as this is deemed "too difficult" for a corner case that wouldn't
        # even materialize in practice because the subtext will never contain
        # code blocks with snowflakes contained within.
        ("`<@192849172497>`", "@", (192849172497, 1)),
        ("```<@192849172497>```", "@", (192849172497, 3)),
    ],
)
def test_find_snowflake(
    content: str, type_: str, result: tuple[int | None, int | None]
) -> None:
    assert _find_snowflake(content, type_) == result


@pytest.mark.parametrize(
    ("content", "result"),
    [
        (
            "a\n-# Authored by <@665120188047556609> • "
            "Moved from <#1281624935558807678> by <@665120188047556609>",
            665120188047556609,
        ),
        (
            "Scanned 1 open posts in <#1305317376346296321>.\n"
            "-# Authored by <@1323096214735945738> on <t:1744888255> • "
            "Moved from <#1324364626225266758> by <@665120188047556609>",
            1323096214735945738,
        ),
        (
            "edit\n-# Authored by <@665120188047556609> on <t:1745489008> "
            "(edited at <t:1745927179:t>) • Moved from <#1281624935558807678> "
            "by <@665120188047556609>",
            665120188047556609,
        ),
        ("a\n -# Moved from <#1281624935558807678> by <@665120188047556609>", None),
        (
            "Scanned 0 open posts in <#1305317376346296321>.\n-# <t:1744158570> • "
            "Moved from <#1324364626225266758> by <@665120188047556609>",
            None,
        ),
        (
            "-# (content attached)\n-# Authored by <@665120188047556609> • "
            "Moved from <#1281624935558807678> by <@665120188047556609>",
            665120188047556609,
        ),
        (
            "-# (content attached)\n-# Moved from "
            "<#1281624935558807678> by <@665120188047556609>",
            None,
        ),
        ("test", None),
        ("", None),
        ("-# Moved from <#1281624935558807678> by <@665120188047556609>", None),
        ("-# Authored by <@665120188047556609>", 665120188047556609),
        ("Authored by <@665120188047556609>", None),
        ("<@665120188047556609>", None),
        ("-#<@665120188047556609>", None),
        ("<@665120188047556609 go to <#1294988140645453834>", None),
        (
            "-# <@252206453878685697> what are you doing in <#1337443701403815999> 👀\n"
            "-# it's not ||[redacted]|| is it...?",
            None,
        ),
        # False positives that are not going to be handled.
        (
            "-# <@252206453878685697> what are you doing in <#1337443701403815999> 👀",
            252206453878685697,
        ),
        ("-# <@665120188047556609> look at this!", 665120188047556609),
        ("-# <@665120188047556609>", 665120188047556609),
        ("-# Oops <@665120188047556609>", 665120188047556609),
        ("-# Moved by <@665120188047556609>", 665120188047556609),
        # See the comment in test_find_snowflake().
        ("-# Moved by `<@665120188047556609>`", 665120188047556609),
        ("-# Authored by ```<@665120188047556609>```", 665120188047556609),
    ],
)
def test_get_moved_message_author_id(content: str, result: int | None) -> None:
    fake_message = cast("discord.WebhookMessage", SimpleNamespace(content=content))
    assert get_moved_message_author_id(fake_message) == result
