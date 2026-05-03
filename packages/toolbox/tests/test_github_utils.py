from hypothesis import assume, given
from hypothesis import strategies as st

from toolbox.github import format_diff_note


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
