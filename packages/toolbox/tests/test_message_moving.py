# ruff: noqa: RUF001, RUF003 (because of `×`)
# pyright: reportPrivateUsage=false

import datetime as dt
from unittest.mock import Mock

import discord as dc
import pytest
from hypothesis import given
from hypothesis import strategies as st

from toolbox.message_moving import (
    MovedMessage,
    SplitSubtext,
    Subtext,
    message_can_be_moved,
)
from toolbox.message_moving.conversion import _unattachable_embed, convert_nitro_emojis
from toolbox.message_moving.moved_message import _find_snowflake
from toolbox.message_moving.subtext import _format_emoji
from toolbox.messages import MessageData

CDN_EMOJI_LINK = "https://cdn.discordapp.com/emojis/"

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
    url = f"{CDN_EMOJI_LINK}{id_}.{file_ending}"
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
        is_usable=Mock(return_value=is_usable),  # test: allow-specless-mock
        __str__=Mock(return_value="<foo>"),  # test: allow-specless-mock
    )
    fake_emoji.configure_mock(name="foo", url="bar")
    assert _format_emoji(fake_emoji) == output


@pytest.mark.parametrize(("guild", "result"), [(object(), True), (None, False)])
def test_message_can_be_moved_message_guild(guild: object, result: bool) -> None:
    fake_message = Mock(dc.Message, guild=guild, type=dc.MessageType.default)
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
    fake_message = Mock(dc.Message, guild=object(), type=type_)
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
        ("``<@192849172497>``", "@", (192849172497, 2)),
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
            (
                "a\n-# Authored by <@665120188047556609> • "
                "Moved from <#1281624935558807678> by <@665120188047556609>"
            ),
            665120188047556609,
        ),
        (
            (
                "Scanned 1 open posts in <#1305317376346296321>.\n"
                "-# Authored by <@1323096214735945738> on <t:1744888255> • "
                "Moved from <#1324364626225266758> by <@665120188047556609>"
            ),
            1323096214735945738,
        ),
        (
            (
                "edit\n-# Authored by <@665120188047556609> on <t:1745489008> "
                "(edited at <t:1745927179:t>) • Moved from <#1281624935558807678> "
                "by <@665120188047556609>"
            ),
            665120188047556609,
        ),
        (
            (
                "-# (content attached)\n-# Authored by <@665120188047556609> • "
                "Moved from <#1281624935558807678> by <@665120188047556609>"
            ),
            665120188047556609,
        ),
        ("-# Authored by <@665120188047556609>", 665120188047556609),
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
        ("-# Moved by ``<@665120188047556609>``", 665120188047556609),
        ("-# Authored by ```<@665120188047556609>```", 665120188047556609),
    ],
)
def test_get_moved_message_author_id(content: str, result: int) -> None:
    fake_message = Mock(dc.WebhookMessage, content=content)
    assert MovedMessage(fake_message).original_author_id == result


@pytest.mark.parametrize(
    "content",
    [
        "a\n -# Moved from <#1281624935558807678> by <@665120188047556609>",
        (
            "Scanned 0 open posts in <#1305317376346296321>.\n-# <t:1744158570> • "
            "Moved from <#1324364626225266758> by <@665120188047556609>"
        ),
        (
            "-# (content attached)\n-# Moved from "
            "<#1281624935558807678> by <@665120188047556609>"
        ),
        "test",
        "",
        "-# meow",
        "-# Moved from <#1281624935558807678> by <@665120188047556609>",
        "Authored by <@665120188047556609>",
        "<@665120188047556609>",
        "-#<@665120188047556609>",
        "<@665120188047556609 go to <#1294988140645453834>",
        (
            "-# <@252206453878685697> what are you doing in <#1337443701403815999> "
            "👀\n-# it's not ||[redacted]|| is it...?"
        ),
    ],
)
def test_get_moved_message_no_author_id(content: str) -> None:
    with pytest.raises(ValueError, match="not a moved message"):
        MovedMessage(Mock(dc.WebhookMessage, content=content))


@given(st.integers(min_value=0))
def test_moved_message_author_assert_pass(author_id: int) -> None:
    fake_message = Mock(dc.WebhookMessage, content=f"-# <@{author_id}>")
    MovedMessage(fake_message, author=Mock(dc.Member, id=author_id))


@st.composite
def differing_ids(draw: st.DrawFn) -> tuple[int, int]:
    n = draw(st.integers(min_value=0))
    return n, draw(st.integers(min_value=0).filter(lambda x: x != n))


@given(differing_ids())
def test_moved_message_author_assert_fail(ids: tuple[int, int]) -> None:
    subtext_id, author_id = ids
    fake_message = Mock(dc.WebhookMessage, content=f"-# <@{subtext_id}>")
    with pytest.raises(ValueError, match="incorrect author passed"):
        MovedMessage(fake_message, author=Mock(dc.Member, id=author_id))


