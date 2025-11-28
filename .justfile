dev:
    uv run fastapi dev app/main.py --reload --host 0.0.0.0 --port 8000

install:
    uv sync

format:
    ruff check --fix .
    ruff format .

test:
    uv run pytest --cov=app --cov-report=term-missing tests