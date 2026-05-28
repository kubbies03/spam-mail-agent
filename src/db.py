from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import JSON, Column, DateTime, Float, Integer, MetaData, String, Table, Text, create_engine, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.sql import func

from .config import get_settings
from .schemas import ProcessingResult


metadata = MetaData()

email_log = Table(
    "email_log",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("message_id", String(255), unique=True, nullable=False, index=True),
    Column("sender", String(512), nullable=False),
    Column("subject", Text, nullable=False),
    Column("route", String(64), nullable=False),
    Column("final_verdict", String(32), nullable=False),
    Column("risk_score", Float, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("classifier_risk_score", Float, nullable=False),
    Column("spam_probability", Float, nullable=False),
    Column("phishing_probability", Float, nullable=False),
    Column("classifier_label", String(32), nullable=False),
    Column("latency_ms", Integer, nullable=False),
    Column("payload", JSON().with_variant(Text, "sqlite"), nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

feedback_queue = Table(
    "feedback_queue",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("message_id", String(255), nullable=False, index=True),
    Column("feedback", String(64), nullable=False),
    Column("source", String(64), nullable=False, default="telegram"),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

telegram_callback_map = Table(
    "telegram_callback_map",
    metadata,
    Column("callback_id", String(64), primary_key=True),
    Column("message_id", String(255), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

retraining_queue = Table(
    "retraining_queue",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("message_id", String(255), nullable=False),
    Column("text", Text, nullable=False),
    Column("label", Integer, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

migrations = Table(
    "schema_migrations",
    metadata,
    Column("version", String(64), primary_key=True),
    Column("applied_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)


def get_engine(database_url: str | None = None) -> Engine:
    url = database_url or get_settings().database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, future=True, connect_args=connect_args)


def _resolve_engine(engine: Engine | None = None) -> Engine:
    return engine or get_engine()


def _engine_uses_sqlite(engine: Engine) -> bool:
    return engine.dialect.name == "sqlite"


def init_db(engine: Engine | None = None) -> None:
    engine = _resolve_engine(engine)
    if _engine_uses_sqlite(engine):
        db_path = Path(engine.url.database or "")
        if str(db_path) not in {"", ":memory:"}:
            db_path.parent.mkdir(parents=True, exist_ok=True)
    metadata.create_all(engine)
    with engine.begin() as conn:
        inspector = inspect(conn)
        existing_columns = {column["name"] for column in inspector.get_columns("email_log")}
        required_columns = {
            "classifier_risk_score": "FLOAT NOT NULL DEFAULT 0",
            "phishing_probability": "FLOAT NOT NULL DEFAULT 0",
            "classifier_label": "VARCHAR(32) NOT NULL DEFAULT 'safe'",
        }
        for column_name, column_type in required_columns.items():
            if column_name not in existing_columns:
                conn.execute(text(f"ALTER TABLE email_log ADD COLUMN {column_name} {column_type}"))
        exists = conn.execute(select(migrations.c.version).where(migrations.c.version == "001_initial")).first()
        if not exists:
            conn.execute(migrations.insert().values(version="001_initial"))
        multi_exists = conn.execute(select(migrations.c.version).where(migrations.c.version == "002_multiclass_classifier")).first()
        if not multi_exists:
            conn.execute(migrations.insert().values(version="002_multiclass_classifier"))


@contextmanager
def db_conn(engine: Engine | None = None) -> Iterator:
    engine = _resolve_engine(engine)
    with engine.begin() as conn:
        yield conn


def _json_payload(result: ProcessingResult, engine: Engine) -> str | dict:
    data = result.model_dump(mode="json")
    if _engine_uses_sqlite(engine):
        return json.dumps(data, ensure_ascii=False)
    return data


def save_result(result: ProcessingResult, engine: Engine | None = None) -> None:
    engine = _resolve_engine(engine)
    with db_conn(engine) as conn:
        existing = conn.execute(select(email_log.c.id).where(email_log.c.message_id == result.email.message_id)).first()
        if existing:
            return
        conn.execute(
            email_log.insert().values(
                message_id=result.email.message_id,
                sender=result.email.sender,
                subject=result.email.subject,
                route=result.route,
                final_verdict=result.final_verdict.value,
                risk_score=result.risk_score,
                confidence=result.classifier.confidence,
                classifier_risk_score=result.classifier.risk_score,
                spam_probability=result.classifier.spam_probability,
                phishing_probability=result.classifier.phishing_probability,
                classifier_label=result.classifier.verdict.value,
                latency_ms=result.latency_ms,
                payload=_json_payload(result, engine),
            )
        )


def is_processed(message_id: str, engine: Engine | None = None) -> bool:
    with db_conn(engine) as conn:
        return conn.execute(select(email_log.c.id).where(email_log.c.message_id == message_id)).first() is not None


def add_feedback(message_id: str, feedback: str, source: str = "telegram", engine: Engine | None = None) -> None:
    with db_conn(engine) as conn:
        conn.execute(feedback_queue.insert().values(message_id=message_id, feedback=feedback, source=source))


def save_telegram_callback(callback_id: str, message_id: str, engine: Engine | None = None) -> None:
    with db_conn(engine) as conn:
        conn.execute(
            telegram_callback_map.delete().where(telegram_callback_map.c.callback_id == callback_id)
        )
        conn.execute(
            telegram_callback_map.insert().values(
                callback_id=callback_id,
                message_id=message_id,
            )
        )


def resolve_telegram_callback(callback_id: str, engine: Engine | None = None) -> str | None:
    with db_conn(engine) as conn:
        row = conn.execute(
            select(telegram_callback_map.c.message_id).where(telegram_callback_map.c.callback_id == callback_id)
        ).first()
    return str(row.message_id) if row else None


def analytics(engine: Engine | None = None) -> dict[str, float | int]:
    with db_conn(engine) as conn:
        rows = conn.execute(select(email_log.c.route, email_log.c.final_verdict, email_log.c.confidence)).all()
    total = len(rows)
    spam = sum(1 for row in rows if row.final_verdict == "spam")
    agent = sum(1 for row in rows if row.route == "agent")
    avg_conf = sum(float(row.confidence) for row in rows) / total if total else 0.0
    return {
        "total": total,
        "spam_ratio": spam / total if total else 0.0,
        "agent_ratio": agent / total if total else 0.0,
        "avg_confidence": avg_conf,
    }
