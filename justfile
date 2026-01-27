[private]
default:
    @just --list

set windows-shell := ["cmd.exe", "/c"]

# Run taplo, ruff, pytest, and basedpyright in check mode
check:
    uv run ruff check
    @just check-package packages/toolbox
    uv run basedpyright app tests
    uv run pytest -p terminalprogress tests
    uv run taplo fmt --check --diff pyproject.toml
    uv run ruff format --check
    uv run mdformat --number --wrap 80 --check README.md

[private]
check-package pkg:
    cd {{pkg}} && uv run basedpyright src tests
    cd {{pkg}} && uv run pytest -p terminalprogress tests
    cd {{pkg}} && uv run taplo fmt --check --diff pyproject.toml

# Run taplo, ruff's formatter, and ruff's isort rules in fix mode
format:
    uv run taplo fmt pyproject.toml packages/*/pyproject.toml
    uv run ruff format
    uv run ruff check --select I,RUF022,RUF023 --fix
    uv run mdformat --number --wrap 80 README.md

# Run taplo and ruff in fix mode
fix: format
    uv run ruff check --fix
