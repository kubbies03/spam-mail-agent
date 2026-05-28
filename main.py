from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

from src.config import get_settings
from src.db import analytics, init_db
from src.email_fetcher import parse_email
from src.logging_config import configure_logging
from src.pipeline import SpamEmailPipeline
from src.schemas import EmailMessage


def print_json(value: object) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2)
    try:
        sys.stdout.buffer.write((text + "\n").encode("utf-8"))
    except Exception:
        print(text)


async def classify_sample(text: str) -> None:
    pipeline = SpamEmailPipeline()
    email = EmailMessage(message_id=f"sample-{abs(hash(text))}", sender="sample@gmail.com", subject="Local sample", body=text)
    result = await pipeline.process_email(email)
    print_json(result.model_dump(mode="json") if result else {})


async def classify_raw(path: str) -> None:
    pipeline = SpamEmailPipeline()
    raw = open(path, "rb").read()
    result = await pipeline.process_email(parse_email(raw))
    print_json(result.model_dump(mode="json") if result else {})


async def self_test() -> None:
    pipeline = SpamEmailPipeline()
    run_id = uuid.uuid4().hex[:8]
    samples = [
        EmailMessage(
            message_id=f"selftest-safe-{run_id}",
            sender="teammate@gmail.com",
            subject="Sprint planning notes",
            body="Please review the agenda for tomorrow morning standup.",
        ),
        EmailMessage(
            message_id=f"selftest-risky-{run_id}",
            sender="alerts@billing-secure.xyz",
            subject="Urgent verify account",
            body="Urgent: verify your password now at https://login-example.xyz to avoid suspension.",
        ),
    ]
    results = []
    for email in samples:
        result = await pipeline.process_email(email)
        if result is not None:
            results.append(result.model_dump(mode="json"))
    print_json({"results": results, "analytics": analytics()})


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    init_db()
    parser = argparse.ArgumentParser(description="Spam Email Agent")
    parser.add_argument("command", choices=["run", "poll-once", "classify-text", "classify-raw", "analytics", "self-test"])
    parser.add_argument("--text", default="")
    parser.add_argument("--path", default="")
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    if args.command == "run":
        asyncio.run(SpamEmailPipeline().run_forever())
    elif args.command == "poll-once":
        results = asyncio.run(SpamEmailPipeline().poll_once(limit=args.limit))
        print_json([r.model_dump(mode="json") for r in results])
    elif args.command == "classify-text":
        asyncio.run(classify_sample(args.text))
    elif args.command == "classify-raw":
        asyncio.run(classify_raw(args.path))
    elif args.command == "analytics":
        print_json(analytics())
    elif args.command == "self-test":
        asyncio.run(self_test())


if __name__ == "__main__":
    main()
