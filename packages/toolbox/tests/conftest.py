import pytest

from tests.fixtures.hooks import edit_hook, linker

__all__ = ("edit_hook", "linker")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
