import asyncio
import datetime as dt
from json import JSONDecodeError
from pathlib import Path
from typing import TYPE_CHECKING, NamedTuple
from unittest.mock import AsyncMock, Mock, patch

import discord as dc
import hcb
import httpx
import pytest
from discord.ext import tasks
from hcb.requests import HCBAPIError
from pydantic import ValidationError

from app.bot import GhosttyBot
from app.components import hcb_feed
from app.config import Channels, Config, config_var

if TYPE_CHECKING:
    from collections.abc import Generator


class FeedHarness(NamedTuple):
    feed: hcb_feed.HCBFeed
    fetch: AsyncMock
    send: AsyncMock
    lookup: AsyncMock


@pytest.fixture
def harness(tmp_path: Path) -> Generator[FeedHarness]:
    fetch = AsyncMock(return_value=[])
    send = AsyncMock()
    org = Mock(hcb.Organization, async_get_transactions=fetch)
    lookup = AsyncMock(return_value=org)
    bot = Mock(GhosttyBot, wait_until_ready=AsyncMock())

    cfg = Mock(
        Config,
        data_dir=tmp_path,
        channels=Channels(
            Mock(dc.TextChannel, send=send), Mock(dc.ForumChannel), Mock(dc.TextChannel)
        ),
    )
    with config_var.set(cfg), patch.object(hcb, "async_get_organization", new=lookup):
        with patch.object(tasks.Loop, "start"):
            feed = hcb_feed.HCBFeed(bot)

        feed.history_file.write_text("260901_old")
        yield FeedHarness(feed, fetch, send, lookup)


def transaction(txn_id: str, **changes: object) -> hcb.Transaction:
    return hcb.Transaction.model_validate(
        {
            "id": txn_id,
            "object": "transaction",
            "href": f"https://example.com/{txn_id}",
            "type": "hcb_fee",
            "pending": False,
            "amount_cents": -100,
            "date": dt.datetime(2026, 9, 1, tzinfo=dt.UTC),
        }
        | changes
    )


def history(feed: hcb_feed.HCBFeed) -> set[str]:
    return set(filter(None, feed.history_file.read_text().split(",")))


async def run_polls(feed: hcb_feed.HCBFeed, count: int) -> None:
    # We run the actual scheduler to detect exceptions that terminate its task.
    feed.feed_loop.change_interval(seconds=0.001)
    feed.feed_loop.count = count
    task = feed.feed_loop.start()
    try:
        # Timeout in case the loop hangs or never reaches its iteration limit.
        async with asyncio.timeout(1):
            await task
        # This checks task termination; callers also assert calls and history because a
        # loop that catches every error could still do no useful work.
        assert not feed.feed_loop.failed()
    finally:
        await feed.cog_unload()


@pytest.mark.parametrize(
    "error",
    [
        httpx.ReadTimeout("response headers timed out"),
        httpx.ConnectError("connection failed"),
        HCBAPIError("temporarily unavailable"),
        JSONDecodeError("invalid JSON", "", 0),
        ValidationError.from_exception_data(
            "Transaction", [{"type": "missing", "loc": ("id",), "input": {}}]
        ),
        RuntimeError("unexpected processing failure"),
    ],
)
@pytest.mark.parametrize("failure_count", [1, 3])
async def test_poll_recovers(
    harness: FeedHarness, error: Exception, failure_count: int
) -> None:
    # Reproduce a healthy poll, one or more outages, then recovery on the same loop.
    attempt = 0
    snapshots: list[set[str]] = []

    async def fetch(**_: object) -> list[hcb.Transaction]:
        nonlocal attempt
        attempt += 1
        snapshots.append(history(harness.feed))
        if attempt == 1:
            return [transaction("txn_old")]
        if attempt <= failure_count + 1:
            raise error
        return [transaction("txn_old"), transaction("txn_new")]

    harness.fetch.side_effect = fetch
    with patch.object(hcb_feed.logger, "info") as info:  # pyright: ignore[reportPrivateLocalImportUsage]
        await run_polls(harness.feed, failure_count + 2)
        recovery_calls = [
            call
            for call in info.call_args_list
            if call.args == ("HCB feed polling recovered",)
        ]

    assert len(recovery_calls) == 1
    assert snapshots == [{"260901_old"}] * (failure_count + 2)
    assert harness.fetch.await_count == failure_count + 2
    harness.lookup.assert_awaited_once_with("ghostty")
    harness.fetch.assert_awaited_with(expand="donation", per_page=100)
    harness.send.assert_awaited_once()
    assert history(harness.feed) == {"260901_old", "260901_new"}


