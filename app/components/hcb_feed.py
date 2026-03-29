import asyncio
import datetime as dt
from typing import TYPE_CHECKING, NamedTuple, Self, final, override

import discord as dc
import hcb
from discord.ext import commands, tasks
from loguru import logger

from app.config import config
from toolbox.misc import COLOR_PALETTE

if TYPE_CHECKING:
    from app.bot import GhosttyBot

GHOSTTY_ORG_ICON = (
    "https://github.com/user-attachments/assets/4e2e48dd-ffef-46b9-bc2f-3814bd44c11f"
)
ORG_USER = "Ghostty", GHOSTTY_ORG_ICON


def date_sort_key(txn: hcb.Transaction) -> dt.date:
    return txn.date.date() if txn.date else dt.date.min


class TransactionSummary(NamedTuple):
    kind: str
    sender_name: str | None
    sender_avatar_url: str | None
    memo: str | None

    @classmethod
    def from_transaction(cls, txn: hcb.Transaction) -> Self | None:
        if txn.type is None:
            logger.error("missing transaction type for {}", txn.id)
            return None
        kind = txn.type.replace("_", " ").capitalize()
        memo = txn.memo
        match txn.type:
            case "check_deposit" | "invoice" | "reimbursed_expense":
                logger.warning("unsupported transaction type {!r}", txn.type)
                return cls(kind, None, None, "*(unsupported transaction type)*")
            case "bank_account_transaction":
                if (txn.amount_cents or 0) < 0:
                    # The organization is spending
                    user = ORG_USER
                # The organization is receiving but we don't know the sender
                user = (None, None)
            case (
                "ach_transfer"
                | "card_charge"
                | "check"
                | "transfer"
                | "wire_transfer"
                | "wise_transfer"
            ):
                if txn.type == "ach_transfer":
                    kind = "ACH transfer"
                assert txn.user
                user = txn.user.full_name, txn.user.photo
            case "donation":
                don = txn.donation
                assert don
                assert don.donor
                if memo and don.recurring is not None:
                    memo += " (recurring)" if don.recurring else " (one-time)"
                user = don.donor.name, don.donor.avatar
                if user == ("Anonymous", None):
                    user = (None, None)
            case "hcb_fee":
                kind, user = "HCB fee", ORG_USER
        return cls(kind, *user, memo)


@final
class HCBFeed(commands.Cog):
    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot
        self.lock = asyncio.Lock()

        self.history_file = config().data_dir / "hcb_feed"
        self.history_file.touch()

        self.org = None
        self.update_feed.start()

    @override
    async def cog_unload(self) -> None:
        self.update_feed.cancel()

    async def publish_transaction(self, txn: hcb.Transaction) -> None:
        if not (summary := TransactionSummary.from_transaction(txn)):
            logger.warning(
                "failed to create a summary; transaction {!r} will not be published",
                txn.id,
            )
            return

        amt = txn.amount_cents
        amount = f"{'−' * (amt < 0)}${abs(amt) / 100:,.2f}" if amt is not None else "$?"  # noqa: RUF001
        color = COLOR_PALETTE["green" if amt > 0 else "red"] if amt else None

        title = f"{summary.kind}: {amount}"
        timestamp = f"  •  {txn.date:%B %-d, %Y}" if txn.date else ""
        embed = dc.Embed(color=color, title=title, description=summary.memo)
        if name := summary.sender_name:
            embed.set_author(name=name, icon_url=summary.sender_avatar_url)
        embed.set_footer(text=f"ID: {txn.id}{timestamp}")

        await config().hcb_feed_channel.send(embed=embed)

    @tasks.loop(minutes=1)
    async def update_feed(self) -> None:
        if self.lock.locked():
            return
        async with self.lock:
            assert self.org
            logger.debug("updating HCB feed")
            resp = await self.org.async_get_transactions(expand="donation")
            txns = {txn.id: txn for txn in resp}

            old_txns = set(self.history_file.read_text().strip().split(","))
            if not (new_txns := txns.keys() - old_txns):
                logger.debug("no new transactions")
                return

            logger.info(
                "found {} new transactions: {}", len(new_txns), ", ".join(new_txns)
            )
            for txn in sorted(new_txns, key=lambda k: date_sort_key(txns[k])):
                await self.publish_transaction(txns[txn])
            self.history_file.write_text(",".join(txns))

    @update_feed.before_loop
    async def before_update_feed(self) -> None:
        await self.bot.wait_until_ready()
        self.org = await hcb.async_get_organization("ghostty")


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(HCBFeed(bot))
