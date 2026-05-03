[private]
default:
    @just --list

set windows-shell := ["cmd.exe", "/c"]

# Run ruff, basedpyright, pytest, taplo, and mdformat in check mode
check:
    uv run ruff check
    @just check-package packages/toolbox
    uv run basedpyright app tests
    uv run pytest -p terminalprogress tests
    uv run taplo fmt --check --diff pyproject.toml config-example.toml
    uv run ruff format --diff
    uv run mdformat --number --wrap 80 --check *.md

[private]
check-package pkg:
    cd {{pkg}} && uv run basedpyright src tests
    cd {{pkg}} && uv run pytest -p terminalprogress tests
    cd {{pkg}} && uv run taplo fmt --check --diff pyproject.toml

# Run taplo, ruff's formatter, ruff's isort rules, and mdformat in fix mode
format:
    uv run taplo fmt pyproject.toml packages/*/pyproject.toml config-example.toml
    uv run ruff format
    uv run ruff check --select I,RUF022,RUF023 --fix
    uv run mdformat --number --wrap 80 *.md

# Run taplo, ruff, and mdformat in fix mode
fix: format
    uv run ruff check --fix
