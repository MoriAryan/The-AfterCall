"""
Backfill script — seeds the database with the latest available concall transcripts.
Looks for real filings from NSE and downloads up to `limit` PDFs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.nse import fetch_concall_announcements
from ingestion.downloader import download_pdf
from backend.db import init_db, filing_exists, insert_filing, update_filing


def backfill(limit: int = 10):
    init_db()
    print(f"[backfill] Fetching NSE concall announcements...")
    filings = fetch_concall_announcements()
    print(f"[backfill] Found {len(filings)} concall filings on NSE")

    downloaded = 0
    for filing in filings:
        if downloaded >= limit:
            break

        if filing_exists(filing["id"]):
            print(f"[backfill] Already have {filing['company']} — skipping")
            continue

        insert_filing(filing)
        pdf_path = download_pdf(filing)

        if pdf_path:
            update_filing(filing["id"], pdf_path=str(pdf_path), status="extracted_pending")
            downloaded += 1
            print(f"[backfill] ({downloaded}/{limit}) Downloaded: {filing['company']}")
        else:
            update_filing(filing["id"], status="failed", error="PDF download failed")

    print(f"[backfill] Done. {downloaded} new PDFs downloaded.")
    return downloaded


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    backfill(limit)
