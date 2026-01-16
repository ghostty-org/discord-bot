from types import SimpleNamespace
from typing import TYPE_CHECKING, Literal, cast, final, override

import discord as dc
from discord import app_commands
from discord.ext import commands

import app.components.github_integration.entities.fmt as github_entities_fmt
from app.components.github_integration.entities.cache import (
    entity_cache as github_entity_cache,
)
from toolbox.discord import generate_autocomplete, is_dm
from toolbox.message_moving import MovedMessage

if TYPE_CHECKING:
    from app.bot import GhosttyBot
    from app.components.docs import Docs

# https://discord.com/developers/docs/topics/opcodes-and-status-codes#http-http-response-codes
INVALID_REQUEST_DATA = 400
# https://discord.com/developers/docs/topics/opcodes-and-status-codes#json
INVALID_FORM_BODY = 50035

POST_TITLE_TOO_LONG = (
    "I couldn't change the post title as it was over 100 characters after modification."
)


@final
@app_commands.guild_only()
class Close(commands.GroupCog, group_name="close"):
    def __init__(self, bot: GhosttyBot) -> None:
        self.description = "Mark current post as resolved."
        self.bot = bot
        github_entity_cache.register_gh(self, self.bot.gh)

    @override
    async def cog_unload(self) -> None:
        github_entity_cache.unregister_gh(self)

    @override
    # This code does work, and the docs also state "this function **can** be
    # a coroutine", but the type signature doesn't have an async override. ¯\_(ツ)_/¯
    async def interaction_check(self, interaction: dc.Interaction, /) -> bool:  # pyright: ignore[reportIncompatibleMethodOverride]
        user = interaction.user
        if is_dm(user) or not (
            isinstance((post := interaction.channel), dc.Thread)
            and post.parent_id == self.bot.config.help_channel_id
        ):
            # Can only close posts in #help
            return False

        # Allow privileged users to close posts, as well as the author of the post.
        if self.bot.is_privileged(user) or user.id == post.owner_id:
            return True

        # When "Turn into #help post" is used, the owner ID is the ID of the webhook
        # used to send the moved message. Get the real author's ID from the subtext, if
        # possible.
        moved_message = await MovedMessage.from_message(
            # NOTE: a thread's starter message's ID is the same as the thread's ID.
            post.starter_message or await post.fetch_message(post.id)
        )
        return (
            isinstance(moved_message, MovedMessage)  # An error wasn't returned.
            and user.id == moved_message.original_author_id
        )

    @override
    async def cog_app_command_error(
        self, interaction: dc.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if type(error) is not app_commands.CheckFailure:
            raise error
        # Triggers if self.interaction_check fails
        await interaction.response.send_message(
            f"This command can only be used in {self.bot.help_channel.mention} posts, "
            "by helpers or the post's author.",
            ephemeral=True,
        )
        interaction.extras["error_handled"] = True

    async def mention_entity(self, entity_id: int) -> str | None:
        # Forging a message to use the entity mention logic
        output = await github_entities_fmt.entity_message(
            self.bot.config,
            self.bot.ghostty_emojis,
            cast("dc.Message", SimpleNamespace(content=f"#{entity_id}")),
        )
        return output.content or None

    @app_commands.command(name="solved", description="Mark post as solved.")
    @app_commands.describe(config_option="Config option name (optional)")
    async def solved(
        self, interaction: dc.Interaction, config_option: str | None = None
    ) -> None:
        if config_option:
            docs = cast("Docs | None", self.bot.cogs.get("Docs"))
            if not docs:
                await interaction.response.send_message(
                    "Docs are disabled", ephemeral=True
                )
                return
            try:
                additional_reply = docs.get_docs_link("option", config_option)
            except ValueError:
                await interaction.response.send_message(
                    f"Invalid config option: `{config_option}`", ephemeral=True
                )
                return
            title_prefix = f"[SOLVED: {config_option}]"
        else:
            title_prefix = additional_reply = None
        await self.close_post(interaction, "solved", title_prefix, additional_reply)

    @solved.autocomplete("config_option")
    async def option_autocomplete(
        self, _: dc.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        if not (docs := cast("Docs | None", self.bot.cogs.get("Docs"))):
            return []
        return generate_autocomplete(current, docs.sitemap.get("option", []))

    @app_commands.command(name="moved", description="Mark post as moved to GitHub.")
    @app_commands.describe(entity_id="New GitHub entity number")
    async def moved(self, interaction: dc.Interaction, entity_id: int) -> None:
        if not (additional_reply := await self.mention_entity(entity_id)):
            await interaction.response.send_message(
                f"Entity #{entity_id} does not exist.", ephemeral=True
            )
            return
        await self.close_post(
            interaction,
            "moved",
            title_prefix=f"[MOVED: #{entity_id}]",
            additional_reply=additional_reply,
        )

    @app_commands.command(name="duplicate", description="Mark post as duplicate.")
    @app_commands.describe(
        original="The original GitHub entity (number) or help post (ID or link)"
    )
    async def duplicate(self, interaction: dc.Interaction, original: str) -> None:
        *_, str_id = original.rpartition("/")
        try:
            id_ = int(str_id)
        except ValueError:
            await interaction.response.send_message("Invalid ID.", ephemeral=True)
            return
        if len(str_id) < 10:
            # GitHub entity number
            title_prefix = f"[DUPLICATE: #{id_}]"
            if not (additional_reply := await self.mention_entity(int(id_))):
                await interaction.response.send_message(
                    f"Entity #{id_} does not exist.", ephemeral=True
                )
                return
        else:
            # Help post ID
            title_prefix = None
            additional_reply = f"Duplicate of: <#{id_}>"
        await self.close_post(interaction, "duplicate", title_prefix, additional_reply)

    @app_commands.command(name="stale", description="Mark post as stale.")
    async def stale(self, interaction: dc.Interaction) -> None:
        await self.close_post(interaction, "stale")

    @app_commands.command(name="wontfix", description="Mark post as stale.")
    async def wontfix(self, interaction: dc.Interaction) -> None:
        await self.close_post(interaction, "stale", "[WON'T FIX]")

    @app_commands.command(name="upstream", description="Mark post as stale.")
    async def upstream(self, interaction: dc.Interaction) -> None:
        await self.close_post(interaction, "stale", "[UPSTREAM]")

    async def close_post(
        self,
        interaction: dc.Interaction,
        tag: Literal["solved", "moved", "duplicate", "stale"],
        title_prefix: str | None = None,
        additional_reply: str | None = None,
    ) -> None:
        post = interaction.channel

        assert isinstance(post, dc.Thread)
        assert post.parent_id == self.bot.config.help_channel_id

        help_tags = {
            tag
            for tag in cast("dc.ForumChannel", post.parent).available_tags
            if tag.id in self.bot.config.help_channel_tag_ids.values()
        }

        if set(post.applied_tags) & help_tags:
            await interaction.response.send_message(
                "This post was already resolved.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)

        desired_tag_id = self.bot.config.help_channel_tag_ids[tag]
        await post.add_tags(next(tag for tag in help_tags if tag.id == desired_tag_id))

        if title_prefix is None:
            title_prefix = f"[{tag.upper()}]"

        try:
            await post.edit(name=f"{title_prefix} {post.name}")
            followup = "Post closed."
        except dc.HTTPException as e:
            # Re-raise if it's not because the new post title was invalid.
            if e.status != INVALID_REQUEST_DATA or e.code != INVALID_FORM_BODY:
                raise

            # HACK: there does not appear to be any way to get the actual error without
            # parsing the returned string or using a private field. This is likely
            # a limitation of discord.py, as the Discord API documentation mentions:
            #     Some of these errors may include additional details in the form of
            #     Error Messages provided by an errors object.
            # in https://discord.com/developers/docs/topics/opcodes-and-status-codes#json.
            # Both approaches are going to be tried... here be dragons.
            try:
                returned_error = cast("str", e._errors["name"]["_errors"][0]["message"])  # pyright: ignore[reportOptionalSubscript, reportPrivateUsage] # noqa: SLF001
            except AttributeError, LookupError, TypeError:
                returned_error = str(e)

            if "or fewer in length" not in returned_error.casefold():
                raise  # The error wasn't that the post title was too long.

            followup = POST_TITLE_TOO_LONG

            delim = ";" if ":" in title_prefix else ":"
            title_prefix = title_prefix.strip("[]").lower()
            additional_reply = f"\n{additional_reply}" if additional_reply else ""
            additional_reply = f"**Closed{delim} {title_prefix}**.{additional_reply}"

        if additional_reply:
            await post.send(additional_reply)

        await interaction.followup.send(followup, ephemeral=True)


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(Close(bot))
