"""
The AfterCall — FastAPI backend.
Exposes REST endpoints for companies and summaries, plus a WebSocket feed.
"""
import os
import sys
import json
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Set

# Ensure project root is in path regardless of how the server is started
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# Load .env if present
_env = ROOT / ".env"
if _env.exists():
    for _line in _env.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.db import init_db, get_all_companies, get_filing, resolve_path
from backend.pipeline import watcher_loop
from summarizer.summarizer import normalize_summary, transcript_metadata

# --- WebSocket connection manager ---

class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, data: dict):
        dead = set()
        for ws in self.active:
            try:
                await ws.send_json(data)
            except Exception:
                dead.add(ws)
        self.active -= dead


manager = ConnectionManager()


# --- App lifecycle ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(watcher_loop(manager.broadcast))
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="The AfterCall", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- REST API ---

@app.get("/api/companies")
def list_companies():
    companies = get_all_companies()
    # Don't expose raw file paths to clients
    for c in companies:
        c.pop("pdf_path", None)
        c.pop("text_path", None)
        c.pop("json_path", None)
        c.pop("md_path", None)
    return companies


@app.get("/api/companies/{filing_id}")
def get_company(filing_id: str):
    filing = get_filing(filing_id)
    if not filing:
        raise HTTPException(status_code=404, detail="Filing not found")
    return {
        "id": filing["id"],
        "company": filing["company"],
        "exchange": filing["exchange"],
        "symbol": filing["symbol"],
        "filed_at": filing["filed_at"],
        "source_url": filing["pdf_url"],
        "status": filing["status"],
    }


@app.get("/api/companies/{filing_id}/summary")
def get_summary(filing_id: str):
    filing = get_filing(filing_id)
    if not filing or not filing.get("json_path"):
        raise HTTPException(status_code=404, detail="Summary not found")
    json_path = resolve_path(filing["json_path"])
    if not json_path.exists():
        raise HTTPException(status_code=404, detail="Summary file missing")
    summary = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(summary, dict):
        raise HTTPException(status_code=500, detail="Stored summary has invalid schema")
    schema_fields = {
        "company", "scrip_code", "nse_symbol", "quarter", "call_date",
        "source", "source_url", "tldr", "management_commentary", "guidance",
        "segment_performance", "key_metrics", "notable_qa", "risks",
    }
    if not schema_fields.issubset(summary):
        required = {
            "tldr", "management_commentary", "guidance",
            "segment_performance", "key_metrics",
        }
        if (
            not required.issubset(summary)
            or not ("notable_qa" in summary or "qa_highlights" in summary)
            or not ("risks" in summary or "risks_and_concerns" in summary)
        ):
            raise HTTPException(status_code=500, detail="Stored summary has invalid schema")

        summary = normalize_summary(summary)
        if filing.get("text_path"):
            text_path = resolve_path(filing["text_path"])
            if text_path.exists():
                summary.update(
                    transcript_metadata(
                        filing, text_path.read_text(encoding="utf-8")
                    )
                )
        summary.update({
            "company": filing["company"],
            "source": filing["exchange"],
            "source_url": filing["pdf_url"],
            "filing_id": filing["id"],
        })
        summary.setdefault("scrip_code", "")
        summary.setdefault("nse_symbol", filing.get("symbol") or "")
        summary.setdefault("quarter", "")
        summary.setdefault("call_date", "")

    return summary


@app.get("/api/companies/{filing_id}/summary/markdown")
def get_summary_markdown(filing_id: str):
    filing = get_filing(filing_id)
    if not filing or not filing.get("md_path"):
        raise HTTPException(status_code=404, detail="Markdown summary not found")
    md_path = resolve_path(filing["md_path"])
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Markdown file missing")
    return FileResponse(str(md_path), media_type="text/markdown")


@app.get("/api/companies/{filing_id}/transcript")
def get_transcript(filing_id: str):
    filing = get_filing(filing_id)
    if not filing or not filing.get("text_path"):
        raise HTTPException(status_code=404, detail="Transcript not found")
    text_path = resolve_path(filing["text_path"])
    if not text_path.exists():
        raise HTTPException(status_code=404, detail="Transcript file missing")
    return FileResponse(str(text_path), media_type="text/plain")


# --- WebSocket ---

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        # Send current processed companies on connect
        companies = get_all_companies()
        await ws.send_json({"event": "init", "companies": [
            {"filing_id": c["id"], "company": c["company"],
             "exchange": c["exchange"], "filed_at": c["filed_at"]}
            for c in companies
        ]})
        while True:
            await ws.receive_text()  # keep alive
    except WebSocketDisconnect:
        manager.disconnect(ws)


# --- Serve frontend ---

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
