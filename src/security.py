from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from functools import lru_cache
import time
from urllib.parse import urlparse

try:
    import httpx
except ImportError:  # pragma: no cover - optional dependency
    httpx = None

try:
    import tldextract
except ImportError:  # pragma: no cover - optional dependency
    tldextract = None

from .config import get_settings
from .schemas import SenderReport, URLReport

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s<>'\")]+", re.IGNORECASE)
SHORTENERS = {"bit.ly", "tinyurl.com", "t.co", "goo.gl", "is.gd", "ow.ly", "cutt.ly"}
BRAND_WORDS = {"paypal", "google", "microsoft", "apple", "amazon", "facebook", "telegram"}
_VIRUSTOTAL_DISABLED_UNTIL = 0.0


def extract_urls(text: str) -> list[str]:
    return list(dict.fromkeys(match.rstrip(".,;]") for match in URL_RE.findall(text or "")))


def domain_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.split("@")[-1].split(":")[0].lower()
    if tldextract is None:
        parts = [part for part in host.split(".") if part]
        return ".".join(parts[-2:]) if len(parts) >= 2 else host
    ext = tldextract.extract(host)
    return ".".join(part for part in [ext.domain, ext.suffix] if part)


def sender_domain(sender: str) -> str:
    match = re.search(r"@([A-Za-z0-9.-]+\.[A-Za-z]{2,})", sender)
    return match.group(1).lower() if match else ""


def suspicious_url_heuristics(url: str) -> tuple[float, list[str]]:
    score = 0.0
    signals: list[str] = []
    parsed = urlparse(url)
    host = parsed.netloc.split("@")[-1].split(":")[0].lower()
    domain = domain_from_url(url)
    suffix = ""
    if tldextract is not None:
        suffix = tldextract.extract(host).suffix
    else:
        parts = [part for part in host.split(".") if part]
        suffix = parts[-1] if parts else ""
    if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", host):
        score += 0.25
        signals.append("ip address host")
    if domain in SHORTENERS:
        score += 0.2
        signals.append("url shortener")
    if suffix in get_settings().suspicious_tlds:
        score += 0.2
        signals.append(f"suspicious tld .{suffix}")
    if host.count("-") >= 2:
        score += 0.15
        signals.append("hyphenated domain")
    if any(brand in host and domain.split(".")[0] != brand for brand in BRAND_WORDS):
        score += 0.25
        signals.append("brand impersonation pattern")
    if parsed.scheme != "https":
        score += 0.1
        signals.append("non-https link")
    return min(score, 1.0), signals


async def virustotal_url_report(url: str) -> tuple[int | None, int | None]:
    global _VIRUSTOTAL_DISABLED_UNTIL
    settings = get_settings()
    api_key = settings.virustotal_api_key
    if not api_key or httpx is None or not settings.virustotal_enabled:
        return None, None
    if time.time() < _VIRUSTOTAL_DISABLED_UNTIL:
        return None, None
    headers = {"x-apikey": api_key}
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            submit = await client.post("https://www.virustotal.com/api/v3/urls", data={"url": url}, headers=headers)
            submit.raise_for_status()
            analysis_id = submit.json()["data"]["id"]
            await asyncio.sleep(2)
            report = await client.get(f"https://www.virustotal.com/api/v3/analyses/{analysis_id}", headers=headers)
            report.raise_for_status()
            stats = report.json()["data"]["attributes"]["stats"]
            return int(stats.get("malicious", 0)), int(stats.get("suspicious", 0))
    except Exception as exc:
        if "429" in str(exc):
            _VIRUSTOTAL_DISABLED_UNTIL = time.time() + settings.virustotal_cooldown_seconds
        logger.warning("virustotal_failed url=%s error=%s", url, exc)
        return None, None


async def analyze_urls(text: str) -> list[URLReport]:
    reports: list[URLReport] = []
    urls = extract_urls(text)
    limit = get_settings().url_analysis_limit
    if len(urls) > limit:
        logger.info("url_analysis_truncated total=%s limit=%s", len(urls), limit)
    for url in urls[:limit]:
        score, signals = suspicious_url_heuristics(url)
        malicious, suspicious = await virustotal_url_report(url)
        if malicious:
            score = max(score, 0.9)
            signals.append(f"virustotal malicious={malicious}")
        if suspicious:
            score = max(score, 0.75)
            signals.append(f"virustotal suspicious={suspicious}")
        reports.append(
            URLReport(
                url=url,
                domain=domain_from_url(url),
                suspicious=score >= 0.35,
                score=score,
                signals=signals,
                vt_malicious=malicious,
                vt_suspicious=suspicious,
            )
        )
        if score >= get_settings().virustotal_decisive_threshold:
            logger.info("url_analysis_short_circuit url=%s score=%.2f", url, score)
            break
    return reports


@lru_cache(maxsize=1024)
def approximate_domain_age_days(domain: str) -> int | None:
    if not domain:
        return None
    try:
        import whois  # type: ignore

        record = whois.whois(domain)
        created = record.creation_date
        if isinstance(created, list):
            created = created[0]
        if not created:
            return None
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return max((datetime.now(timezone.utc) - created).days, 0)
    except Exception:
        return None


async def lookup_sender(sender: str) -> SenderReport:
    settings = get_settings()
    domain = sender_domain(sender)
    trusted = domain in settings.trusted_domains
    known_sender_domains = {item.strip().lower() for item in settings.known_sender_domains.split(",") if item.strip()}
    known_notification_domain = domain in known_sender_domains
    age_days = await asyncio.to_thread(approximate_domain_age_days, domain)
    signals: list[str] = []
    if not domain:
        signals.append("missing sender domain")
    if trusted:
        signals.append("trusted public mail domain")
    if known_notification_domain:
        signals.append("known notification sender domain")
    if age_days is not None and age_days < 30:
        signals.append("newly registered sender domain")
    unknown = not trusted and not known_notification_domain and age_days is None
    if unknown:
        signals.append("unknown sender domain age")
    return SenderReport(sender_domain=domain, trusted=(trusted or known_notification_domain), unknown=unknown, age_days=age_days, signals=signals)
