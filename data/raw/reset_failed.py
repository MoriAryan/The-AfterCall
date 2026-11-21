import sys
sys.path.insert(0, '.')
from backend.db import _conn
from pathlib import Path

with _conn() as db:
    rows = db.execute("SELECT id, company, text_path, status FROM filings").fetchall()
    for r in rows:
        text_path = Path(r['text_path'] or '')
        if text_path.exists() and text_path.stat().st_size > 3000:
            db.execute("UPDATE filings SET status='summarize_pending', error=NULL WHERE id=?", (r['id'],))
            print(f"Reset to summarize_pending: {r['company']} ({text_path.stat().st_size} bytes)")
        else:
            print(f"Skip (short text or missing): {r['company']}")
