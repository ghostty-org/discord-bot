import datetime as dt
import json
from typing import TYPE_CHECKING, NotRequired, Self, TypedDict, cast

import discord as dc
from discord.app_commands import Choice, autocomplete

from app.common.message_moving import get_or_create_webhook
from app.components.status import bot_status
from app.setup import bot, config, gh

if TYPE_CHECKING:
    from collections.abc import Iterable

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


def _load_children(
    sitemap: dict[str, list[str]], path: str, children: list[Entry]
) -> None:
    sitemap[path] = []
    for item in children:
        sitemap[path].append((page := item["path"].lstrip("/")) or "overview")
        if item["type"] == "folder":
            _load_children(sitemap, f"{path}-{page}", item.get("children", []))


def _get_file(path: str) -> str:
    return gh.rest.repos.get_content(
        config.GITHUB_ORG,
        config.GITHUB_REPOS["web"],
        path,
        headers={"Accept": "application/vnd.github.raw+json"},
    ).text


def refresh_sitemap() -> None:
    # Reading vt/, install/, help/, config/, config/keybind/ subpages by reading
    # nav.json
    nav: list[Entry] = json.loads(_get_file("docs/nav.json"))["items"]
    for entry in nav:
        if entry["type"] != "folder":
            continue
        _load_children(sitemap, entry["path"].lstrip("/"), entry.get("children", []))

    # Reading config references by parsing headings in .mdx files
    for key, config_path in (
        ("option", "reference.mdx"),
        ("action", "keybind/reference.mdx"),
    ):
        sitemap[key] = [
            line.removeprefix("## ").strip("`")
            for line in _get_file(f"docs/config/{config_path}").splitlines()
            if line.startswith("## ")
        ]

    # Manual adjustments
    sitemap["install"].remove("release-notes")
    sitemap["keybind"] = sitemap.pop("config-keybind")
    del sitemap["install-release-notes"]
    for vt_section in (s for s in SECTIONS if s.startswith("vt-")):
        sitemap["vt"].remove(vt_section.removeprefix("vt-"))
    bot_status.last_sitemap_refresh = dt.datetime.now(tz=dt.UTC)


sitemap: dict[str, list[str]] = {}


async def section_autocomplete(_: dc.Interaction, current: str) -> list[Choice[str]]:
    return [
        Choice(name=name, value=name)
        for name in SECTIONS
        if current.casefold() in name.casefold()
    ]


async def page_autocomplete(
    interaction: dc.Interaction, current: str
) -> list[Choice[str]]:
    if not interaction.data:
        return []
    options = cast("Iterable[dict[str, str]] | None", interaction.data.get("options"))
    if not options:
        return []
    section = next(
        (opt["value"] for opt in options if opt["name"] == "section"),
        None,
    )
    if section is None:
        return []
    return [
        Choice(name=name, value=name)
        for name in sitemap.get(section, [])
        if current.casefold() in name.casefold()
    ][:25]  # Discord only allows 25 options for autocomplete


@bot.tree.command(name="docs", description="Link a documentation page.")
@autocomplete(section=section_autocomplete, page=page_autocomplete)
@dc.app_commands.guild_only()
async def docs(
    interaction: dc.Interaction, section: str, page: str, message: str = ""
) -> None:
    try:
        if not message or not isinstance(
            interaction.channel, dc.TextChannel | dc.ForumChannel
        ):
            await interaction.response.send_message(get_docs_link(section, page))
            return
        webhook = await get_or_create_webhook(interaction.channel)
        await webhook.send(
            f"{message}\n{get_docs_link(section, page)}",
            username=interaction.user.display_name,
            avatar_url=interaction.user.display_avatar.url,
        )
        await interaction.response.send_message("Documentation linked.", ephemeral=True)
    except ValueError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
    except dc.HTTPException:
        await interaction.response.send_message(
            "Message content too long.", ephemeral=True
        )


def get_docs_link(section: str, page: str) -> str:
    if section not in SECTIONS:
        msg = f"Invalid section {section!r}"
        raise ValueError(msg)
    if page not in sitemap.get(section, []):
        msg = f"Invalid page {page!r}"
        raise ValueError(msg)
    return URL_TEMPLATE.format(
        section=SECTIONS[section],
        page=page if page != "overview" else "",
    )