async def test_initialization_recovers(harness: FeedHarness) -> None:
    # Fail before an organization is fetched. Initialization must be retried inside of
    # the update loop, with no transaction polling or send on the failed attempt.
    org = harness.lookup.return_value
    harness.lookup.side_effect = [httpx.ConnectError("startup connection failed"), org]
    harness.fetch.return_value = [transaction("txn_old"), transaction("txn_new")]

    await run_polls(harness.feed, 2)

    assert harness.lookup.await_count == 2
    harness.fetch.assert_awaited_once()
    harness.send.assert_awaited_once()
    assert history(harness.feed) == {"260901_old", "260901_new"}


@pytest.mark.parametrize("failure_stage", ["format", "send"])
async def test_failed_transaction_remains_retryable(
    harness: FeedHarness, failure_stage: str
) -> None:
    first = transaction("txn_a")
    second = transaction("txn_b")
    skipped = transaction("txn_c", type=None)
    harness.fetch.return_value = [second, skipped, first, transaction("txn_old")]

    if failure_stage == "format":
        summarize = hcb_feed.TransactionSummary.from_transaction

        def fail_first(txn: hcb.Transaction) -> hcb_feed.TransactionSummary | None:
            if txn.id == first.id:
                msg = "formatting failed"
                raise ValueError(msg)
            return summarize(txn)

        with patch.object(
            hcb_feed.TransactionSummary, "from_transaction", side_effect=fail_first
        ):
            await harness.feed.feed_loop()
    else:
        harness.send.side_effect = [RuntimeError("send failed"), None]
        await harness.feed.feed_loop()

    # Neither an exception nor an unpublished summary counts as delivery.
    assert history(harness.feed) == {"260901_old", "260901_b"}
    # Remove the injected send failure and inspect only the next poll's calls.
    harness.send.reset_mock(side_effect=True)

    await harness.feed.feed_loop()

    # Only `a` is retried successfully; `b` is already recorded and `c` stays skipped.
    harness.send.assert_awaited_once()
    assert history(harness.feed) == {"260901_old", "260901_a", "260901_b"}
    harness.send.reset_mock()

    await harness.feed.feed_loop()

    harness.send.assert_not_awaited()


async def test_missing_donor_details(harness: FeedHarness) -> None:
    harness.fetch.return_value = [
        transaction("txn_old"),
        transaction(
            "txn_donation",
            type="donation",
            donation={
                "id": "don_test",
                "object": "donation",
                "href": "https://example.com/don_test",
                "donor": None,
            },
        ),
    ]

    await harness.feed.feed_loop()

    harness.send.assert_awaited_once()
    assert history(harness.feed) == {"260901_old", "260901_donation"}
    embed = harness.send.await_args_list[0].kwargs["embed"]
    assert embed.author.name is None


async def test_missing_donation_does_not_block_batch(harness: FeedHarness) -> None:
    harness.fetch.return_value = [
        transaction("txn_old"),
        transaction("txn_a", type="donation", donation=None),
        transaction("txn_b"),
    ]

    await harness.feed.feed_loop()

    harness.send.assert_awaited_once()
    assert history(harness.feed) == {"260901_old", "260901_b"}

    # Once the API provides usable data, the failed transaction is retried.
    harness.fetch.return_value = [
        transaction("txn_old"),
        transaction(
            "txn_a",
            type="donation",
            donation={
                "id": "don_test",
                "object": "donation",
                "href": "https://example.invalid/don_test",
                "donor": None,
            },
        ),
        transaction("txn_b"),
    ]
    harness.send.reset_mock()

    await harness.feed.feed_loop()

    harness.send.assert_awaited_once()
    assert history(harness.feed) == {"260901_old", "260901_a", "260901_b"}


