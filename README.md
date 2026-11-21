# The AfterCall

**Automated earnings concall intelligence for NSE-listed Indian companies.**

Companies have a lot to say after announcing their quarterly results. Somewhere between the exchange filing and the actual transcript, there's usually a little digging involved.

The AfterCall takes care of that part. It watches NSE announcements, finds likely earnings-call transcripts, extracts the conversation, and turns it into structured summaries that are easier to follow.

It runs on its own, with one small catch: the market may move in seconds, but this watcher checks in every five minutes.

---

## Demo

```text
start.bat                 # Windows
bash start.sh             # Linux/macOS
# Open http://localhost:8000
```

---

## Architecture

```text
NSE API -> Watcher -> Downloader -> Extractor -> Summarizer (Gemini)
                                                     |
                                               data/summaries/
                                                     |
                                     FastAPI (REST + WebSocket)
                                                     |
                                                Frontend (/)
```
The pipeline is intentionally kept in separate stages. Finding a document, reading it, and understanding it are three different problems. Better not make one responsible for all three.

| Path | What it does |
|---|---|
| `ingestion/nse.py` | Fetches and title-filters likely transcript filings from NSE |
| `ingestion/downloader.py` | Downloads PDFs with retry + dedup |
| `ingestion/backfill.py` | Seeds initial data from last N days |
| `extraction/extractor.py` | pdfplumber text extraction + pytesseract OCR fallback |
| `summarizer/summarizer.py` | Gemini single-pass or chunked summarizer -> JSON + Markdown |
| `backend/db.py` | SQLite state store for filings and summaries |
| `backend/main.py` | FastAPI server: REST API + WebSocket + serves frontend |
| `backend/pipeline.py` | Orchestrates the full ingest -> extract -> summarize cycle |
| `frontend/` | Vanilla JS dashboard — company browser + summary viewer |

---

## Setup

### Requirements

- Python 3.11+
- A free [Gemini API key](https://aistudio.google.com/app/apikey)
- `pip install -r requirements.txt`

### Configuration

```text
Copy .env.example to .env and set GEMINI_API_KEY.
```

### First Run

```bash
# Start the watcher, API, UI, and WebSocket
start.bat        # Windows
bash start.sh    # Linux/macOS
```

Open **http://localhost:8000**. On a fresh install the watcher discovers and processes new filings; a historical backfill is optional:

```bash
python ingestion/backfill.py 10 7
python -m extraction.run_extraction
python run_summarize.py
```

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

---

## Data Storage

```text
data/
  pdfs/          Original downloaded PDFs (local, gitignored)
  texts/         Extracted plain text transcripts (local, gitignored)
  summaries/     Generated JSON and Markdown summaries (local, gitignored)
  db.sqlite      Processing state (local, gitignored)
```

Database file paths are stored relative to the project root so moving a checkout does not invalidate completed filings.

---

## Design Decisions and Trade-offs

- **Transcript filtering:** the NSE category includes meeting notices as well as transcripts. Ingestion requires transcript-like attachment text (e.g. “transcript”, “earning call”, or “concall”) and a PDF of a minimum size; extracted documents are skipped if they are under 3,000 characters or lack a `Moderator:` speaker label. This reduces repeated false-positive processing but may reject unusually formatted transcripts.
- **Retries:** failed processing attempts are capped at three and retried on later poll cycles. Skipped documents are terminal and are not retried.
- **Storage:** the SQLite database stores paths relative to the project root. Runtime PDFs, extracted text, and generated summaries remain local and are gitignored.
- **Summary format:** JSON follows the assignment's sample fields, with `tldr` as a list, segment objects, metric context, and `asked_by` on Q&A. Exchange and filing IDs are retained as additional traceability fields. Missing transcript metadata is left empty rather than inferred from the filing date.
- **Exchange coverage:** the unattended watcher is NSE-only. A BSE fetcher is not wired into the pipeline, so this project does not claim BSE ingestion or cross-exchange deduplication.
- **Long transcripts:** the summarizer uses overlapping chunks followed by an aggregation call. Map-reduce reduces prompt size but can lose nuance; chunk notes are sent without the previous fixed 30,000-character truncation.

A meeting announcement is not a meeting transcript. The distinction matters more than it initially sounds.

## Samples

See [`samples/`](samples/) for three JSON and Markdown summaries. Original exchange PDFs and full transcript text are not redistributed here; each sample links to its NSE source filing.

The current sample set covers logistics, nutrition, and FMCG; the assignment's suggested bank, IT, and pharma coverage is not yet represented.

## What I'd Do With More Time

- Wire BSE into the watcher, normalize its metadata, and deduplicate filings across exchanges by issuer, call date, and source document.
- Improve transcript classification with structured exchange metadata and a curated test set of notices and transcripts.
- Add integration tests for live exchange responses and model output, with recorded fixtures that do not require API calls in CI.
- Improve extraction for multi-column PDFs and small-caps speaker names, and expose OCR quality diagnostics.

## Limitations

- **Polling, not push:** NSE is polled every five minutes by default (`POLL_INTERVAL`). New filings are therefore detected with a delay, not the instant they are posted.
- **NSE only:** BSE ingestion and cross-exchange deduplication are not implemented.
- **Heuristic filtering:** titles, file size, extracted text length, and the moderator label reduce schedule-notice false positives but may miss transcripts with unusual filenames or layouts.
- **Gemini availability:** rate limits and provider outages can delay a summary. Failed attempts are retried up to three times.
- **Scanned PDFs:** OCR is attempted but quality varies and Tesseract must be installed separately.
- **Metadata:** scrip code, symbol, quarter, and call date are parsed from transcript text when present; fields remain empty when not found.
- **Source coverage:** only exchange attachments are processed; investor-relations sites and audio-only announcements are not scraped.

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



*May your PDFs be text-based and your API calls return 200 ✨.*