@pytest.mark.parametrize(
    ("content", "emoji_id", "emoji_guild_id", "force", "expected"),
    [
        (
            "<:foo:12345>",
            12345,
            999,
            False,
            f"[foo](<{CDN_EMOJI_LINK}12345.webp?size=48&name=foo>)",
        ),
        (
            "<a:bar:67890>",
            67890,
            999,
            False,
            f"[bar](<{CDN_EMOJI_LINK}67890.gif?size=48&animated=true&name=bar>)",
        ),
        ("<:same_guild:11111>", 11111, 111, False, "<:same_guild:11111>"),
        (
            "<:same_guild:11111>",
            11111,
            111,
            True,
            f"[same_guild](<{CDN_EMOJI_LINK}11111.webp?size=48&name=same_guild>)",
        ),
        (
            "<:unknown:22222>",
            22222,
            None,
            False,
            f"[unknown](<{CDN_EMOJI_LINK}22222.webp?size=48&name=unknown>)",
        ),
        (
            "hi <:foo:12345>",
            12345,
            999,
            False,
            f"hi [foo](<{CDN_EMOJI_LINK}12345.webp?size=48&name=foo>)",
        ),
        (
            "<:a:1> <:b:2> <:c:3>",
            1,
            999,
            False,
            (
                f"[a](<{CDN_EMOJI_LINK}1.webp?size=48&name=a>) "
                f"[b](<{CDN_EMOJI_LINK}2.webp?size=48&name=b>) "
                f"[c](<{CDN_EMOJI_LINK}3.webp?size=48&name=c>)"
            ),
        ),
        ("no emojis here", None, None, False, "no emojis here"),
        ("", None, None, False, ""),
    ],
)
def test_convert_nitro_emojis(
    content: str,
    emoji_id: int | None,
    emoji_guild_id: int | None,
    force: bool,
    expected: str,
) -> None:
    fake_guild = Mock(dc.Guild, id=111)
    fake_client = Mock(dc.Client)
    fake_client.get_emoji.return_value = (
        Mock(dc.Emoji, guild_id=emoji_guild_id) if emoji_id is not None else None
    )

    result = convert_nitro_emojis(fake_client, fake_guild, content, force=force)
    assert result == expected


@pytest.mark.parametrize(
    ("strs", "expected"),
    [
        ((), ""),
        (("hello",), "-# hello"),
        (("hello", "world"), "-# hello\n-# world"),
        (("a", "b", "c"), "-# a\n-# b\n-# c"),
        (("", "hello", ""), "-# hello"),
        (("hello", "", "world"), "-# hello\n-# world"),
    ],
)
def test_subtext_sub_join(strs: tuple[str, ...], expected: str) -> None:
    assert Subtext._sub_join(*strs) == expected


@given(st.lists(st.text(max_size=30), max_size=30).map(tuple))
def test_subtext_sub_join_lines_retained(strs: tuple[str, ...]) -> None:
    joined = Subtext._sub_join(*strs)
    assert all(s in joined for s in strs)


@pytest.mark.parametrize(
    ("reaction_line", "expected"),
    [
        ("-# 👍 ×5", {"👍": 5}),
        ("-# 👍 ×5   👎 ×3", {"👍": 5, "👎": 3}),
        ("-# 🎉 ×10   🚀 ×2   💯 ×1", {"🎉": 10, "🚀": 2, "💯": 1}),
        ("-# [foo](<https://example.com>) ×42", {"[foo](<https://example.com>)": 42}),
        ("-# 👍 ×5   👎", {}),
        ("-# 👍 ×5   invalid", {}),
        ("-# not a reaction line", {}),
        ("👍 ×5", {}),
        ("-#👍 ×5", {}),
        ("", {}),
        ("-# ", {}),
        ("-# 👍×5", {}),
        ("-# 👍 x5", {}),
    ],
)
def test_split_subtext_get_reactions(
    reaction_line: str, expected: dict[str, int]
) -> None:
    assert SplitSubtext._get_reactions(reaction_line) == expected