async def test_baseline(harness: FeedHarness) -> None:
    harness.feed.history_file.unlink()
    harness.fetch.return_value = [transaction("txn_foo")]

    await harness.feed.feed_loop()

    assert harness.feed.history_file.read_text() == "260901_foo"
    assert harness.send.await_count == 0


async def test_filtering_and_order(harness: FeedHarness) -> None:
    harness.fetch.return_value = [
        transaction("txn_newer", date=dt.datetime(2026, 9, 2, tzinfo=dt.UTC)),
        transaction("txn_new"),
        transaction("txn_pending", pending=True),
        transaction("txn_unknown", pending=None),
    ]

    await harness.feed.feed_loop()

    # Transactions still pending (or of unknown state) should not enter history.
    assert history(harness.feed) == {"260901_old", "260901_new", "260902_newer"}
    assert harness.send.await_count == 2

    # Notifications must be chronological even when the API returns newest first.
    embed_footers = [
        call.kwargs["embed"].footer.text for call in harness.send.await_args_list
    ]
    assert embed_footers[0].startswith("ID: txn_new")
    assert embed_footers[1].startswith("ID: txn_newer")

    # Both baselined and successfully published IDs suppress later duplicates.
    harness.send.reset_mock()
    await harness.feed.feed_loop()
    harness.send.assert_not_awaited()


async def test_history_failure_stops_batch(harness: FeedHarness) -> None:
    harness.fetch.return_value = [
        transaction("txn_old"),
        transaction("txn_a"),
        transaction("txn_b"),
    ]

    with patch.object(
        harness.feed, "_append_history", side_effect=OSError("append failed")
    ):
        await harness.feed.feed_loop()

    # Abort before sending b: continuing would create more unrecorded deliveries.
    harness.send.assert_awaited_once()
    assert history(harness.feed) == {"260901_old"}
    assert not harness.feed.history_file.with_name("hcb_feed.tmp").exists()
    assert harness.feed.poll_failed

    await harness.feed.feed_loop()

    # The unrecorded first delivery is retried, then the second is sent. This documents
    # the duplicate possible between a send and its history write.
    assert harness.send.await_count == 3
    assert history(harness.feed) == {"260901_old", "260901_a", "260901_b"}
    assert not harness.feed.poll_failed


async def test_history_replacement_failure_preserves_deliveries(
    harness: FeedHarness,
) -> None:
    harness.fetch.return_value = [
        transaction("txn_old"),
        transaction("txn_a"),
        transaction("txn_b"),
    ]

    with patch.object(Path, "replace", side_effect=OSError("replacement failed")):
        await harness.feed.feed_loop()

    # Each delivery is appended before the final history replacement is attempted.
    assert harness.send.await_count == 2
    assert history(harness.feed) == {"260901_old", "260901_a", "260901_b"}
    assert not harness.feed.history_file.with_name("hcb_feed.tmp").exists()
    assert harness.feed.poll_failed
    harness.send.reset_mock()

    await harness.feed.feed_loop()

    harness.send.assert_not_awaited()
    assert history(harness.feed) == {"260901_old", "260901_a", "260901_b"}
    assert not harness.feed.poll_failed


async def test_history_file_is_limited_to_500_entries(harness: FeedHarness) -> None:
    harness.feed.history_file.write_text(",".join(f"260901_{i:03}" for i in range(498)))
    harness.fetch.return_value = [
        transaction(f"txn_{i}", date=dt.date(2026, 9, 2)) for i in range(5)
    ]

    await harness.feed.feed_loop()

    new_history = harness.feed.history_file.read_text().split(",")

    assert len(new_history) == 500
    assert new_history[:10] == [f"260901_{i:03}" for i in range(3, 13)]
    assert new_history[-10:] == [
        *(f"260901_{i:03}" for i in range(493, 498)),
        *(f"260902_{i}" for i in range(5)),
    ]


async def test_no_resend_on_transaction_date_change(harness: FeedHarness) -> None:
    harness.fetch.return_value = [transaction("txn_old", date=dt.date(2026, 9, 2))]

    await harness.feed.feed_loop()

    assert harness.send.await_count == 0
