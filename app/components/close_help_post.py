from types import SimpleNamespace
from typing import Literal, cast

import discord
from discord import app_commands

from app.components.docs import get_docs_link
from app.components.entity_mentions import entity_message
from app.setup import bot, config
from app.utils import is_dm, is_helper, is_mod

# https://discord.com/developers/docs/topics/opcodes-and-status-codes#http-http-response-codes
INVALID_REQUEST_DATA = 400
# https://discord.com/developers/docs/topics/opcodes-and-status-codes#json
INVALID_FORM_BODY = 50035


async def mention_entity(entity_id: int, owner_id: int) -> str:
    msg, _ = await entity_message(
        # Forging a message to use the entity_mentions logic
        cast(
            discord.Message,
            SimpleNamespace(
                content=f"#{entity_id}",
                author=SimpleNamespace(id=owner_id),
            ),
        )
    )
    return msg


class Close(app_commands.Group):
    @app_commands.command(name="solved", description="Mark post as solved.")
    @app_commands.describe(config_option="Config option name (optional)")
    async def solved(
        self, interaction: discord.Interaction, config_option: str | None = None
    ) -> None:
        if config_option:
            try:
                additional_reply = get_docs_link("option", config_option)
            except ValueError:
                await interaction.response.send_message(
                    f"Invalid config option: `{config_option}`", ephemeral=True
                )
                return
            title_prefix = f"[SOLVED: {config_option}]"
        else:
            title_prefix = additional_reply = None
        await close_post(interaction, "solved", title_prefix, additional_reply)

    @app_commands.command(name="moved", description="Mark post as moved to GitHub.")
    @app_commands.describe(entity_id="New GitHub entity number")
    async def moved(self, interaction: discord.Interaction, entity_id: int) -> None:
        await close_post(
            interaction,
            "moved",
            title_prefix=f"[MOVED: #{entity_id}]",
            additional_reply=await mention_entity(entity_id, interaction.user.id),
        )

    @app_commands.command(name="duplicate", description="Mark post as duplicate.")
    @app_commands.describe(
        original="The original GitHub entity (number) or help post (ID or link)"
    )
    async def duplicate(self, interaction: discord.Interaction, original: str) -> None:
        *_, str_id = original.rpartition("/")
        try:
            id_ = int(str_id)
        except ValueError:
            await interaction.response.send_message("Invalid ID.", ephemeral=True)
            return
        if len(str_id) < 10:
            # GitHub entity number
            title_prefix = f"[DUPLICATE: #{id_}]"
            additional_reply = await mention_entity(int(id_), interaction.user.id)
        else:
            # Help post ID
            title_prefix = None
            additional_reply = f"Duplicate of: <#{id_}>"
        await close_post(interaction, "duplicate", title_prefix, additional_reply)

    @app_commands.command(name="stale", description="Mark post as stale.")
    async def stale(self, interaction: discord.Interaction) -> None:
        await close_post(interaction, "stale")

    @app_commands.command(name="wontfix", description="Mark post as stale.")
    async def wontfix(self, interaction: discord.Interaction) -> None:
        await close_post(interaction, "stale", "[WON'T FIX]")


bot.tree.add_command(Close(name="close", description="Mark current post as resolved."))


async def close_post(
    interaction: discord.Interaction,
    tag: Literal["solved", "moved", "duplicate", "stale"],
    title_prefix: str | None = None,
    additional_reply: str | None = None,
) -> None:
    if not (
        isinstance(post := interaction.channel, discord.Thread)
        and post.parent_id == config.HELP_CHANNEL_ID
    ):
        await interaction.response.send_message(
            f"This command can only be used in <#{config.HELP_CHANNEL_ID}> posts.",
            ephemeral=True,
        )
        return

    user = interaction.user
    assert not is_dm(user)
    if not (is_mod(user) or is_helper(user) or user.id == post.owner_id):
        await interaction.response.send_message(
            "You don't have permission to resolve this post.", ephemeral=True
        )
        return

    help_tags = {
        tag
        for tag in cast(discord.ForumChannel, post.parent).available_tags
        if tag.id in config.HELP_CHANNEL_TAG_IDS.values()
    }

    if set(post.applied_tags) & help_tags:
        await interaction.response.send_message(
            "This post was already resolved.", ephemeral=True
        )
        return

    await interaction.response.defer(ephemeral=True)
    followup = "Post closed."

    desired_tag_id = config.HELP_CHANNEL_TAG_IDS[tag]
    await post.add_tags(next(tag for tag in help_tags if tag.id == desired_tag_id))

    if title_prefix is None:
        title_prefix = f"[{tag.upper()}]"

    try:
        await post.edit(name=f"{title_prefix} {post.name}")
    except discord.HTTPException as e:
        # Re-raise if it's not because the new post title was invalid.
        if e.status != INVALID_REQUEST_DATA or e.code != INVALID_FORM_BODY:
            raise

        # HACK: there does not appear to be any way to get the actual error
        # without parsing the returned string or using a private field.  This
        # is likely a limitation of discord.py, as the Discord API
        # documentation mentions:
        #     Some of these errors may include additional details in the form
        #     of Error Messages provided by an errors object.
        # in https://discord.com/developers/docs/topics/opcodes-and-status-codes#json
        # Both approaches are going to be tried... here be dragons.
        try:
            # The format of e._errors that is being parsed below is
            # {
            #     "name": {
            #         "_errors": [
            #             {
            #                 "code": "BASE_TYPE_MAX_LENGTH",
            #                 "message": "Must be 100 or fewer in length.",
            #             }
            #         ]
            #     }
            # }
            # This tries to make as few assumptions of the keys of the
            # dictionary as possible, as the field is private.
            returned_error = next(iter(next(iter(e._errors.values())).values()))[0][  # noqa: SLF001
                "message"
            ]
        except (StopIteration, IndexError):
            try:
                # Parsing something of the form:
                # "Invalid Form Body\nIn name: Must be 100 or fewer in length."
                returned_error = (
                    str(e).splitlines()[1].removeprefix("In name: ").strip()
                )
            except IndexError:
                returned_error = None
        if not returned_error:
            followup = "Unable to change the post title."
        else:
            # Try to fix up some grammar and punctuation.
            returned_error = returned_error[0].lower() + returned_error[1:]
            if returned_error[-1] not in ".?!":
                returned_error += "."
            returned_error = returned_error.replace("must be", "must have been")
            followup = f"Unable to change the post title as it {returned_error}"

        delim = ";" if ":" in title_prefix else ":"
        title_prefix = title_prefix.removeprefix("[").removesuffix("]").lower()
        if additional_reply:
            additional_reply = f"Closed{delim} {title_prefix}.\n{additional_reply}"
        else:
            additional_reply = f"Closed{delim} {title_prefix}."

    if additional_reply:
        await post.send(additional_reply)

    await interaction.followup.send(followup, ephemeral=True)
