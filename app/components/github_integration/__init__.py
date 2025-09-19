from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from .entities import fmt as fmt
from .webhooks import monalisten_client
from app.errors import handle_task_error

if TYPE_CHECKING:
    from app.bot import GhosttyBot


async def setup(bot: GhosttyBot) -> None:
    # Creating a strong reference
    monalisten_task = asyncio.create_task(monalisten_client.listen())
    monalisten_task.add_done_callback(handle_task_error)
    bot.background_tasks.add(monalisten_task)
