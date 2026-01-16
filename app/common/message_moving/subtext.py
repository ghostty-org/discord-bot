import datetime as dt
import re
from typing import TYPE_CHECKING, final

import discord as dc

from app.utils import GuildTextChannel, dynamic_timestamp

if TYPE_CHECKING:
    from .moved_message import MovedMessage
    from app.utils import MessageData

_REACTION_REGEX = re.compile(r"([^\s×]+) ×(\d+)", re.ASCII)  # noqa: RUF001


def _format_emoji(emoji: str | dc.PartialEmoji | dc.Emoji) -> str:
    if (
        isinstance(emoji, str)
        or (isinstance(emoji, dc.PartialEmoji) and emoji.is_unicode_emoji())
        or (isinstance(emoji, dc.Emoji) and emoji.is_usable())
    ):
        return str(emoji)
    return f"[{emoji.name}](<{emoji.url}>)"


@final
class Subtext:
    # NOTE: when changing the subtext's format in ways that are not backward-compatible,
    # don't forget to bump the cut-off time in app/components/message_filter.py!
    reactions: str
    timestamp: str
    author: str
    move_hint: str
    skipped: str
    poll_error: str

    def __init__(
        self,
        msg_data: MessageData,
        executor: dc.Member | None,
        poll: dc.Poll | None = None,
    ) -> None:
        self.msg_data = msg_data
        self._format_reactions()
        self._format_timestamp()
        self.author = f"Authored by {msg_data.author.mention}"
        assert isinstance(self.msg_data.channel, GuildTextChannel)
        self.move_hint = (
            f"Moved from {self.msg_data.channel.mention} by {executor.mention}"
            if executor is not None
            else ""
        )
        self.skipped = (
            self.format_skipped(skipped)
            if (skipped := msg_data.skipped_attachments)
            else ""
        )
        self.poll_error = (
            "Unable to attach closed poll" if poll is dc.utils.MISSING else ""
        )

    def _format_reactions(self) -> None:
        self.reactions = "   ".join(
            f"{_format_emoji(reaction.emoji)} ×{reaction.count}"  # noqa: RUF001
            for reaction in self.msg_data.reactions
        )

    def _format_timestamp(self) -> None:
        if self.msg_data.created_at > dt.datetime.now(tz=dt.UTC) - dt.timedelta(
            hours=12
        ):
            self.timestamp = ""
            return
        self.timestamp = dynamic_timestamp(self.msg_data.created_at)
        if self.msg_data.edited_at is not None:
            self.timestamp += (
                f" (edited at {dynamic_timestamp(self.msg_data.edited_at, 't')})"
            )

    @staticmethod
    def format_skipped(skipped: int) -> str:
        return f"Skipped {skipped} large attachment{'s' * (skipped != 1)}"

    def format(self) -> str:
        original_message_info = (
            self.author,
            " on " if self.author and self.timestamp else "",
            self.timestamp,
        )
        context = (
            "".join(original_message_info),
            self.skipped,
            self.poll_error,
            self.move_hint,
        )
        return self._sub_join(self.reactions, " • ".join(filter(None, context)))

    def format_simple(self) -> str:
        return self._sub_join(self.reactions, self.skipped, self.poll_error)

    @staticmethod
    def _sub_join(*strs: str) -> str:
        return "\n".join(f"-# {s}" for s in strs if s)


@final
class SplitSubtext:
    def __init__(self, message: MovedMessage) -> None:
        # Since we know that we definitely have a moved message here (due to the
        # restriction on `message`'s type), the last line must be the subtext.
        *lines, self._subtext = message.content.splitlines()
        if not lines:
            self.content, self.reactions = "", {}
            return
        self.reactions = self._get_reactions(lines[-1])
        if self.reactions:
            lines.pop()
        self.content = "\n".join(lines)

    @staticmethod
    def _get_reactions(reaction_line: str) -> dict[str, int]:
        if not reaction_line.startswith("-# "):
            return {}
        d: dict[str, int] = {}
        for s in reaction_line.removeprefix("-# ").split("   "):
            if not (match := _REACTION_REGEX.fullmatch(s)):
                # If any of the reactions don't match, we don't have an actual reaction
                # line; return an empty dictionary to ignore that line as it may just be
                # a similarly-formatted line present in the actual message content
                # itself.
                return {}
            emoji, count = match.groups()
            d[emoji] = int(count)
        return d

    def update(self, message: dc.Message, executor: dc.Member | None) -> None:
        if executor:
            assert isinstance(message.channel, GuildTextChannel)
            self._subtext += (
                f", then from {message.channel.mention} by {executor.mention}"
            )
        for reaction in message.reactions:
            emoji = _format_emoji(reaction.emoji)
            self.reactions.setdefault(emoji, 0)
            self.reactions[emoji] += reaction.count

    @property
    def subtext(self) -> str:
        if not self.reactions:
            return self._subtext
        formatted_reactions = "   ".join(
            f"{emoji} ×{count}"  # noqa: RUF001
            for emoji, count in self.reactions.items()
        )
        return f"-# {formatted_reactions}\n{self._subtext}"
