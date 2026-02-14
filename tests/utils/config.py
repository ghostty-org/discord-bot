from typing import TYPE_CHECKING

from app.config import Config, config_var

if TYPE_CHECKING:
    from contextvars import Token


def config() -> Token[Config]:
    """
    Intended to be used as a context manager:

        with config():
            ...
    """
    return config_var.set(Config(".env.example"))
