import sys, os
sys.path.insert(0, '.')
from backend.db import _conn
from pathlib import Path

with _conn() as db:
    rows = db.execute('SELECT id, company, status, text_path FROM filings ORDER BY status').fetchall()
    for r in rows:
        tp = r['text_path'] or ''
        sz = Path(tp).stat().st_size if tp and Path(tp).exists() else 0
        print(f"{r['status']:25s} | {sz:6d}b | {r['company'][:45]}")
