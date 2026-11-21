"""
NSE corporate announcements fetcher.
NSE requires a session cookie — hit the main page first, then the API.
"""
import time
import hashlib
import re
import requests
from datetime import datetime, timedelta
from urllib.parse import unquote, urlparse

CONCALL_DESC = "Analysts/Institutional Investor Meet/Con. Call Updates"
MIN_TRANSCRIPT_SIZE_KB = 80  # filter out 1-page cover letters and schedule notices

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


def _parse_size_kb(size_str: str) -> float:
    """Parse NSE file size string like '1.26 MB' or '387.00 KB' to KB."""
    try:
        parts = size_str.strip().split()
        val = float(parts[0])
        return val * 1024 if parts[1].upper() == "MB" else val
    except Exception:
        return 0.0


def _parse_filing(item: dict, min_size_kb: float = MIN_TRANSCRIPT_SIZE_KB) -> dict | None:
    pdf_url = item.get("attchmntFile")
    if not pdf_url or not urlparse(pdf_url).path.lower().endswith(".pdf"):
        return None
    if item.get("desc") != CONCALL_DESC:
        return None

    title = " ".join(
        str(item.get(key) or "")
        for key in ("subject", "attFileName", "attachmentName", "an_desc")
    )
    filename = unquote(urlparse(pdf_url).path.rsplit("/", 1)[-1])
    transcript_terms = ("transcript", "earningcall", "earningscall", "concall",
                        "conferencecall", "investorcall")
    searchable_title = re.sub(r"[\s_\-]+", "", f"{title} {filename}").lower()
    if not any(term in searchable_title for term in transcript_terms):
        return None

    size_kb = _parse_size_kb(item.get("attFileSize", "") or "")
    if size_kb > 0 and size_kb < min_size_kb:
        return None

    company = item.get("sm_name", "Unknown")
    symbol = item.get("symbol") or item.get("sm_isin", "")[:10]
    isin = item.get("sm_isin", "")
    filed_at = item.get("an_dt", "")
    filing_id = hashlib.sha1(pdf_url.encode()).hexdigest()[:16]

    return {
        "id": filing_id,
        "exchange": "NSE",
        "symbol": symbol,
        "company": company,
        "isin": isin,
        "filed_at": filed_at,
        "pdf_url": pdf_url,
        "size_kb": round(size_kb, 1),
        "attempt_count": 0,
    }


def fetch_concall_announcements(days_back: int = 0) -> list[dict]:
    """
    Return concall transcript filings from NSE.
    days_back=0 fetches current page; >0 fetches a date range.
    """
    session = _get_session()
    params = {"index": "equities"}

    if days_back > 0:
        today = datetime.now()
        params["from_date"] = (today - timedelta(days=days_back)).strftime("%d-%m-%Y")
        params["to_date"] = today.strftime("%d-%m-%Y")

    try:
        resp = session.get(
            "https://www.nseindia.com/api/corporate-announcements",
            params=params,
            timeout=20,
        )
        resp.raise_for_status()
        announcements = resp.json()
    except Exception as e:
        print(f"[NSE] fetch error: {e}")
        return []

    results = []
    seen = set()
    for item in announcements:
        filing = _parse_filing(item)
        if filing and filing["id"] not in seen:
            seen.add(filing["id"])
            results.append(filing)

    return results


def fetch_concall_range(days_back: int = 60) -> list[dict]:
    """Fetch concall filings across multiple date windows to maximize coverage."""
    today = datetime.now()
    seen_ids = set()
    all_filings = []

    # NSE returns max ~500 items per request, so split into 2-week windows
    window = 14
    for start in range(0, days_back, window):
        end = min(start + window, days_back)
        date_to = (today - timedelta(days=start)).strftime("%d-%m-%Y")
        date_from = (today - timedelta(days=end)).strftime("%d-%m-%Y")

        session = _get_session()
        try:
            resp = session.get(
                "https://www.nseindia.com/api/corporate-announcements",
                params={"index": "equities", "from_date": date_from, "to_date": date_to},
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"[NSE] window {date_from}-{date_to} error: {e}")
            time.sleep(2)
            continue

        for item in data:
            filing = _parse_filing(item)
            if filing and filing["id"] not in seen_ids:
                seen_ids.add(filing["id"])
                all_filings.append(filing)

        time.sleep(1)  # be polite to NSE

    return all_filings
