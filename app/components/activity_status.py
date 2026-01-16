import secrets
from typing import TYPE_CHECKING, final, override

from discord import CustomActivity
from discord.ext import commands, tasks

if TYPE_CHECKING:
    from app.bot import GhosttyBot

STATUSES = (
    CustomActivity("Watching over the Ghostty server 👻"),
    CustomActivity("Haunting your threads 🧵"),
    CustomActivity("Admiring posts in #showcase"),
    CustomActivity("Watching over #help"),
    CustomActivity("Listening to your complaints"),
    CustomActivity("Playing with my config file"),
    CustomActivity("Competing in the terminal game"),
)


@final
class ActivityStatus(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot
        self.randomize.start()

    @override
    async def cog_unload(self) -> None:
        self.randomize.cancel()

    @tasks.loop(hours=2)
    async def randomize(self) -> None:
        await self.bot.change_presence(activity=secrets.choice(STATUSES))

    @randomize.before_loop
    async def before_randomize(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(ActivityStatus(bot))
