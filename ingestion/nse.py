"""
NSE corporate announcements fetcher.
NSE requires a session cookie — hit the main page first, then the API.
"""
import time
import hashlib
import requests
from datetime import datetime

CONCALL_DESC = "Analysts/Institutional Investor Meet/Con. Call Updates"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}

_session = None
_session_refreshed = 0
SESSION_TTL = 300  # re-init session every 5 minutes


def _get_session():
    global _session, _session_refreshed
    now = time.time()
    if _session is None or (now - _session_refreshed) > SESSION_TTL:
        s = requests.Session()
        s.headers.update(HEADERS)
        s.get("https://www.nseindia.com", timeout=20)
        _session = s
        _session_refreshed = now
    return _session


def fetch_concall_announcements() -> list[dict]:
    """Return filings with concall transcripts from NSE."""
    session = _get_session()
    try:
        resp = session.get(
            "https://www.nseindia.com/api/corporate-announcements",
            params={"index": "equities"},
            timeout=20,
        )
        resp.raise_for_status()
        announcements = resp.json()
    except Exception as e:
        print(f"[NSE] fetch error: {e}")
        return []

    results = []
    for item in announcements:
        if item.get("desc") != CONCALL_DESC:
            continue
        pdf_url = item.get("attchmntFile")
        if not pdf_url or not pdf_url.endswith(".pdf"):
            continue

        company = item.get("sm_name", "Unknown")
        symbol = item.get("symbol") or item.get("sm_isin", "")[:10]
        isin = item.get("sm_isin", "")
        filed_at = item.get("an_dt", "")

        # Stable ID: hash of pdf_url so same filing from both exchanges matches
        filing_id = hashlib.sha1(pdf_url.encode()).hexdigest()[:16]

        results.append({
            "id": filing_id,
            "exchange": "NSE",
            "symbol": symbol,
            "company": company,
            "isin": isin,
            "filed_at": filed_at,
            "pdf_url": pdf_url,
        })

    return results
