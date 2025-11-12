dev:
    uv run fastapi dev app/main.py

install:
    uv sync

format:
    ruff check --fix app tests
    ruff format app tests