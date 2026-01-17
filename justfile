[private]
default:
    @just --list

# Run taplo, ruff, pytest, and basedpyright in check mode
check:
    uv run taplo fmt --check --diff pyproject.toml
    uv run ruff format --check
    uv run ruff check
    uv run pytest -p terminalprogress
    uv run basedpyright app tests

# Run taplo, ruff's formatter, and ruff's isort rules in fix mode
format:
    uv run taplo fmt pyproject.toml
    uv run ruff format
    uv run ruff check --select I,RUF022,RUF023 --fix

# Run taplo and ruff in fix mode
fix: format
    uv run ruff check --fix
