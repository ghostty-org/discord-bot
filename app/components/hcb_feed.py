import datetime as dt
from itertools import islice
from typing import TYPE_CHECKING, NamedTuple, Self, assert_never, final, override

import discord as dc
import hcb
from discord.ext import commands, tasks
from loguru import logger

from app.config import config
from toolbox.misc import COLOR_PALETTE

if TYPE_CHECKING:
    from collections.abc import Iterable

    from app.bot import GhosttyBot

GHOSTTY_ORG_ICON = (
    "https://github.com/user-attachments/assets/4e2e48dd-ffef-46b9-bc2f-3814bd44c11f"
)
ORG_USER = "Ghostty", GHOSTTY_ORG_ICON


def transaction_key(txn: hcb.Transaction) -> str:
    date = txn.date.date() if txn.date else dt.date.min
    return f"{date:%y%m%d}{txn.id.removeprefix('txn')}"


class TransactionSummary(NamedTuple):
    kind: str
    sender_name: str | None
    sender_avatar_url: str | None
    memo: str | None

    @classmethod
    def from_transaction(cls, txn: hcb.Transaction) -> Self | None:
        if txn.type is None:
            logger.error("missing transaction type for {txn}", txn=txn.id)
            return None

        # Acceptable fallbacks
        kind = txn.type.replace("_", " ").capitalize()
        memo = txn.memo
        user = (None, None)

        match txn.type:
            case "check_deposit" | "invoice" | "reimbursed_expense" as unsupported:
                logger.warning(
                    "unsupported transaction type {txn_type!r}", txn_type=unsupported
                )
                memo = "*(unsupported transaction type)*"
            case "bank_account_transaction":
                if (txn.amount_cents or 0) < 0:
                    # The organization is spending. In other cases we don't know the
                    # sender as this transaction type doesn't provide it.
                    user = ORG_USER
            case (
                "ach_transfer"
                | "card_charge"
                | "check"
                | "transfer"
                | "wire_transfer"
                | "wise_transfer"
            ):
                if txn.type == "ach_transfer":
                    # Casing adjustment
                    kind = "ACH transfer"
                if txn.user:
                    user = (txn.user.full_name, txn.user.photo)
                elif (txn.amount_cents or 0) < 0:
                    user = ORG_USER
            case "donation":
                don = txn.donation
                assert don
                if memo and don.recurring is not None:
                    memo += " (recurring)" if don.recurring else " (one-time)"
                if don.donor is not None:
                    donor_info = don.donor.name, don.donor.avatar
                    # We don't want to set the field for anonymous users as it's not
                    # very helpful and only takes up space.
                    if donor_info != ("Anonymous", None):
                        user = donor_info
            case "hcb_fee":
                kind = "HCB fee"
                user = ORG_USER
            case _:
                # This will only get triggered if HCB adds a new transaction type.
                assert_never(txn.type)

        return cls(kind, *user, memo)


@final
class HCBFeed(commands.Cog):
    org: hcb.Organization | None

    def __init__(self, bot: GhosttyBot) -> None:
        self.bot = bot

        self.poll_failed = False
        self.history_file = config().data_dir / "hcb_feed"

        self.org = None
        self.feed_loop.start()

    @override
    async def cog_unload(self) -> None:
        self.feed_loop.cancel()

    async def publish_transaction(self, txn: hcb.Transaction) -> bool:
        if not (summary := TransactionSummary.from_transaction(txn)):
            logger.warning(
                "failed to create a summary; transaction {txn!r} will not be published",
                txn=txn.id,
            )
            return False

        amt = txn.amount_cents
        amount = f"{'−' * (amt < 0)}${abs(amt) / 100:,.2f}" if amt is not None else "$?"  # noqa: RUF001
        color = COLOR_PALETTE["green" if amt > 0 else "red"] if amt else None

        title = f"{summary.kind}: {amount}"
        timestamp = f"  •  {txn.date:%B %-d, %Y}" if txn.date else ""
        embed = dc.Embed(color=color, title=title, description=summary.memo)
        if name := summary.sender_name:
            embed.set_author(name=name, icon_url=summary.sender_avatar_url)
        embed.set_footer(text=f"ID: {txn.id}{timestamp}")

        await config().channels.hcb_feed.send(embed=embed)
        return True

    @tasks.loop(minutes=3)
    async def feed_loop(self) -> None:
        try:
            await self._update_feed()
        except Exception:
            self.poll_failed = True
            logger.exception("HCB feed poll failed; retrying on next scheduled poll")
        else:
            if self.poll_failed:
                logger.info("HCB feed polling recovered")
            self.poll_failed = False

    async def _update_feed(self) -> None:
        if self.org is None:
            logger.debug("initializing HCB feed organization")
            self.org = await hcb.async_get_organization("ghostty")

        logger.debug("fetching HCB feed transactions")
        resp = await self.org.async_get_transactions(expand="donation", per_page=100)

        # Temporary log for response and behavior tracking, to be removed soon hopefully
        resp_summary = ";".join(
            f"{transaction_key(txn)},p={txn.pending}" for txn in resp
        )
        logger.info("HCB response: {response}", response=resp_summary)

        transactions = {
            transaction_key(txn): txn
            for txn in islice((txn for txn in resp if txn.pending is False), 50)
        }

        try:
            history = self.history_file.read_text()
        except FileNotFoundError:
            # Ignore the new transactions and pretend they had already been sent, so as
            # to avoid spamming 50 transactions when the history file is created for the
            # first time.
            logger.warning(
                "HCB feed history file not found; baselining {txn_count} transactions",
                txn_count=len(transactions),
            )
            self._save_history(transactions)
            return

        sent_keys = set(history.strip().split(","))
        sent_ids = {f"txn{sent_key[6:]}" for sent_key in sent_keys}

        new_transactions = {
            txn_key: txn
            for txn_key, txn in sorted(transactions.items(), key=lambda i: i[0])
            if txn.id not in sent_ids
        }
        if not new_transactions:
            logger.debug("no new transactions")
            return

        logger.info(
            "found {txn_count} new transactions: {txn_ids}",
            txn_count=len(new_transactions),
            txn_ids=", ".join(new_transactions),
        )
        published = None
        for txn_key, txn in new_transactions.items():
            try:
                published = await self.publish_transaction(txn)
            except Exception:
                logger.exception(
                    "failed to publish HCB transaction {txn_id!r}; leaving for retry",
                    txn_id=txn_key,
                )
                continue

            if published:
                sent_keys.add(txn_key)
                self._append_history(txn_key)
        if published is not None:
            self._save_history(sent_keys)

    def _append_history(self, transaction_id: str) -> None:
        with self.history_file.open("a") as f:
            f.write(f",{transaction_id}")

    def _save_history(self, transaction_ids: Iterable[str]) -> None:
        temp = self.history_file.with_suffix(".tmp")
        try:
            temp.write_text(",".join(sorted(transaction_ids)[-500:]))
            temp.replace(self.history_file)
        finally:
            temp.unlink(missing_ok=True)

    @feed_loop.before_loop
    async def before_update_feed(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: GhosttyBot) -> None:
    await bot.add_cog(HCBFeed(bot))
