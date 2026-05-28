from email.message import EmailMessage as RawEmail

from src.email_fetcher import parse_email


def test_parse_multipart_email_with_attachment() -> None:
    msg = RawEmail()
    msg["From"] = "Alice <alice@example.com>"
    msg["To"] = "Bob <bob@example.com>"
    msg["Subject"] = "Invoice"
    msg["Message-ID"] = "<abc@example.com>"
    msg.set_content("hello body")
    msg.add_attachment(b"pdf-bytes", maintype="application", subtype="pdf", filename="invoice.pdf")
    parsed = parse_email(msg.as_bytes())
    assert parsed.message_id == "abc@example.com"
    assert parsed.sender == "Alice <alice@example.com>"
    assert "hello body" in parsed.body
    assert parsed.attachments[0].filename == "invoice.pdf"
