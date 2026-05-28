# Spam Email Agent

Production-grade spam/phishing detection system with a hybrid ML + agentic architecture. Routes each email through a fast DistilBERT classifier or a LangGraph reasoning agent depending on confidence and risk signals.

## Architecture

```
Gmail IMAP (UNSEEN)
        |
        v
Email Parser → Duplicate Guard → DistilBERT Classifier (safe / phishing / spam)
                                          |
                                          v
                                   HybridRouter.should_escalate()
                                    /                      \
                              FAST PATH               AGENT PATH (LangGraph)
                         (high confidence)      classify → check_security → finalize
                                    \                      /
                              URL heuristics + VirusTotal + sender domain lookup
                                          |
                                          v
                             Gemini Flash-Lite explanation + Redis cache
                                          |
                                          v
                         SQLite / Postgres log + Telegram alert + metrics
```

### Routing logic

| Condition | Effect |
|---|---|
| Classifier confidence < `CLASSIFIER_THRESHOLD` (0.82) | → Agent path |
| Any suspicious URL detected | → Agent path |
| Unknown sender domain | → Agent path |
| Phishing prob ≥ `PHISHING_ESCALATION_THRESHOLD` (0.50) | → Agent path |
| Spam prob ≥ `SPAM_ESCALATION_THRESHOLD` (0.65) | → Agent path |
| ≥ 3 keyword risk signals | → Agent path |
| Otherwise | → Fast path |

### LangGraph agent nodes

```
classify → check_security → finalize
```

- **classify**: DistilBERT 3-class prediction (safe / phishing / spam)
- **check_security**: URL heuristics + VirusTotal + WHOIS sender age
- **finalize**: risk aggregation, verdict determination, structured state output

Falls back to sequential execution if LangGraph is unavailable.

## Project Structure

```
spam-mail-agent/
├── src/
│   ├── pipeline.py       # Top-level orchestrator (APScheduler + semaphore)
│   ├── router.py         # HybridRouter: escalation logic + fast path
│   ├── agent.py          # LangGraph StateGraph agent
│   ├── classifier.py     # DistilBERT (primary) + SVM/TF-IDF (fallback)
│   ├── security.py       # URL heuristics, VirusTotal, sender domain lookup
│   ├── explainer.py      # Gemini Flash-Lite explanation + Redis cache
│   ├── db.py             # SQLAlchemy 2.0 ORM, auto-migrate
│   ├── schemas.py        # Pydantic contracts (EmailMessage, ProcessingResult…)
│   ├── email_fetcher.py  # Gmail IMAP fetcher + RFC822 parser
│   ├── telegram_bot.py   # Alerts + feedback buttons
│   ├── config.py         # Pydantic Settings from .env
│   └── monitoring.py     # In-memory metrics + latency timer
├── tests/                # pytest suite (49 tests)
├── scripts/              # Training and export scripts
├── models/               # distilbert_multilingual/ + svm_tfidf.joblib
├── data/                 # spam_dataset.csv + spam_agent.db
├── logs/
├── .env.example
├── main.py
├── requirements.txt
├── Dockerfile
└── docker-compose.yml
```

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux / macOS

pip install -r requirements.txt
copy .env.example .env          # then fill in credentials
```

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `GMAIL_USER` | — | Gmail address |
| `GMAIL_APP_PASSWORD` | — | Gmail app password (not account password) |
| `GMAIL_FOLDERS` | `INBOX,[Gmail]/Spam` | Mailboxes to poll |
| `POLL_INTERVAL_SECONDS` | `60` | Polling interval in production mode |
| `DATABASE_URL` | `sqlite:///data/spam_agent.db` | SQLite or Postgres connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis for LLM explanation cache |
| `TELEGRAM_BOT_TOKEN` | — | Telegram bot token for alerts |
| `TELEGRAM_CHAT_ID` | — | Telegram chat ID for alerts |
| `GOOGLE_API_KEY` | — | Gemini API key |
| `GEMINI_MODEL` | `gemini-2.5-flash-lite` | Gemini model name |
| `VIRUSTOTAL_API_KEY` | — | VirusTotal URL reputation |
| `CLASSIFIER_THRESHOLD` | `0.82` | Min confidence to stay on fast path |
| `PHISHING_ESCALATION_THRESHOLD` | `0.50` | Phishing prob to trigger agent path |
| `SPAM_ESCALATION_THRESHOLD` | `0.65` | Spam prob to trigger agent path |
| `DISTILBERT_MODEL_DIR` | `models/distilbert_multilingual` | Fine-tuned model path |

