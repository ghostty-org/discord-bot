from unittest.mock import Mock

from githubkit_schemas.latest.models import (  # pyright: ignore[reportMissingTypeStubs]
    SimpleUser,
)
from hypothesis import assume, given
from hypothesis import strategies as st

from toolbox.github import format_diff_note, format_event_sender


@given(st.integers(), st.integers(), st.integers())
def test_format_diff_note(additions: int, deletions: int, changed_files: int) -> None:
    assume(changed_files and (additions or deletions))
    formatted = format_diff_note(additions, deletions, changed_files)
    assert formatted is not None
    assert f"+{additions}" in formatted
    assert f"-{deletions}" in formatted
    assert str(changed_files) in formatted


def test_format_diff_note_unavailable() -> None:
    assert format_diff_note(0, 0, 0) is None


@given(st.text())
def test_format_event_sender_present(login: str) -> None:
    assert login in format_event_sender(Mock(SimpleUser, login=login))


def test_format_event_sender_missing() -> None:
    assert format_event_sender(None) == "?"
