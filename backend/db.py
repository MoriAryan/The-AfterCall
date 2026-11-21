"""
Database layer — SQLite for storing filing state and summaries.
Single file, no ORM. Keep it simple.
"""
import sqlite3
import json
import re
from pathlib import Path
from contextlib import contextmanager

ROOT = Path(__file__).parent.parent.resolve()
DB_PATH = ROOT / "data" / "db.sqlite"


def stored_path(path: str | Path) -> str:
    """Store an app-local path in a portable, root-relative form."""
    resolved = Path(path).resolve()
    return resolved.relative_to(ROOT).as_posix()


def resolve_path(path: str | Path) -> Path:
    """Resolve current and legacy absolute DB paths against the project root."""
    value = str(path)
    if not Path(value).is_absolute():
        return (ROOT / value).resolve()

    try:
        return (ROOT / Path(value).resolve().relative_to(ROOT)).resolve()
    except ValueError:
        # Older databases may have an absolute path from another machine.
        match = re.search(r"(?:^|[\\/])(data[\\/].*)$", value, re.IGNORECASE)
        if match:
            relative = match.group(1).replace("\\", "/")
            return (ROOT / relative).resolve()
        return Path(value)


def init_db():
    with _conn() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS filings (
                id          TEXT PRIMARY KEY,
                exchange    TEXT NOT NULL,
                symbol      TEXT,
                company     TEXT NOT NULL,
                isin        TEXT,
                filed_at    TEXT NOT NULL,
                pdf_url     TEXT NOT NULL,
                pdf_path    TEXT,
                text_path   TEXT,
                status      TEXT NOT NULL DEFAULT 'pending',
                error       TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS summaries (
                filing_id   TEXT PRIMARY KEY REFERENCES filings(id),
                json_path   TEXT,
                md_path     TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(filings)")}
        if "attempt_count" not in columns:
            db.execute(
                "ALTER TABLE filings ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0"
            )

        for table, path_columns in (
            ("filings", ("pdf_path", "text_path")),
            ("summaries", ("json_path", "md_path")),
        ):
            for column in path_columns:
                rows = db.execute(
                    f"SELECT rowid, {column} FROM {table} WHERE {column} IS NOT NULL"
                ).fetchall()
                for row in rows:
                    portable = resolve_path(row[column])
                    try:
                        relative = stored_path(portable)
                    except ValueError:
                        continue
                    if relative != row[column]:
                        db.execute(
                            f"UPDATE {table} SET {column} = ? WHERE rowid = ?",
                            (relative, row["rowid"]),
                        )


@contextmanager
def _conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def filing_exists(filing_id: str) -> bool:
    with _conn() as db:
        row = db.execute("SELECT 1 FROM filings WHERE id = ?", (filing_id,)).fetchone()
        return row is not None


def insert_filing(filing: dict):
    with _conn() as db:
        db.execute("""
            INSERT OR IGNORE INTO filings (id, exchange, symbol, company, isin, filed_at, pdf_url)
            VALUES (:id, :exchange, :symbol, :company, :isin, :filed_at, :pdf_url)
        """, filing)


def update_filing(filing_id: str, **kwargs):
    if not kwargs:
        return
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    values = list(kwargs.values()) + [filing_id]
    with _conn() as db:
        db.execute(f"UPDATE filings SET {sets} WHERE id = ?", values)


def increment_attempt_count(filing_id: str):
    with _conn() as db:
        db.execute(
            "UPDATE filings SET attempt_count = attempt_count + 1 WHERE id = ?",
            (filing_id,),
        )


def insert_summary(filing_id: str, json_path: str, md_path: str):
    with _conn() as db:
        db.execute("""
            INSERT OR REPLACE INTO summaries (filing_id, json_path, md_path)
            VALUES (?, ?, ?)
        """, (filing_id, json_path, md_path))


def get_all_companies():
    with _conn() as db:
        rows = db.execute("""
            SELECT f.id, f.company, f.symbol, f.exchange, f.isin, f.filed_at,
                   f.pdf_url, f.pdf_path, f.text_path, f.status,
                   s.json_path, s.md_path
            FROM filings f
            LEFT JOIN summaries s ON s.filing_id = f.id
            WHERE f.status = 'done'
            ORDER BY f.filed_at DESC
        """).fetchall()
        return [dict(r) for r in rows]


def get_filing(filing_id: str):
    with _conn() as db:
        row = db.execute("""
            SELECT f.*, s.json_path, s.md_path
            FROM filings f
            LEFT JOIN summaries s ON s.filing_id = f.id
            WHERE f.id = ?
        """, (filing_id,)).fetchone()
        return dict(row) if row else None


def get_pending_filings():
    with _conn() as db:
        rows = db.execute(
            """SELECT * FROM filings
               WHERE status IN (
                   'pending', 'failed', 'summarize_pending',
                   'extracting', 'summarizing', 'extracted_pending'
               )
               AND attempt_count < 3
               ORDER BY created_at"""
        ).fetchall()
        return [dict(r) for r in rows]
