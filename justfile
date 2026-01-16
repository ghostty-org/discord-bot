[private]
default:
    @just --list

# Run taplo, ruff, pytest, and basedpyright in check mode
check:
    uv run ruff check
    uv run basedpyright app tests packages
    uv run pytest -p terminalprogress
    uv run taplo fmt --check --diff pyproject.toml packages/*/pyproject.toml
    uv run ruff format --check

# Run taplo, ruff's formatter, and ruff's isort rules in fix mode
format:
    uv run taplo fmt pyproject.toml packages/*/pyproject.toml
    uv run ruff format
    uv run ruff check --select I,RUF022,RUF023 --fix

# Run taplo and ruff in fix mode
fix: format
    uv run ruff check --fix
