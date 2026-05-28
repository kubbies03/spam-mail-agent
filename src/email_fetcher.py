from __future__ import annotations

import email
import imaplib
import logging
import socket
from email.header import decode_header, make_header
from email.message import Message
from typing import Iterable

from .config import get_settings
from .schemas import AttachmentMeta, EmailMessage

logger = logging.getLogger(__name__)


def decode_mime(value: str | None) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _part_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw = part.get_payload()
        return raw if isinstance(raw, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def parse_email(raw_bytes: bytes) -> EmailMessage:
    msg = email.message_from_bytes(raw_bytes)
    message_id = msg.get("Message-ID") or msg.get("X-GM-MSGID") or str(abs(hash(raw_bytes)))
    bodies: list[str] = []
    attachments: list[AttachmentMeta] = []
    if msg.is_multipart():
        for part in msg.walk():
            content_disposition = (part.get("Content-Disposition") or "").lower()
            content_type = part.get_content_type()
            filename = decode_mime(part.get_filename())
            payload = part.get_payload(decode=True)
            if filename or "attachment" in content_disposition:
                attachments.append(
                    AttachmentMeta(
                        filename=filename or "unnamed",
                        content_type=content_type,
                        size_bytes=len(payload or b""),
                    )
                )
                continue
            if content_type in {"text/plain", "text/html"}:
                bodies.append(_part_payload(part))
    else:
        bodies.append(_part_payload(msg))
    return EmailMessage(
        message_id=message_id.strip("<>"),
        sender=decode_mime(msg.get("From")),
        subject=decode_mime(msg.get("Subject")),
        body="\n".join(body for body in bodies if body).strip(),
        attachments=attachments,
        raw_headers={key: decode_mime(value) for key, value in msg.items()},
    )


class GmailIMAPFetcher:
    def __init__(self) -> None:
        self.settings = get_settings()

    def _mailboxes(self) -> list[str]:
        folders = [folder.strip() for folder in self.settings.gmail_folders.split(",")]
        return [folder for folder in folders if folder]

    def fetch_unseen(self, limit: int = 25) -> list[EmailMessage]:
        if not self.settings.gmail_user or not self.settings.gmail_app_password:
            logger.warning("gmail_credentials_missing")
            return []
        emails: list[EmailMessage] = []
        seen_ids: set[str] = set()
        try:
            with imaplib.IMAP4_SSL(self.settings.gmail_imap_host, self.settings.gmail_imap_port) as client:
                client.login(self.settings.gmail_user, self.settings.gmail_app_password)
                for mailbox in self._mailboxes():
                    status, _data = client.select(f'"{mailbox}"')
                    if status != "OK":
                        logger.warning("imap_select_failed mailbox=%s status=%s", mailbox, status)
                        continue
                    status, data = client.uid("SEARCH", None, "UNSEEN")
                    if status != "OK":
                        logger.warning("imap_search_failed mailbox=%s status=%s", mailbox, status)
                        continue
                    remaining = max(limit - len(emails), 0)
                    if remaining == 0:
                        break
                    ids = data[0].split()[:remaining]
                    for uid in ids:
                        try:
                            status, payload = client.uid("FETCH", uid, "(RFC822)")
                            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                                logger.warning("imap_fetch_failed mailbox=%s uid=%s status=%s", mailbox, uid, status)
                                continue
                            email_message = parse_email(payload[0][1])
                            email_message.source_mailbox = mailbox
                            email_message.source_uid = uid.decode() if isinstance(uid, bytes) else str(uid)
                            if email_message.message_id in seen_ids:
                                continue
                            seen_ids.add(email_message.message_id)
                            emails.append(email_message)
                            if len(emails) >= limit:
                                break
                        except Exception as exc:
                            logger.exception("email_parse_failed mailbox=%s uid=%s error=%s", mailbox, uid, exc)
                    if len(emails) >= limit:
                        break
        except (imaplib.IMAP4.error, OSError, socket.error) as exc:
            logger.warning("gmail_fetch_failed host=%s port=%s error=%s", self.settings.gmail_imap_host, self.settings.gmail_imap_port, exc)
            return []
        return emails

    def mark_seen(self, email: EmailMessage) -> None:
        if not self.settings.gmail_user or not self.settings.gmail_app_password:
            return
        if not email.source_mailbox or not email.source_uid:
            return
        try:
            with imaplib.IMAP4_SSL(self.settings.gmail_imap_host, self.settings.gmail_imap_port) as client:
                client.login(self.settings.gmail_user, self.settings.gmail_app_password)
                status, _data = client.select(f'"{email.source_mailbox}"')
                if status != "OK":
                    logger.warning("imap_select_failed mailbox=%s status=%s", email.source_mailbox, status)
                    return
                status, _data = client.uid("STORE", email.source_uid, "+FLAGS", "(\\Seen)")
                if status != "OK":
                    logger.warning("imap_mark_seen_failed mailbox=%s uid=%s status=%s", email.source_mailbox, email.source_uid, status)
        except (imaplib.IMAP4.error, OSError, socket.error) as exc:
            logger.warning("gmail_mark_seen_failed mailbox=%s uid=%s error=%s", email.source_mailbox, email.source_uid, exc)


def parse_many(raw_messages: Iterable[bytes]) -> list[EmailMessage]:
    return [parse_email(raw) for raw in raw_messages]
