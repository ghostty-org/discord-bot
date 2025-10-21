import datetime as dt
from typing import Any, cast
from unittest.mock import Mock

import discord as dc


def _spawn_message(**kwargs: Any) -> dc.Message:
    kwargs = {"created_at": dt.datetime.now(tz=dt.UTC)} | kwargs
    if age := kwargs.pop("age", None):
        kwargs["created_at"] -= cast("dt.timedelta", age)
    return Mock(dc.Message, **kwargs)


def spawn_user_message(**kwargs: Any) -> dc.Message:
    return _spawn_message(author=Mock(bot=False), **kwargs)


def spawn_bot_message(**kwargs: Any) -> dc.Message:
    return _spawn_message(author=Mock(bot=True), **kwargs)
