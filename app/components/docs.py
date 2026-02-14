import datetime as dt
import json
from typing import TYPE_CHECKING, NotRequired, Self, TypedDict, cast, final, override

import discord as dc
from discord.app_commands import Choice  # noqa: TC002
from discord.ext import commands
from githubkit.exception import RequestFailed
from loguru import logger

from app.config import config, gh
from toolbox.discord import generate_autocomplete
from toolbox.message_moving import get_or_create_webhook

if TYPE_CHECKING:
    from collections.abc import Iterable

    from app.bot import GhosttyBot

URL_TEMPLATE = "https://ghostty.org/docs/{section}{page}"

SECTIONS = {
    "action": "config/keybind/reference#",
    "config": "config/",
    "help": "help/",
    "install": "install/",
    "keybind": "config/keybind/",
    "option": "config/reference#",
    "vt-concepts": "vt/concepts/",
    "vt-control": "vt/control/",
    "vt-csi": "vt/csi/",
    "vt-esc": "vt/esc/",
    "vt": "vt/",
}


class Entry(TypedDict):
    type: str
    path: str
    children: NotRequired[list[Self]]


@final
class Docs(commands.Cog):
    sitemap: dict[str, list[str]]

    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot
        self.sitemap = {}

    @override
    async def cog_load(self) -> None:
        try:
            await self.refresh_sitemap()
        except RequestFailed:
            logger.warning(
                "refreshing sitemap failed, running bot with limited functionality"
            )

    @dc.app_commands.command(name="docs", description="Link a documentation page.")
    @dc.app_commands.guild_only()
    async def docs(
        self, interaction: dc.Interaction, section: str, page: str, message: str = ""
    ) -> None:
        try:
            if not message or not isinstance(
                interaction.channel, dc.TextChannel | dc.ForumChannel
            ):
                await interaction.response.send_message(
                    self.get_docs_link(section, page)
                )
                return
            webhook = await get_or_create_webhook(interaction.channel)
            await webhook.send(
                f"{message}\n{self.get_docs_link(section, page)}",
                username=interaction.user.display_name,
                avatar_url=interaction.user.display_avatar.url,
            )
            await interaction.response.send_message(
                "Documentation linked.", ephemeral=True
            )
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
        except dc.HTTPException:
            await interaction.response.send_message(
                "Message content too long.", ephemeral=True
            )

    def _load_children(
        self, sitemap: dict[str, list[str]], path: str, children: list[Entry]
    ) -> None:
        sitemap[path] = []
        for item in children:
            sitemap[path].append((page := item["path"].lstrip("/")) or "overview")
            if item["type"] == "folder":
                self._load_children(sitemap, f"{path}-{page}", item.get("children", []))

    async def _get_file(self, path: str) -> str:
        return (
            await gh().rest.repos.async_get_content(
                config().github_org,
                "website",
                path,
                headers={"Accept": "application/vnd.github.raw+json"},
            )
        ).text

    @dc.app_commands.command(name="refresh-docs", description="Refresh sitemap docs.")
    @dc.app_commands.guild_only()
    # Hide interaction from non-mods
    @dc.app_commands.default_permissions(ban_members=True)
    async def refresh_docs(self, interaction: dc.Interaction) -> None:
        # The client-side check with `default_permissions` isn't guaranteed to work.
        if not self.bot.is_ghostty_mod(interaction.user):
            await interaction.response.send_message(
                "Only mods can run this command", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await self.refresh_sitemap()
        await interaction.followup.send("Sitemap refreshed.", ephemeral=True)

    async def refresh_sitemap(self) -> None:
        # Reading vt/, install/, help/, config/, config/keybind/ subpages by reading
        # nav.json
        nav: list[Entry] = json.loads(await self._get_file("docs/nav.json"))["items"]
        for entry in nav:
            if entry["type"] != "folder":
                continue
            self._load_children(
                self.sitemap, entry["path"].lstrip("/"), entry.get("children", [])
            )

        # Reading config references by parsing headings in .mdx files
        for key, config_path in (
            ("option", "reference.mdx"),
            ("action", "keybind/reference.mdx"),
        ):
            self.sitemap[key] = [
                line.removeprefix("## ").strip("`")
                for line in (
                    await self._get_file(f"docs/config/{config_path}")
                ).splitlines()
                if line.startswith("## ")
            ]

        # Manual adjustments
        self.sitemap["install"].remove("release-notes")
        self.sitemap["keybind"] = self.sitemap.pop("config-keybind")
        del self.sitemap["install-release-notes"]
        for vt_section in (s for s in SECTIONS if s.startswith("vt-")):
            self.sitemap["vt"].remove(vt_section.removeprefix("vt-"))
        self.bot.bot_status.last_sitemap_refresh = dt.datetime.now(tz=dt.UTC)

    @docs.autocomplete("section")
    async def section_autocomplete(
        self, _: dc.Interaction, current: str
    ) -> list[Choice[str]]:
        return generate_autocomplete(current, SECTIONS)

    @docs.autocomplete("page")
    async def page_autocomplete(
        self, interaction: dc.Interaction, current: str
    ) -> list[Choice[str]]:
        if not interaction.data:
            return []
        options = cast(
            "Iterable[dict[str, str]] | None", interaction.data.get("options")
        )
        if not options:
            return []
        section = next(
            (opt["value"] for opt in options if opt["name"] == "section"),
            None,
        )
        if section is None:
            return []
        return generate_autocomplete(current, self.sitemap.get(section, []))

    def get_docs_link(self, section: str, page: str) -> str:
        if section not in SECTIONS:
            msg = f"Invalid section {section!r}"
            raise ValueError(msg)
        if page not in self.sitemap.get(section, []):
            msg = f"Invalid page {page!r}"
            raise ValueError(msg)
        return URL_TEMPLATE.format(
            section=SECTIONS[section],
            page=page if page != "overview" else "",
        )


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(Docs(bot))
