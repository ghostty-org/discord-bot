from tempfile import gettempdir
from typing import TYPE_CHECKING, cast

from app.config import Config, config_var

if TYPE_CHECKING:
    from contextvars import Token

    from app.bot import GhosttyBot


def config() -> Token[Config]:
    """
    Intended to be used as a context manager:

        with config():
            ...
    """
    # NOTE: stub out the functions on `bot` as needed (with SimpleNamespace) for
    # execution of the tests.
    bot = cast("GhosttyBot", object())
    return config_var.set(Config(".env.example", data_dir=gettempdir(), bot=bot))
