# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env   # then fill in credentials

# Run
python main.py run                          # continuous polling (production)
python main.py poll-once [--limit 25]       # single batch
python main.py classify-text --text "..."   # classify a string
python main.py classify-raw --path file.eml # parse & classify an .eml file
python main.py self-test                    # smoke test with 2 sample emails
python main.py analytics                    # print DB stats

# Tests
pytest                                      # all tests
pytest tests/test_classifier.py            # single file
pytest -k "test_name"                      # single test

# Training
python scripts/train_distilbert.py --csv data/spam_dataset.csv --epochs 2 --batch-size 8
python scripts/train.py                     # SVM/TF-IDF fallback model
python scripts/export_onnx.py              # optional ONNX export

# Docker
docker compose up --build -d
docker compose --profile postgres up --build -d   # with Postgres
```

## Architecture

The system is a hybrid email spam detector that routes each email through either a fast ML path or an agentic reasoning path.

```
Gmail IMAP → Email Parser → Duplicate Guard → Classifier (DistilBERT)
                                                     ↓
                                           HybridRouter.should_escalate()
                                              ↙                 ↘
                                        FAST PATH          AGENT PATH
                                   (high-confidence)    (LangGraph fallback)
                                              ↘                 ↙
                                         Security checks (URL + sender)
                                         Gemini explanation (+ Redis cache)
                                                     ↓
                                         SQLite/Postgres + Telegram alert
```

### Key modules (`src/`)

- **`pipeline.py`** — Top-level orchestrator. Fetches emails, runs the router, saves results, sends alerts. `run_forever()` uses APScheduler; `poll_once()` for single batch. Async concurrency controlled by semaphore.
- **`router.py`** — `HybridRouter` decides fast vs agent path. Escalates if: low classifier confidence, suspicious URLs, unknown sender, high phishing/spam probability, or 3+ keyword signals.
- **`classifier.py`** — Primary: `DistilBertMultilingualClassifier` (3-class: safe/phishing/spam, loaded from `models/distilbert_multilingual/`). Fallback: `SpamClassifier` (SVM+TF-IDF, `models/svm_tfidf.joblib`). Falls back automatically if model files are missing.
- **`agent.py`** — LangGraph `StateGraph` with tools: `classify_email`, `check_urls_in_email`, `lookup_sender_tool`. Currently uses a fallback graph (not full LangGraph integration).
- **`security.py`** — URL risk heuristics + async VirusTotal lookup (429 → 15-min cooldown, max 8 URLs/email). Sender domain lookup against known trusted domains.
- **`explainer.py`** — Gemini Flash-Lite for natural language explanation (EN + Vietnamese). Redis cache by SHA256 hash (24h TTL). 429 → 15-min cooldown. Deterministic fallback always available.
- **`db.py`** — SQLAlchemy 2.0 ORM. `email_log` is append-only (unique on `message_id`). `feedback_queue` holds Telegram corrections. Auto-migrates schema on startup.
- **`config.py`** — Pydantic `BaseSettings` from `.env`. All external integrations (Gmail, Telegram, Gemini, VirusTotal, Redis) are optional with graceful degradation.
- **`schemas.py`** — Pydantic contracts: `EmailMessage`, `ClassifierResult`, `URLReport`, `SenderReport`, `SpamExplanation`, `ProcessingResult`, `Verdict` enum.
- **`telegram_bot.py`** — Sends formatted alerts with feedback buttons ("Confirm spam" / "Mark safe"). Callbacks stored in `telegram_callback_map`; feedback saved to `feedback_queue`.
- **`monitoring.py`** — In-memory metrics (counts, latencies, confidence histogram) via a latency context manager.

### Routing thresholds (configurable via `.env`)

| Variable | Default | Effect |
|---|---|---|
| `CLASSIFIER_THRESHOLD` | 0.82 | Confidence needed to stay on fast path |
| `PHISHING_ESCALATION_THRESHOLD` | 0.50 | Phishing prob above this → escalate |
| `SPAM_ESCALATION_THRESHOLD` | 0.65 | Spam prob above this → escalate |

### Models

- `models/distilbert_multilingual/` — Primary fine-tuned DistilBERT (3-class). Falls back to `docs/22590/` if missing.
- `models/svm_tfidf.joblib` — Fallback SVM model (2-class: safe/spam).

### Database

SQLite by default (`data/spam_agent.db`). Switch to Postgres with `DATABASE_URL=postgresql+psycopg://...`. Schema migrations run automatically on startup and are tracked in `schema_migrations`.

### Testing conventions

Mock all external services (Gmail, Telegram, Gemini, VirusTotal, Redis) in tests. Tests live in `tests/` and use `pytest-asyncio` for async cases.