@pytest.mark.parametrize(
    ("lines", "expected_content", "expected_reactions"),
    [
        (["-# subtext only"], "", {}),
        (["hello world", "-# subtext"], "hello world", {}),
        (["hello world", "-# 👍 ×5", "-# subtext"], "hello world", {"👍": 5}),
        (
            ["line1", "line2", "-# 👍 ×5   👎 ×3", "-# subtext"],
            "line1\nline2",
            {"👍": 5, "👎": 3},
        ),
        (
            ["hello", "-# invalid reaction", "-# subtext"],
            "hello\n-# invalid reaction",
            {},
        ),
        (["hello", "-# 👍×5", "-# subtext"], "hello\n-# 👍×5", {}),
        (["-# 👍 ×5", "-# subtext"], "", {"👍": 5}),
    ],
)
def test_split_subtext_init(
    lines: list[str], expected_content: str, expected_reactions: dict[str, int]
) -> None:
    fake_message = Mock(MovedMessage, content="\n".join(lines))
    split = SplitSubtext(fake_message)
    assert split.content == expected_content
    assert split.reactions == expected_reactions


@pytest.mark.parametrize(
    ("reactions", "expected_subtext"),
    [
        ({}, "-# subtext line"),
        ({"👍": 5, "👎": 3}, "-# 👍 ×5   👎 ×3\n-# subtext line"),
    ],
)
def test_split_subtext_subtext_property(
    reactions: dict[str, int], expected_subtext: str
) -> None:
    fake_message = Mock(MovedMessage, content="-# subtext line")
    split = SplitSubtext(fake_message)
    split.reactions = reactions
    assert split.subtext == expected_subtext


def _reaction(emoji: str, count: int) -> dc.Reaction:
    return Mock(dc.Reaction, emoji=emoji, count=count)


def test_split_subtext_update() -> None:
    fake_message = Mock(MovedMessage, content="content\n-# subtext")
    split = SplitSubtext(fake_message)
    split.reactions = {"👍": 5}

    fake_channel = Mock(dc.TextChannel, id=123456, mention="<#123456>")
    fake_executor = Mock(dc.Member, mention="<@789>")
    new_message = Mock(
        dc.Message,
        channel=fake_channel,
        reactions=[_reaction("👍", 3), _reaction("👎", 2)],
    )

    split.update(new_message, fake_executor)

    assert split.reactions == {"👍": 8, "👎": 2}
    assert ", then from <#123456> by <@789>" in split._subtext


def test_split_subtext_update_no_executor() -> None:
    fake_message = Mock(MovedMessage, content="content\n-# subtext")
    split = SplitSubtext(fake_message)
    split.reactions = {"👍": 5}
    original_subtext = split._subtext

    new_message = Mock(dc.Message, reactions=[_reaction("👎", 2)])

    split.update(new_message, None)

    assert split.reactions == {"👍": 5, "👎": 2}
    assert split._subtext == original_subtext


def _make_message_data(  # noqa: PLR0917
    author: dc.User | None = None,
    channel: dc.TextChannel | None = None,
    reactions: list[dc.Reaction] | None = None,
    created_at: dt.datetime | None = None,
    edited_at: dt.datetime | None = None,
    skipped_attachments: int = 0,
) -> MessageData:
    return Mock(
        MessageData,
        author=author or Mock(dc.User, mention="<@123>"),
        channel=channel or Mock(dc.TextChannel, mention="<#456>"),
        reactions=reactions or [],
        created_at=created_at or dt.datetime.now(tz=dt.UTC),
        edited_at=edited_at,
        skipped_attachments=skipped_attachments,
    )


@pytest.mark.parametrize(
    ("reactions", "expected"),
    [
        ([], ""),
        ([_reaction("👍", 5)], "👍 ×5"),
        ([_reaction("👍", 5), _reaction("👎", 3)], "👍 ×5   👎 ×3"),
        (
            [_reaction("🎉", 10), _reaction("🚀", 2), _reaction("💯", 1)],
            "🎉 ×10   🚀 ×2   💯 ×1",
        ),
    ],
)
def test_subtext_format_reactions(reactions: list[dc.Reaction], expected: str) -> None:
    subtext = object.__new__(Subtext)
    subtext.msg_data = _make_message_data(reactions=reactions)
    subtext._format_reactions()

    assert subtext.reactions == expected


@pytest.mark.parametrize(
    ("executor", "expected_move_hint"),
    [(Mock(dc.Member, mention="<@123>"), "Moved from <#456> by <@123>"), (None, "")],
)
def test_subtext_init_move_hint(
    executor: dc.Member | None, expected_move_hint: str
) -> None:
    fake_author = Mock(dc.User, mention="<@789>")
    msg_data = _make_message_data(author=fake_author)

    subtext = Subtext(msg_data, executor)

    assert subtext.move_hint == expected_move_hint
    assert subtext.author == "Authored by <@789>"


@pytest.mark.parametrize(
    ("skipped_attachments", "expected_skipped"),
    [
        (0, ""),
        (1, "Skipped 1 large attachment"),
        (3, "Skipped 3 large attachments"),
    ],
)
def test_subtext_init_skipped(skipped_attachments: int, expected_skipped: str) -> None:
    msg_data = _make_message_data(skipped_attachments=skipped_attachments)
    subtext = Subtext(msg_data, None)
    assert subtext.skipped == expected_skipped


