import unittest
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from ingestion.nse import _parse_filing
from summarizer import summarizer
from backend import db


class NseTranscriptFilterTests(unittest.TestCase):
    def setUp(self):
        self.item = {
            "attchmntFile": "https://example.test/Acme_Transcript.pdf",
            "desc": "Analysts/Institutional Investor Meet/Con. Call Updates",
            "attFileSize": "300.00 KB",
            "sm_name": "Acme Limited",
            "symbol": "ACME",
            "sm_isin": "INE123A01010",
            "an_dt": "21-Nov-2026 10:00:00",
        }

    def test_accepts_transcript_attachment(self):
        filing = _parse_filing(self.item)
        self.assertIsNotNone(filing)
        self.assertEqual(filing["symbol"], "ACME")

    def test_rejects_large_schedule_notice(self):
        self.item["attchmntFile"] = "https://example.test/InvestorMeetSchedule.pdf"
        self.assertIsNone(_parse_filing(self.item))


class SummarySchemaTests(unittest.TestCase):
    def test_normalizes_legacy_summary_fields(self):
        result = summarizer.normalize_summary({
            "tldr": "Summary",
            "management_commentary": [],
            "guidance": [],
            "segment_performance": ["Retail: Revenue increased"],
            "key_metrics": [{"metric": "Revenue", "value": "100", "period": "Q2", "note": "Up"}],
            "qa_highlights": [{"question": "Question", "answer": "Answer"}],
            "risks_and_concerns": ["Risk"],
        })
        self.assertTrue(summarizer._has_summary_fields(result))
        self.assertEqual(result["tldr"], ["Summary"])
        self.assertEqual(result["segment_performance"], [
            {"segment": "Retail", "notes": "Revenue increased"}
        ])
        self.assertEqual(result["key_metrics"][0]["context"], "Q2 — Up")
        self.assertEqual(result["notable_qa"][0]["asked_by"], "")
        self.assertEqual(result["risks"], ["Risk"])
        self.assertNotIn("qa_highlights", result)
        self.assertNotIn("risks_and_concerns", result)
        self.assertTrue(summarizer._valid(result))

    def test_rejects_missing_required_model_fields(self):
        self.assertFalse(summarizer._has_summary_fields({"tldr": ["Summary"]}))

    def test_extracts_transcript_metadata_without_guessing(self):
        filing = {"symbol": "ACME"}
        text = (
            "BSE Scrip Code: 500368 NSE Symbol: PATANJALI "
            "Q2 & H1 FY27 call held on November 14, 2026."
        )
        self.assertEqual(summarizer.transcript_metadata(filing, text), {
            "scrip_code": "500368",
            "nse_symbol": "PATANJALI",
            "quarter": "Q2 & H1 FY27",
            "call_date": "2026-11-14",
        })
        self.assertEqual(
            summarizer.transcript_metadata(filing, "No metadata here")["nse_symbol"],
            "ACME",
        )

    def test_chunking_finishes_on_last_overlapping_chunk(self):
        with patch.object(summarizer, "CHUNK_SIZE", 100), \
             patch.object(summarizer, "OVERLAP", 10), \
             patch.object(summarizer, "_call", return_value="{}") as call:
            summarizer._summarize_chunked(object(), "Acme", "x" * 201)
        self.assertEqual(call.call_count, 4)


class DatabasePathTests(unittest.TestCase):
    def test_init_migrates_legacy_windows_paths(self):
        relative = "data/texts/52c936a9d5c61435.txt"
        legacy_path = r"Z:\old-checkout\data\texts\52c936a9d5c61435.txt"
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "legacy.sqlite"
            connection = sqlite3.connect(database_path)
            connection.executescript("""
                CREATE TABLE filings (
                    id TEXT PRIMARY KEY, exchange TEXT NOT NULL, symbol TEXT,
                    company TEXT NOT NULL, isin TEXT, filed_at TEXT NOT NULL,
                    pdf_url TEXT NOT NULL, pdf_path TEXT, text_path TEXT,
                    status TEXT NOT NULL DEFAULT 'pending', error TEXT,
                    created_at TEXT
                );
                INSERT INTO filings (
                    id, exchange, company, filed_at, pdf_url, text_path, status
                ) VALUES (
                    'legacy', 'NSE', 'Acme', '2026-11-21', 'https://example.test/x.pdf',
                    'Z:\\old-checkout\\data\\texts\\52c936a9d5c61435.txt', 'failed'
                );
                CREATE TABLE summaries (
                    filing_id TEXT PRIMARY KEY, json_path TEXT, md_path TEXT,
                    created_at TEXT
                );
            """)
            connection.commit()
            connection.close()

            with patch.object(db, "DB_PATH", database_path):
                db.init_db()
                migrated = sqlite3.connect(database_path)
                try:
                    row = migrated.execute(
                        "SELECT text_path, attempt_count FROM filings WHERE id = 'legacy'"
                    ).fetchone()
                finally:
                    migrated.close()

        self.assertEqual(row, (relative, 0))


if __name__ == "__main__":
    unittest.main()
