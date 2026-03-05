# pyright: reportPrivateUsage=false
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock

import discord as dc
import pytest
from hypothesis import given
from hypothesis import strategies as st

from toolbox.message_moving import MovedMessage, message_can_be_moved
from toolbox.message_moving.conversion import _unattachable_embed
from toolbox.message_moving.moved_message import _find_snowflake
from toolbox.message_moving.subtext import _format_emoji

# A random list of Unicode emojis that default to the emoji presentation.
UNICODE_EMOJIS = "📨🌼🎬⌛🧆🦯🤩👤🥈🏑🌊🤲👦🛝🍏🥫🐙👰🇫🤏🚋🏽🐾🌄🔛🐸🤣🐎💿👃🔘🍋🚈👘🚹"


@pytest.mark.parametrize("emoji", list(UNICODE_EMOJIS))
def test_format_unicode_emoji(emoji: str) -> None:
    assert _format_emoji(emoji) == emoji


@pytest.mark.parametrize("emoji", list(UNICODE_EMOJIS))
def test_format_unicode_partial_emoji(emoji: str) -> None:
    assert _format_emoji(dc.PartialEmoji(name=emoji)) == emoji


@pytest.mark.parametrize(
    ("name", "animated", "id_"),
    [
        ("apple_logo", False, 1322303418651508819),
        ("bobr~1", True, 1332673162160246784),
        ("bobr_explod", True, 1339003097493672016),
        ("del", False, 1296742294732673095),
        ("ete", False, 1296742293893681242),
        ("discussion_answered", False, 1326130753272025090),
        ("xd", False, 1317644781169672204),
        ("fooBaRb__az_loR_em", False, 1328977544984268890),
    ],
)
def test_format_partial_emoji(name: str, animated: bool, id_: int) -> None:
    file_ending = "webp?animated=true" if animated else "png"
    url = f"https://cdn.discordapp.com/emojis/{id_}.{file_ending}"
    assert (
        _format_emoji(dc.PartialEmoji(name=name, animated=animated, id=id_))
        == f"[{name}](<{url}>)"
    )


@pytest.mark.parametrize(
    ("is_usable", "output"), [(True, "<foo>"), (False, "[foo](<bar>)")]
)
def test_format_emoji_is_usable(is_usable: bool, output: str) -> None:
    fake_emoji = Mock(
        dc.Emoji,
        is_usable=Mock(return_value=is_usable),
        __str__=Mock(return_value="<foo>"),
    )
    fake_emoji.configure_mock(name="foo", url="bar")
    assert _format_emoji(fake_emoji) == output


@pytest.mark.parametrize(("guild", "result"), [(object(), True), (None, False)])
def test_message_can_be_moved_message_guild(guild: object, result: bool) -> None:
    fake_message = cast(
        "dc.Message", SimpleNamespace(guild=guild, type=dc.MessageType.default)
    )
    assert message_can_be_moved(fake_message) == result


@pytest.mark.parametrize(
    ("type_", "result"),
    [
        (dc.MessageType.default, True),
        (dc.MessageType.call, False),
        (dc.MessageType.pins_add, False),
        (dc.MessageType.reply, True),
        (dc.MessageType.new_member, False),
        (dc.MessageType.premium_guild_tier_1, False),
        (dc.MessageType.chat_input_command, True),
        (dc.MessageType.guild_discovery_grace_period_final_warning, False),
        (dc.MessageType.context_menu_command, True),
        (dc.MessageType.auto_moderation_action, False),
    ],
)
def test_message_can_be_moved_message_type(type_: dc.MessageType, result: bool) -> None:
    fake_message = cast("dc.Message", SimpleNamespace(guild=object(), type=type_))
    assert message_can_be_moved(fake_message) == result


@given(st.text())
def test_unattachable_embed(elem: str) -> None:
    # Require the (escaped) string to be in the returned embed. repr() on a string wraps
    # it in quotes, so remove those too.
    assert (
        repr(elem)[1:-1].casefold()
        in repr(_unattachable_embed(elem).to_dict()).casefold()
    )


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
        # *Technically* not a false positive, but Discord won't treat it as special, so
        # it's a false positive in the context that this function is used in. This would
        # have to be handled by the caller, and won't be as this is deemed "too
        # difficult" for a corner case that wouldn't even materialize in practice
        # because the subtext will never contain code blocks with snowflakes contained
        # within.
        ("`<@192849172497>`", "@", (192849172497, 1)),
        ("```<@192849172497>```", "@", (192849172497, 3)),
    ],
)
def test_find_snowflake(
    content: str, type_: str, result: tuple[int, int] | tuple[None, None]
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
    # NOTE: casting a SimpleNamespace to MovedMessage seems to break the code in
    # ExtensibleMessage, so we shall access _extract_author_id() directly.
    assert MovedMessage._extract_author_id(content) == result
