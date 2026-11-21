"""
BSE corporate announcements fetcher.
BSE's API endpoint is unreliable from certain networks — this is a best-effort fetcher.
If BSE fails, the pipeline continues with NSE data only.
"""
import hashlib
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.bseindia.com/",
}

BSE_PDF_BASE = "https://www.bseindia.com/xml-data/corpfiling/AttachHis/"

CONCALL_KEYWORDS = ["transcript", "concall", "conference call", "earnings call"]


def fetch_concall_announcements(from_date: str, to_date: str) -> list[dict]:
    """
    Fetch BSE announcements for the given date range and filter for concall transcripts.
    Returns empty list if BSE API is unreachable.
    """
    try:
        resp = requests.get(
            "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w",
            params={
                "strCat": "Result",
                "strPrevDate": from_date,
                "strScrip": "",
                "strSearch": "P",
                "strToDate": to_date,
                "strType": "C",
                "subcategory": "-1",
            },
            headers=HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"[BSE] fetch error (non-fatal): {e}")
        return []

    table = data.get("Table", [])
    results = []

    for item in table:
        subject = (item.get("NEWSSUB") or "").lower()
        if not any(kw in subject for kw in CONCALL_KEYWORDS):
            continue

        attachment = item.get("ATTACHMENTNAME", "")
        if not attachment:
            continue

        pdf_url = BSE_PDF_BASE + attachment
        company = item.get("SLONGNAME", "Unknown")
        scrip_cd = str(item.get("SCRIP_CD", ""))
        filed_at = item.get("DT_TM", "")

        filing_id = hashlib.sha1(pdf_url.encode()).hexdigest()[:16]

        results.append({
            "id": filing_id,
            "exchange": "BSE",
            "symbol": scrip_cd,
            "company": company,
            "isin": "",
            "filed_at": filed_at,
            "pdf_url": pdf_url,
        })

    return results
