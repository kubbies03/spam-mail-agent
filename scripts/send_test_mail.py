from __future__ import annotations

import argparse
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.config import get_settings


TEST_CASES: dict[str, dict[str, str]] = {
    "safe": {
        "subject": "Weekly project update",
        "body": (
            "Hello team,\n\n"
            "This is the weekly update for the current sprint.\n"
            "Please review the task progress, blockers, and timeline before tomorrow's meeting.\n\n"
            "Best regards,\n"
            "Project Coordinator\n"
        ),
    },
    "suspicious": {
        "subject": "Review your recent account activity",
        "body": (
            "Hello,\n\n"
            "We noticed recent activity on your account that may need your attention.\n"
            "Please review the details here:\n"
            "https://account-review-example.com/activity-check\n\n"
            "If this was not you, consider changing your password.\n\n"
            "Regards,\n"
            "Support Team\n"
        ),
    },
    "spam": {
        "subject": "Congratulations! You have won a free gift card",
        "body": (
            "Hello,\n\n"
            "You have been selected to receive a free gift card worth $500.\n"
            "Claim your reward now before it expires:\n"
            "https://reward-fastclaim.xyz/winner\n\n"
            "Do not miss this limited-time opportunity.\n\n"
            "Promotions Center\n"
        ),
    },
    "phishing": {
        "subject": "Final warning: verify your account immediately",
        "body": (
            "Attention,\n\n"
            "Your account has been flagged for suspicious activity and will be suspended within 24 hours.\n"
            "You must confirm your password immediately to restore access.\n\n"
            "Verify now:\n"
            "https://login-example.xyz/verify-account\n\n"
            "Failure to act now will result in permanent account suspension.\n\n"
            "Security and Billing Department\n"
        ),
    },
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send predefined test emails through Gmail SMTP.")
    parser.add_argument("--case", choices=sorted(TEST_CASES), required=True, help="Predefined test email to send.")
    parser.add_argument("--to", dest="to_email", help="Destination email. Defaults to GMAIL_USER from .env.")
    parser.add_argument("--from-name", default="Spam Mail Agent Test", help="Display name for the sender.")
    parser.add_argument("--subject", help="Override the predefined subject.")
    parser.add_argument("--body", help="Override the predefined body.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    settings = get_settings()

    if not settings.gmail_user or not settings.gmail_app_password:
        raise SystemExit("Missing GMAIL_USER or GMAIL_APP_PASSWORD in .env")

    to_email = args.to_email or settings.gmail_user
    template = TEST_CASES[args.case]
    subject = args.subject or template["subject"]
    body = args.body or template["body"]

    message = EmailMessage()
    message["From"] = f"{args.from_name} <{settings.gmail_user}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as client:
        client.login(settings.gmail_user, settings.gmail_app_password)
        client.send_message(message)

    print(f"Sent '{args.case}' test email to {to_email}")
    print(f"Subject: {subject}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
