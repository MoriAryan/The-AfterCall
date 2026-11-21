"""
Backfill script — seeds the database with real concall transcripts from NSE.
Fetches across a date range to find diverse companies across sectors.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.nse import fetch_concall_range
from ingestion.downloader import download_pdf
from backend.db import init_db, filing_exists, insert_filing, update_filing

# Target well-known companies across sectors for the initial backfill
# If these aren't in the latest window, we fall back to whatever we find
PRIORITY_COMPANIES = {
    "Titan Company Limited",
    "Trent Limited",
    "Kalyan Jewellers India Limited",
    "IndusInd Bank Limited",
    "HDFC Bank Limited",
    "Tata Communications Limited",
    "Bikaji Foods International Limited",
    "Hexagon Nutrition Limited",
    "Adani Green Energy Limited",
    "JSW Energy Limited",
    "Pidilite Industries Limited",
    "Colgate Palmolive (India) Limited",
    "Siemens Limited",
    "ABB India Limited",
    "Kaynes Technology India Limited",
    "Shriram Finance Limited",
    "Tata Power Company Limited",
    "NHPC Limited",
    "IndiaMART InterMESH Limited",
    "Nazara Technologies Limited",
}


def backfill(limit: int = 10, days_back: int = 7):
    init_db()
    print(f"[backfill] Fetching NSE concall announcements (last {days_back} days)...")
    all_filings = fetch_concall_range(days_back=days_back)
    print(f"[backfill] Found {len(all_filings)} unique concall filings")

    # Sort: priority companies first, then rest
    priority = [f for f in all_filings if f["company"] in PRIORITY_COMPANIES]
    rest = [f for f in all_filings if f["company"] not in PRIORITY_COMPANIES]
    ordered = priority + rest

    downloaded = 0
    for filing in ordered:
        if downloaded >= limit:
            break
        if filing_exists(filing["id"]):
            print(f"[backfill] Already have: {filing['company']}")
            continue

        insert_filing(filing)
        pdf_path = download_pdf(filing)

        if pdf_path:
            update_filing(filing["id"], pdf_path=str(pdf_path), status="extracted_pending")
            downloaded += 1
            print(f"[backfill] ({downloaded}/{limit}) {filing['company']}")
        else:
            update_filing(filing["id"], status="failed", error="download failed")

    print(f"[backfill] Done. {downloaded} new PDFs downloaded.")
    return downloaded


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 7
    backfill(limit, days)
