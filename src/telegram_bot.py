from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import timedelta, timezone

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.constants import ParseMode
    from telegram.ext import Application, CallbackQueryHandler, ContextTypes
except ImportError:  # pragma: no cover - optional dependency
    Application = None
    CallbackQueryHandler = None
    ContextTypes = None
    InlineKeyboardButton = None
    InlineKeyboardMarkup = None
    ParseMode = None
    Update = object

from .config import get_settings
from .db import add_feedback, resolve_telegram_callback, save_telegram_callback
from .schemas import ProcessingResult

logger = logging.getLogger(__name__)
VIETNAM_TZ = timezone(timedelta(hours=7))


def telegram_enabled() -> bool:
    settings = get_settings()
    return bool(settings.telegram_bot_token and settings.telegram_chat_id and Application is not None)


def format_alert(result: ProcessingResult) -> str:
    signals = result.explanation.spam_signals if result.explanation else result.classifier.signals
    summary = result.explanation.summary if result.explanation else "No LLM explanation available."
    processed_at = result.created_at.astimezone(VIETNAM_TZ).strftime("%Y-%m-%d %H:%M:%S GMT+7")
    signal_text = ", ".join(signals[:5]) if signals else "no notable signals"
    url_text = ", ".join(f"{report.domain}({report.score:.2f})" for report in result.url_reports[:3]) if result.url_reports else "no urls"
    return (
        f"[{processed_at}]\n"
        f"Alert\n"
        f"Subject: {result.email.subject[:160] or '(no subject)'}\n"
        f"Verdict: {result.final_verdict.value.upper()}\n"
        f"Risk: {result.risk_score:.2f}\n"
        f"From: {result.email.sender}\n"
        f"Reason/Description: {summary}\n"
        f"Signals: {signal_text}\n"
        f"URLs: {url_text}"
    )


async def send_alert(result: ProcessingResult) -> None:
    if not telegram_enabled():
        logger.info("telegram_disabled message_id=%s", result.email.message_id)
        return
    settings = get_settings()
    app = Application.builder().token(settings.telegram_bot_token).build()
    spam_callback = secrets.token_urlsafe(8)
    safe_callback = secrets.token_urlsafe(8)
    save_telegram_callback(spam_callback, result.email.message_id)
    save_telegram_callback(safe_callback, result.email.message_id)
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Confirm spam", callback_data=f"spam:{spam_callback}"),
                InlineKeyboardButton("Mark safe", callback_data=f"safe:{safe_callback}"),
            ]
        ]
    )
    for attempt in range(3):
        try:
            async with app:
                await app.bot.send_message(
                    chat_id=settings.telegram_chat_id,
                    text=format_alert(result),
                    reply_markup=keyboard,
                    disable_web_page_preview=True,
                )
            return
        except Exception as exc:
            logger.warning("telegram_send_failed attempt=%s error=%s", attempt + 1, exc)
            await asyncio.sleep(2**attempt)


async def feedback_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    query = update.callback_query
    if not query or not query.data:
        return
    action, callback_id = query.data.split(":", 1)
    message_id = resolve_telegram_callback(callback_id)
    if not message_id:
        await query.answer("Feedback target not found.")
        return
    add_feedback(message_id=message_id, feedback=action)
    await query.answer(f"Recorded: {action}")


def build_feedback_app() -> Application | None:
    settings = get_settings()
    if not settings.telegram_bot_token or Application is None or CallbackQueryHandler is None:
        return None
    app = Application.builder().token(settings.telegram_bot_token).build()
    app.add_handler(CallbackQueryHandler(feedback_callback))
    return app
