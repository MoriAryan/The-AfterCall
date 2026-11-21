"""
Run summarization on all filings that have extracted text but no summary yet.
"""
import sys, os
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

# Load .env
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from backend.db import init_db, update_filing, insert_summary, _conn
from summarizer.summarizer import summarize


def run_summarization():
    init_db()
    with _conn() as db:
        rows = db.execute("""
            SELECT f.* FROM filings f
            LEFT JOIN summaries s ON s.filing_id = f.id
            WHERE f.text_path IS NOT NULL
              AND f.text_path != ''
              AND s.filing_id IS NULL
              AND f.status IN ('summarize_pending', 'extracted_pending', 'done')
        """).fetchall()
        filings = [dict(r) for r in rows]

    print(f"[summarize] Processing {len(filings)} filings...")
    done = 0
    for filing in filings:
        print(f"\n[summarize] -> {filing['company']}")
        result = summarize(filing)
        if result:
            json_path, md_path = result
            insert_summary(filing["id"], str(json_path), str(md_path))
            update_filing(filing["id"], status="done")
            done += 1
        else:
            text_path = Path(filing.get("text_path", ""))
            if text_path.exists() and text_path.stat().st_size > 3000:
                update_filing(filing["id"], status="failed", error="summarization failed")

    print(f"\n[summarize] Done. {done} summaries generated.")


if __name__ == "__main__":
    run_summarization()
