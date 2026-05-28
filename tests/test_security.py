from __future__ import annotations

import pytest

from src.schemas import EmailMessage
from src.security import (
    analyze_urls,
    domain_from_url,
    extract_urls,
    lookup_sender,
    sender_domain,
    suspicious_url_heuristics,
)


# --- extract_urls ---

def test_extract_urls_deduplicates():
    text = "Visit https://example.com and also https://example.com again"
    urls = extract_urls(text)
    assert urls == ["https://example.com"]


def test_extract_urls_strips_trailing_punctuation():
    text = "See https://example.com."
    urls = extract_urls(text)
    assert urls == ["https://example.com"]


def test_extract_urls_empty():
    assert extract_urls("") == []
    assert extract_urls("no links here") == []


# --- domain_from_url ---

def test_domain_from_url_basic():
    assert domain_from_url("https://login.paypal.com/verify") == "paypal.com"


def test_domain_from_url_ip():
    assert domain_from_url("http://192.168.1.1/phish") == "192.168.1.1"


# --- sender_domain ---

def test_sender_domain_extracts_correctly():
    assert sender_domain("John Doe <john@example.com>") == "example.com"
    assert sender_domain("spam@sub.domain.org") == "sub.domain.org"


def test_sender_domain_missing():
    assert sender_domain("no-at-sign") == ""


# --- suspicious_url_heuristics ---

def test_heuristic_ip_host():
    score, signals = suspicious_url_heuristics("http://192.168.1.1/login")
    assert score >= 0.25
    assert "ip address host" in signals


def test_heuristic_shortener():
    score, signals = suspicious_url_heuristics("https://bit.ly/abc123")
    assert "url shortener" in signals


def test_heuristic_brand_impersonation():
    score, signals = suspicious_url_heuristics("https://paypal-secure-login.xyz/verify")
    assert "brand impersonation pattern" in signals


def test_heuristic_non_https():
    score, signals = suspicious_url_heuristics("http://example.com/page")
    assert "non-https link" in signals


def test_heuristic_score_capped_at_one():
    # A URL that triggers multiple signals should not exceed 1.0
    score, _ = suspicious_url_heuristics("http://192.168.1.1-paypal.xyz/verify")
    assert score <= 1.0


def test_heuristic_clean_https_url():
    score, signals = suspicious_url_heuristics("https://github.com/user/repo")
    assert score < 0.35
    assert signals == []


# --- analyze_urls (async, VirusTotal disabled) ---

@pytest.mark.asyncio
async def test_analyze_urls_marks_suspicious(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.security.virustotal_url_report", lambda _url: _awaitable((None, None)))
    reports = await analyze_urls("Click here http://192.168.0.1/steal now")
    assert len(reports) == 1
    assert reports[0].suspicious is True
    assert reports[0].score >= 0.25


@pytest.mark.asyncio
async def test_analyze_urls_clean(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.security.virustotal_url_report", lambda _url: _awaitable((None, None)))
    reports = await analyze_urls("Visit https://github.com for details")
    assert len(reports) == 1
    assert reports[0].suspicious is False


@pytest.mark.asyncio
async def test_analyze_urls_virustotal_malicious_boosts_score(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.security.virustotal_url_report", lambda _url: _awaitable((3, 0)))
    reports = await analyze_urls("http://evil.xyz/phish")
    assert reports[0].score >= 0.9
    assert reports[0].vt_malicious == 3


@pytest.mark.asyncio
async def test_analyze_urls_respects_limit(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.security.virustotal_url_report", lambda _url: _awaitable((None, None)))
    many_urls = " ".join(f"https://example{i}.com" for i in range(20))
    reports = await analyze_urls(many_urls)
    from src.config import get_settings
    assert len(reports) <= get_settings().url_analysis_limit


# --- lookup_sender ---

@pytest.mark.asyncio
async def test_lookup_sender_trusted_domain(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.security.approximate_domain_age_days", lambda _d: 3650)
    report = await lookup_sender("user@gmail.com")
    assert report.trusted is True
    assert report.unknown is False
    assert "trusted public mail domain" in report.signals


@pytest.mark.asyncio
async def test_lookup_sender_known_notification_domain(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.security.approximate_domain_age_days", lambda _d: 1000)
    report = await lookup_sender("notify@facebookmail.com")
    assert report.trusted is True
    assert "known notification sender domain" in report.signals


@pytest.mark.asyncio
async def test_lookup_sender_unknown_new_domain(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.security.approximate_domain_age_days", lambda _d: 5)
    report = await lookup_sender("attacker@newdomain-xyz.click")
    assert "newly registered sender domain" in report.signals


@pytest.mark.asyncio
async def test_lookup_sender_missing_domain(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("src.security.approximate_domain_age_days", lambda _d: None)
    report = await lookup_sender("no-at-sign")
    assert "missing sender domain" in report.signals


async def _awaitable(value):
    return value
