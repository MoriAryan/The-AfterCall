import sys
sys.path.insert(0, '.')
from backend.db import _conn

# Reset ABB and any other failed filings with good text
with _conn() as db:
    rows = db.execute("SELECT id, company, text_path FROM filings WHERE status='failed'").fetchall()
    for r in rows:
        from pathlib import Path
        tp = Path(r['text_path'] or '')
        if tp.exists() and tp.stat().st_size > 3000:
            db.execute("UPDATE filings SET status='summarize_pending', error=NULL WHERE id=?", (r['id'],))
            print(f"Reset: {r['company']}")
