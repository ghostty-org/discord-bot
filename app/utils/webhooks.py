from io import BytesIO

import discord

from app.utils.message_data import MessageData, scrape_message_data

GuildTextChannel = discord.TextChannel | discord.Thread


def _format_subtext(executor: discord.Member | None, msg_data: MessageData) -> str:
    lines: list[str] = []
    if reactions := msg_data.reactions.items():
        lines.append("   ".join(f"{emoji} x{count}" for emoji, count in reactions))
    if executor:
        assert isinstance(msg_data.channel, GuildTextChannel)
        lines.append(f"Moved from {msg_data.channel.mention} by {executor.mention}")
    if skipped := msg_data.skipped_attachments:
        lines.append(f"(skipped {skipped} large attachment(s))")
    return "".join(f"\n-# {line}" for line in lines)


async def get_or_create_webhook(
    name: str, channel: discord.TextChannel | discord.ForumChannel
) -> discord.Webhook:
    webhooks = await channel.webhooks()
    for webhook in webhooks:
        if webhook.name == name:
            if webhook.token is None:
                await webhook.delete()
            else:
                return webhook

    return await channel.create_webhook(name=name)


async def move_message_via_webhook(
    webhook: discord.Webhook,
    message: discord.Message,
    executor: discord.Member | None = None,
    *,
    thread: discord.abc.Snowflake = discord.utils.MISSING,
    thread_name: str = discord.utils.MISSING,
) -> discord.WebhookMessage:
    msg_data = await scrape_message_data(message)

    subtext = _format_subtext(executor, msg_data)
    content, file = format_or_file(msg_data.content, template=f"{{}}{subtext}")
    if file:
        msg_data.attachments.append(file)
        content += "\n-# (content attached)"

    msg = await webhook.send(
        content=content,
        poll=(
            message.poll
            if message.poll is not None
            and message.poll.duration.total_seconds() / 3600 >= 1
            else discord.utils.MISSING
        ),
        username=message.author.display_name,
        avatar_url=message.author.display_avatar.url,
        allowed_mentions=discord.AllowedMentions.none(),
        files=msg_data.attachments,
        thread=thread,
        thread_name=thread_name,
        wait=True,
    )
    await message.delete()
    return msg


def format_or_file(
    message: str, *, template: str | None = None
) -> tuple[str, discord.File | None]:
    if template is None:
        template = "{}"

    if len(full_message := template.format(message)) > 2000:
        return template.format(""), discord.File(
            BytesIO(message.encode()), filename="content.md"
        )
    return full_message, None