@pytest.mark.parametrize(
    ("poll", "expected_poll_error"),
    [
        (None, ""),
        (Mock(dc.Poll), ""),
        (dc.utils.MISSING, "Unable to attach closed poll"),
    ],
)
def test_subtext_init_poll_error(
    poll: dc.Poll | None, expected_poll_error: str
) -> None:
    msg_data = _make_message_data()
    subtext = Subtext(msg_data, None, poll=poll)
    assert subtext.poll_error == expected_poll_error


@pytest.mark.parametrize(
    ("delta", "expected_timestamp_empty"),
    [
        (dt.timedelta(), True),
        (dt.timedelta(hours=1), True),
        (dt.timedelta(hours=11), True),
        (dt.timedelta(hours=13), False),
        (dt.timedelta(days=1), False),
    ],
)
def test_subtext_init_timestamp(
    delta: dt.timedelta,
    expected_timestamp_empty: bool,
) -> None:
    msg_data = _make_message_data(created_at=dt.datetime.now(tz=dt.UTC) - delta)
    subtext = Subtext(msg_data, None)
    assert (subtext.timestamp == "") is expected_timestamp_empty


def test_subtext_init_timestamp_with_edited() -> None:
    old_time = dt.datetime.now(tz=dt.UTC) - dt.timedelta(days=1)
    edited_time = dt.datetime.now(tz=dt.UTC) - dt.timedelta(hours=6)
    msg_data = _make_message_data(created_at=old_time, edited_at=edited_time)

    subtext = Subtext(msg_data, None)

    assert "<t:" in subtext.timestamp
    assert "edited at <t:" in subtext.timestamp


@pytest.mark.parametrize(
    (
        "reactions",
        "author",
        "timestamp",
        "skipped",
        "poll_error",
        "move_hint",
        "expected",
    ),
    [
        ([], "", "", "", "", "", ""),
        (["👍"], "Authored by <@1>", "", "", "", "", "-# 👍\n-# Authored by <@1>"),
        (
            [],
            "Authored by <@1>",
            "<t:123>",
            "",
            "",
            "",
            "-# Authored by <@1> on <t:123>",
        ),
        (
            [],
            "Authored by <@1>",
            "",
            "Skipped 1",
            "",
            "",
            "-# Authored by <@1> • Skipped 1",
        ),
        (
            [],
            "",
            "",
            "",
            "Unable to attach closed poll",
            "",
            "-# Unable to attach closed poll",
        ),
        ([], "", "", "", "", "Moved from <#1> by <@2>", "-# Moved from <#1> by <@2>"),
        (
            ["👍"],
            "Authored by <@1>",
            "<t:123>",
            "Skipped 1",
            "Unable to attach closed poll",
            "Moved from <#1> by <@2>",
            (
                "-# 👍\n-# Authored by <@1> on <t:123> • Skipped 1 • Unable to attach "
                "closed poll • Moved from <#1> by <@2>"
            ),
        ),
        (
            [],
            "Authored by <@1>",
            "<t:123>",
            "",
            "",
            "Moved from <#1> by <@2>",
            "-# Authored by <@1> on <t:123> • Moved from <#1> by <@2>",
        ),
    ],
)
def test_subtext_format(  # noqa: PLR0917
    reactions: list[str],
    author: str,
    timestamp: str,
    skipped: str,
    poll_error: str,
    move_hint: str,
    expected: str,
) -> None:
    subtext = object.__new__(Subtext)
    subtext.reactions = "   ".join(reactions)
    subtext.author = author
    subtext.timestamp = timestamp
    subtext.skipped = skipped
    subtext.poll_error = poll_error
    subtext.move_hint = move_hint

    assert subtext.format() == expected


@pytest.mark.parametrize(
    ("reactions", "skipped", "poll_error", "expected"),
    [
        ("", "", "", ""),
        ("👍 ×5", "", "", "-# 👍 ×5"),
        ("", "Skipped 1 large attachment", "", "-# Skipped 1 large attachment"),
        ("", "", "Unable to attach closed poll", "-# Unable to attach closed poll"),
        (
            "👍 ×5",
            "Skipped 1 large attachment",
            "Unable to attach closed poll",
            "-# 👍 ×5\n-# Skipped 1 large attachment\n-# Unable to attach closed poll",
        ),
    ],
)
def test_subtext_format_simple(
    reactions: str, skipped: str, poll_error: str, expected: str
) -> None:
    subtext = object.__new__(Subtext)
    subtext.reactions = reactions
    subtext.skipped = skipped
    subtext.poll_error = poll_error

    assert subtext.format_simple() == expected
