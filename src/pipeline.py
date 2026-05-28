from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Awaitable, Callable
from pathlib import Path

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
except ImportError:  # pragma: no cover - optional dependency
    AsyncIOScheduler = None

from .agent import SpamAgent
from .config import get_settings
from .db import init_db, is_processed, save_result
from .email_fetcher import GmailIMAPFetcher
from .logging_config import configure_logging
from .monitoring import latency_timer, metrics
from .schemas import EmailMessage, ProcessingResult
from .telegram_bot import send_alert
from .router import HybridRouter, should_send_alert

logger = logging.getLogger(__name__)


class SpamEmailPipeline:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.fetcher = GmailIMAPFetcher()
        self.router = HybridRouter()
        self.agent = SpamAgent()
        self.semaphore = asyncio.Semaphore(self.settings.max_concurrency)
        self.inflight: set[str] = set()

    async def process_email(self, email: EmailMessage) -> ProcessingResult | None:
        logger.info(
            "process_email_started message_id=%s mailbox=%s uid=%s subject=%r",
            email.message_id,
            email.source_mailbox,
            email.source_uid,
            email.subject[:160],
        )
        if is_processed(email.message_id) or email.message_id in self.inflight:
            logger.info("duplicate_skipped message_id=%s", email.message_id)
            await asyncio.to_thread(self.fetcher.mark_seen, email)
            logger.info(
                "mark_seen_after_duplicate message_id=%s mailbox=%s uid=%s",
                email.message_id,
                email.source_mailbox,
                email.source_uid,
            )
            return None
        async with self.semaphore:
            self.inflight.add(email.message_id)
            try:
                with latency_timer() as elapsed:
                    escalate, context = await self.router.should_escalate(email)
                    if escalate:
                        result = await self.agent.run(email, latency_ms=elapsed())
                    else:
                        result = await self.router.fast_path(email, context, latency_ms=elapsed())
                    result.latency_ms = elapsed()
                save_result(result)
                await asyncio.to_thread(self.fetcher.mark_seen, email)
                logger.info(
                    "process_email_completed message_id=%s verdict=%s route=%s risk=%.2f mailbox=%s uid=%s",
                    email.message_id,
                    result.final_verdict.value,
                    result.route,
                    result.risk_score,
                    email.source_mailbox,
                    email.source_uid,
                )
                metrics.record(result.route, result.final_verdict.value, result.classifier.confidence, result.latency_ms)
                if should_send_alert(result):
                    await send_alert(result)
                    logger.info("telegram_alert_requested message_id=%s verdict=%s", email.message_id, result.final_verdict.value)
                return result
            except Exception as exc:
                logger.exception("process_email_failed message_id=%s error=%s", email.message_id, exc)
                return None
            finally:
                self.inflight.discard(email.message_id)

    async def poll_once(self, limit: int = 25) -> list[ProcessingResult]:
        logger.info("poll_started limit=%s inflight=%s", limit, len(self.inflight))
        try:
            emails = await asyncio.to_thread(self.fetcher.fetch_unseen, limit)
        except Exception as exc:
            logger.warning("poll_fetch_failed error=%s", exc)
            return []
        logger.info("poll_fetched count=%s", len(emails))
        for email in emails:
            logger.info(
                "poll_email_found message_id=%s mailbox=%s uid=%s subject=%r",
                email.message_id,
                email.source_mailbox,
                email.source_uid,
                email.subject[:160],
            )
        if not emails:
            logger.info("poll_no_emails metrics=%s", metrics.snapshot())
            return []
        tasks = [self.process_email(email) for email in emails]
        results = await asyncio.gather(*tasks)
        completed = [result for result in results if result is not None]
        logger.info("poll_completed processed=%s", len(completed))
        return completed

    async def run_forever(self) -> None:
        init_db()
        if AsyncIOScheduler is None:
            raise RuntimeError("APScheduler is unavailable. Install project dependencies to use run mode.")
        pid_path = Path(self.settings.log_dir) / "system.pid"
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        scheduler = AsyncIOScheduler()
        scheduler.add_job(self.poll_once, "interval", seconds=self.settings.poll_interval_seconds, max_instances=1)
        scheduler.start()
        logger.info("pipeline_started pid=%s interval_seconds=%s", os.getpid(), self.settings.poll_interval_seconds)
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                pass
        try:
            await self.poll_once()
            await stop.wait()
        finally:
            scheduler.shutdown(wait=False)
            try:
                if pid_path.exists():
                    pid_path.unlink()
            except OSError:
                logger.warning("pid_cleanup_failed path=%s", pid_path)
            logger.info("pipeline_stopped pid=%s metrics=%s", os.getpid(), metrics.snapshot())


async def run_with_retry(fn: Callable[[], Awaitable[object]], retries: int = 3) -> object:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            return await fn()
        except Exception as exc:
            last_error = exc
            logger.warning("retryable_operation_failed attempt=%s error=%s", attempt + 1, exc)
            await asyncio.sleep(2**attempt)
    raise RuntimeError("operation failed after retries") from last_error


def start() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    asyncio.run(SpamEmailPipeline().run_forever())
