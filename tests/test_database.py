from sqlalchemy import create_engine, select

from src.db import analytics, email_log, init_db, is_processed, save_result
from src.schemas import ClassifierResult, EmailMessage, ProcessingResult, Verdict


def test_database_save_and_query() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    init_db(engine)
    email = EmailMessage(message_id="db1", sender="a@example.com", subject="s", body="b")
    result = ProcessingResult(
        email=email,
        route="fast",
        classifier=ClassifierResult(
            verdict=Verdict.safe,
            confidence=0.9,
            class_probabilities={"safe": 0.9, "phishing": 0.02, "spam": 0.08},
            risk_score=0.08,
            model_name="test",
        ),
        final_verdict=Verdict.safe,
        risk_score=0.1,
    )
    save_result(result, engine)
    save_result(result, engine)

    with engine.begin() as conn:
        row = conn.execute(select(email_log.c.payload).where(email_log.c.message_id == "db1")).first()

    assert is_processed("db1", engine)
    assert analytics(engine)["total"] == 1
    assert isinstance(row.payload, str)
