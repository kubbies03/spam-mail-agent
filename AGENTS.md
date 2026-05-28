# Repository Guidelines

## Project Structure & Module Organization

This is a Python spam email detection agent. Runtime entry points live in `main.py`, while reusable code is under `src/`. Key modules include `pipeline.py` for orchestration, `classifier.py` for spam scoring, `router.py` for fast-path versus agent routing, `db.py` for persistence, and integrations such as `email_fetcher.py` and `telegram_bot.py`.

Tests are in `tests/`, for example `tests/test_classifier.py` and `tests/test_router.py`. Training and model utilities are in `scripts/`. Local data, SQLite state, and trained artifacts are stored in `data/` and `models/`; treat those as generated unless a change is intentional.

## Build, Test, and Development Commands

Create a local environment and install dependencies:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Train the primary DistilBERT classifier:

```bash
python scripts/train_distilbert.py --csv data/spam_dataset.csv --epochs 2 --batch-size 8
```

Train the fallback SVM/TF-IDF baseline:

```bash
python scripts/train.py --csv data/spam_dataset.csv
```

Run the CLI against sample text:

```bash
python main.py classify-text --text "urgent verify password at http://example.test"
```

Run all tests:

```bash
pytest
```

Use Docker for a production-like run:

```bash
docker compose up --build -d
```

## Coding Style & Naming Conventions

Use Python 3 with 4-space indentation, type hints where practical, and small functions that keep I/O, model logic, and orchestration separate. Modules and functions use `snake_case`, classes use `PascalCase`, and tests use `test_<behavior>.py`. Prefer Pydantic schemas from `src/schemas.py` over loose dictionaries.

## Testing Guidelines

The project uses `pytest` and `pytest-asyncio`. Add or update tests in `tests/` for any behavior change, especially routing rules, database writes, parser behavior, and classifier signal extraction. Keep tests deterministic; avoid live Gmail, Telegram, Gemini, VirusTotal, Redis, or remote model downloads. Mock external services and use temporary databases where persistence is required.

## Commit & Pull Request Guidelines

The visible history uses concise conventional-style commits such as `docs: add ref`. Prefer `feat:`, `fix:`, `test:`, `docs:`, or `chore:` followed by a short imperative summary.

Pull requests should include a clear description, test results such as `pytest`, relevant configuration changes, and screenshots or logs only when UI, Telegram output, or operational behavior changes.

## Security & Configuration Tips

Copy `.env.example` to `.env` for local settings and never commit real credentials. Keep Gmail app passwords, API keys, Telegram tokens, and database URLs out of source files. When adding integrations, preserve fallback behavior so the agent can still classify locally when optional services are unavailable.
