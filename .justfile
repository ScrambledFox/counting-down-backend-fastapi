dev:
    uv run fastapi dev app/main.py

install:
    uv sync

format:
    ruff check --fix .
    ruff format .

test:
    uv run pytest --cov=app --cov-report=term-missing tests