All integrations (Gemini, VirusTotal, Telegram, Redis) are optional — the system degrades gracefully with fallback heuristics when credentials are missing.

## Commands

```bash
# Single-shot classification
python main.py classify-text --text "urgent verify password at http://paypal-login.xyz"
python main.py classify-raw --path data/sample.eml

# Gmail polling
python main.py poll-once [--limit 25]   # one batch
python main.py run                       # continuous (production)

# Utilities
python main.py self-test                 # smoke test with 2 sample emails
python main.py analytics                 # print DB stats

# Tests
pytest                                   # all 49 tests
pytest tests/test_classifier.py         # single file
pytest -k "test_name"                   # single test
```

## Training

Fine-tune the DistilBERT classifier:

```bash
python scripts/train_distilbert.py --csv data/spam_dataset.csv --epochs 2 --batch-size 8
```

Fallback SVM + TF-IDF model:

```bash
python scripts/train.py --csv data/spam_dataset.csv --text-col text --label-col label
```

Optional ONNX export:

```bash
python scripts/export_onnx.py --model-dir models/distilbert_multilingual
```

## Docker Deployment

```bash
copy .env.example .env
docker compose up --build -d

# With Postgres
docker compose --profile postgres up --build -d
```

Set `DATABASE_URL=postgresql+psycopg://spam_agent:spam_agent_password@postgres:5432/spam_agent` when using Postgres.

## Models

| Model | Path | Notes |
|---|---|---|
| DistilBERT (primary) | `models/distilbert_multilingual/` | Fine-tuned 3-class (safe/phishing/spam) |
| DistilBERT (legacy) | `docs/22590/` | Fallback if primary missing |
| SVM + TF-IDF | `models/svm_tfidf.joblib` | 2-class, used when DistilBERT unavailable |

## Database

| Table | Purpose |
|---|---|
| `email_log` | Append-only processing results (unique on `message_id`) |
| `feedback_queue` | Telegram feedback ("Confirm spam" / "Mark safe") |
| `telegram_callback_map` | Maps callback IDs to message IDs |
| `retraining_queue` | Corrected examples for future retraining |
| `schema_migrations` | Migration version tracking |

Schema migrations run automatically on startup.

## Security

- **Prompt injection protection**: Gemini receives email content as labelled opaque data under `system_instruction` separation. Raw headers and full body are never placed in instruction position; content is truncated (subject ≤ 512 chars, body ≤ 1 000 chars).
- **URL analysis**: IP-host detection, shortener detection, TLD blocklist, brand impersonation pattern, non-HTTPS flag, VirusTotal lookup (max 8 URLs/email, 429 → 15-min cooldown).
- **Sender analysis**: Trusted domain whitelist, known notification sender list, WHOIS domain age check.

## Monitoring

In-memory metrics tracked per run:

- processing count by route (fast / agent)
- verdict distribution
- confidence histogram
- per-email latency (ms)

Use `python main.py analytics` for persisted aggregate stats from the database.

## Troubleshooting

| Symptom | Action |
|---|---|
| Gmail returns no emails | Verify IMAP is enabled in Gmail settings and app password is correct; messages must be unread |
| Redis unavailable | App continues with warning logs; LLM explanations are not cached |
| Gemini unavailable or rate-limited | Deterministic fallback explanation runs; 15-min cooldown after 429 |
| VirusTotal rate-limited | URL heuristics still run; 15-min cooldown after 429 |
| DistilBERT slow on CPU | Reduce batch size during training or use GPU; inference also benefits from GPU |
| Telegram MarkdownV2 errors | Special characters in subject/sender need escaping for strict Telegram Markdown mode |
