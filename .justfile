dev:
    uv run fastapi dev app/main.py

install:
    uv sync

format:
    ruff format .