"""
Pipeline orchestrator — ties together ingest → extract → summarize.
Used by both the watcher loop and manual runs.
"""
import sys
import asyncio
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backend.db import (
    init_db, filing_exists, insert_filing, update_filing,
    insert_summary, get_pending_filings, increment_attempt_count, stored_path,
    resolve_path,
)
from ingestion.nse import fetch_concall_announcements, fetch_concall_range
from ingestion.downloader import download_pdf
from extraction.extractor import extract_and_save
from summarizer.summarizer import summarize


async def process_filing(filing: dict, broadcast_fn=None):
    """
    Full pipeline for one filing: download → extract → summarize → broadcast.
    Returns True on success.
    """
    filing_id = filing["id"]
    increment_attempt_count(filing_id)

    # Download PDF
    pdf_path = await asyncio.to_thread(download_pdf, filing)
    if not pdf_path:
        update_filing(filing_id, status="failed", error="PDF download failed")
        return False

    pdf_relative_path = stored_path(pdf_path)
    update_filing(filing_id, pdf_path=pdf_relative_path, status="extracting")
    filing["pdf_path"] = pdf_relative_path

    # Extract text
    text_path = await asyncio.to_thread(extract_and_save, filing)
    if not text_path:
        update_filing(filing_id, status="failed", error="Text extraction failed")
        return False

    text_relative_path = stored_path(text_path)
    update_filing(filing_id, text_path=text_relative_path, status="summarizing")
    filing["text_path"] = text_relative_path

    text = resolve_path(text_relative_path).read_text(encoding="utf-8")
    if len(text.strip()) < 3000 or not re.search(r"\bmoderator\s*:", text, re.IGNORECASE):
        update_filing(
            filing_id,
            status="skipped",
            error="Extracted text is too short or has no moderator speaker label",
        )
        print(f"[pipeline] Skipped non-transcript filing: {filing['company']}")
        return False

    # Summarize
    result = await asyncio.to_thread(summarize, filing)
    if not result:
        update_filing(filing_id, status="failed", error="Summarization failed")
        return False

    json_path, md_path = result
    insert_summary(filing_id, stored_path(json_path), stored_path(md_path))
    update_filing(filing_id, status="done")

    if broadcast_fn:
        import json as _json
        summary_data = _json.loads(json_path.read_text(encoding="utf-8"))
        await broadcast_fn({
            "event": "new-summary",
            "filing_id": filing_id,
            "company": filing["company"],
            "exchange": filing["exchange"],
            "filed_at": filing["filed_at"],
            "tldr": summary_data.get("tldr", ""),
        })

    return True


async def run_once(broadcast_fn=None):
    """Fetch new NSE filings and process any that haven't been seen."""
    filings = await asyncio.to_thread(fetch_concall_announcements)
    new = 0
    attempted_ids = set()
    for filing in filings:
        if filing_exists(filing["id"]):
            continue
        insert_filing(filing)
        new += 1
        attempted_ids.add(filing["id"])
        print(f"[pipeline] New filing: {filing['company']}")
        await process_filing(filing, broadcast_fn)

    # Also retry previously failed ones
    for filing in get_pending_filings():
        if filing["id"] in attempted_ids:
            continue
        print(f"[pipeline] Retrying: {filing['company']}")
        await process_filing(dict(filing), broadcast_fn)

    return new


async def watcher_loop(broadcast_fn=None, poll_interval: int = 300):
    """Continuously poll for new filings."""
    import os
    interval = int(os.environ.get("POLL_INTERVAL", poll_interval))
    print(f"[watcher] Starting. Polling every {interval}s.")
    while True:
        try:
            new = await run_once(broadcast_fn)
            if new:
                print(f"[watcher] Processed {new} new filing(s)")
        except Exception as e:
            print(f"[watcher] Error in poll cycle: {e}")
        await asyncio.sleep(interval)
