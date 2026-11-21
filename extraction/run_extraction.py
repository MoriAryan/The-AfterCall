"""
Run extraction on all filings in extracted_pending status.
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from backend.db import init_db, get_pending_filings, update_filing, get_all_companies
from extraction.extractor import extract_and_save
import sqlite3

def run_extraction():
    init_db()
    # Get all filings that have a PDF but no text yet
    from backend.db import _conn
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM filings WHERE pdf_path IS NOT NULL AND (text_path IS NULL OR text_path = '') AND status != 'failed'"
        ).fetchall()
        filings = [dict(r) for r in rows]

    print(f"[extract] Processing {len(filings)} filings...")
    for filing in filings:
        print(f"[extract] -> {filing['company']}")
        text_path = extract_and_save(filing)
        if text_path:
            update_filing(filing["id"], text_path=str(text_path), status="summarize_pending")
        else:
            update_filing(filing["id"], status="failed", error="extraction failed")

    print("[extract] Done.")

if __name__ == "__main__":
    run_extraction()
