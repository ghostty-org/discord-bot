from pathlib import Path

import pytest

VS16 = "\ufe0f"
VS16_SUPPRESS_COMMENT = "# test: allow-vs16"


def check_dir_for_vs16(path: Path) -> None:
    error_locations: list[tuple[Path, int]] = []
    for file in path.rglob("*.py"):
        for line_no, line in enumerate(file.read_text().splitlines(), 1):
            if VS16 in line and VS16_SUPPRESS_COMMENT not in line:
                error_locations.append((file, line_no))

    if error_locations:
        raise AssertionError(
            f"unsuppressed VS16 found in {len(error_locations)} lines:\n"
            + "\n".join(f"- {file}:{line_no}" for file, line_no in error_locations)
        )


@pytest.mark.parametrize("folder", ["app", "tests"])
def test_self_unwanted_vs16(folder: str) -> None:
    root = Path(__file__).parents[1]
    check_dir_for_vs16(root / folder)


def test_dummy_unwanted_vs16(tmp_path: Path) -> None:
    (tmp_path / "foo").mkdir()
    (tmp_path / "foo" / "bar.py").write_text(VS16)
    (tmp_path / "foo" / "baz.py").write_text("\u2764" + VS16)

    (tmp_path / "qux").mkdir()
    (tmp_path / "qux" / "foo.py").write_text("\u2764\ufffd")
    (tmp_path / "qux" / "bar.txt").write_text(VS16)

    check_dir_for_vs16(tmp_path / "qux")

    with pytest.raises(AssertionError, match="found in 2 lines"):
        check_dir_for_vs16(tmp_path / "foo")
