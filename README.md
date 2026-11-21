# The AfterCall

**Automated earnings concall intelligence for NSE-listed Indian companies.**

The AfterCall monitors NSE corporate announcements, identifies concall transcript filings, downloads and extracts their content, and generates AI-powered summaries — all in real time.

---

## Demo

```
start.bat                 # Windows
bash start.sh             # Linux/macOS
# Open http://localhost:8000
```

---

## Architecture

```
NSE API ──► Watcher ──► Downloader ──► Extractor ──► Summarizer (Gemini)
                                                           │
                                                     data/summaries/
                                                           │
                                           FastAPI (REST + WebSocket)
                                                           │
                                                      Frontend (/)
```

### Components

| Path | What it does |
|---|---|
| `ingestion/nse.py` | Fetches concall filings from NSE via session-cookie API |
| `ingestion/bse.py` | BSE fetcher (best-effort, non-fatal if unavailable) |
| `ingestion/downloader.py` | Downloads PDFs with retry + dedup |
| `ingestion/backfill.py` | Seeds initial data from last N days |
| `extraction/extractor.py` | pdfplumber text extraction + pytesseract OCR fallback |
| `summarizer/summarizer.py` | Gemini single-pass summarizer → JSON + Markdown |
| `backend/db.py` | SQLite state store for filings and summaries |
| `backend/main.py` | FastAPI server: REST API + WebSocket + serves frontend |
| `backend/pipeline.py` | Orchestrates the full ingest→extract→summarize cycle |
| `frontend/` | Vanilla JS dashboard — company browser + summary viewer |

---

## Setup

### Requirements

- Python 3.11+
- A free [Gemini API key](https://aistudio.google.com/app/apikey)
- `pip install -r requirements.txt`

### Configuration

```bash
cp .env.example .env
# Edit .env and set GEMINI_API_KEY
```

### First Run

```bash
# 1. Download initial batch of concall transcripts (last 7 days, 10 companies)
python ingestion/backfill.py 10 7

# 2. Extract text from PDFs
python -m extraction.run_extraction

# 3. Generate AI summaries (takes a few minutes per transcript)
python run_summarize.py

# 4. Start the server (also runs the watcher automatically)
start.bat        # Windows
bash start.sh    # Linux/macOS
```

Then open **http://localhost:8000**

---

## API

| Endpoint | Description |
|---|---|
| `GET /api/companies` | List all processed companies |
| `GET /api/companies/{id}` | Get filing metadata |
| `GET /api/companies/{id}/summary` | Get structured JSON summary |
| `GET /api/companies/{id}/summary/markdown` | Get Markdown summary file |
| `GET /api/companies/{id}/transcript` | Get extracted transcript text |
| `WS /ws` | WebSocket: receives `init` and `new-summary` events |

### WebSocket Events

**`init`** — sent on connect:
```json
{
  "event": "init",
  "companies": [{"filing_id": "...", "company": "...", "exchange": "NSE", "filed_at": "..."}]
}
```

**`new-summary`** — broadcast when a transcript is processed:
```json
{
  "event": "new-summary",
  "filing_id": "abc123",
  "company": "Acme Corp Limited",
  "exchange": "NSE",
  "filed_at": "20-Nov-2026 18:30:00",
  "tldr": "Acme reported..."
}
```

---

## Data Storage

```
data/
  pdfs/          Original downloaded PDFs (preserved)
  texts/         Extracted plain text transcripts
  summaries/
    {filing_id}/
      summary.json    Structured AI summary
      summary.md      Human-readable Markdown
  db.sqlite      Processing state (filings + summaries)
```

---

## How NSE Filtering Works

NSE's `Analysts/Institutional Investor Meet/Con. Call Updates` category contains two types of filings:

1. **Schedule notices** — brief 1-page PDFs announcing an upcoming call (< 80KB, 1 page)
2. **Actual transcripts** — multi-page PDFs filed after the call (> 80KB, 5-25 pages)

The ingestion layer filters by file size (`attFileSize` field in NSE's API) to skip schedule notices and only process actual transcripts.

---

## Limitations

- **NSE session cookies** expire periodically; the watcher refreshes them every 5 minutes
- **BSE API** is unreliable from certain network conditions; the pipeline falls back gracefully to NSE-only
- **Free-tier Gemini** rate limits: 15 req/min on `gemini-3.5-flash-lite`. The summarizer handles this with auto-retry and backoff
- **Scanned PDFs**: Some companies upload image-scanned transcripts. OCR via `pytesseract` is attempted but quality varies. OCR requires Tesseract to be installed separately
- The watcher polls NSE every 5 minutes (configurable via `POLL_INTERVAL`). It is not truly real-time
- Transcript PDFs are sourced only from exchange filings. Direct investor-relations websites are not scraped

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | *(required)* | Google AI Studio API key |
| `POLL_INTERVAL` | `300` | Seconds between watcher polls |
| `HOST` | `0.0.0.0` | Server bind address |
| `PORT` | `8000` | Server port |
| `MAX_WORKERS` | `3` | Max concurrent downloads |

---

## Disclaimer

AI summaries are generated from actual transcript text. They are for informational purposes only and should not be used as the basis for financial decisions. Always refer to the original source documents.

---

*Built with FastAPI, pdfplumber, and Google Gemini. Data sourced from NSE corporate filings.*
