import discord as dc
from discord.ext import commands
from githubkit import GitHub

from app import config

intents = dc.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(
    command_prefix=commands.when_mentioned_or("!"),
    intents=intents,
    allowed_mentions=dc.AllowedMentions(everyone=False, roles=False),
)

gh = GitHub(config.GITHUB_TOKEN)
