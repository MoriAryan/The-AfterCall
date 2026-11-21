"""
AI summarizer using Google Gemini (google-genai SDK).

For transcripts under 100K chars we do a single-pass summarization.
For longer ones we chunk. Free tier: 15 req/min on 3.5-flash-lite.
"""
import os
import json
import re
import time
from pathlib import Path
from datetime import datetime

from google import genai
from google.genai import types

SUMMARY_DIR = Path(__file__).parent.parent / "data" / "summaries"

MODEL = "gemini-3.5-flash-lite"
MIN_TEXT_LEN = 3000
CHUNK_SIZE = 50000      # only chunk if transcript > 50K chars
OVERLAP = 500
INTER_CALL_DELAY = 5    # seconds between calls (3.5-flash-lite has higher quota)

SINGLE_PASS_PROMPT = """You are analyzing an earnings conference call transcript for {company}.

CRITICAL RULES:
- Only include information explicitly stated in the transcript
- Never fabricate financial figures, statements, or guidance
- Use exact numbers as mentioned. If a figure isn't stated, don't include it
- If a category has no information, use a clear placeholder string

Transcript:
{text}

Respond with ONLY valid JSON (no markdown fences, no explanation):
{{
  "tldr": "2-3 sentence executive summary of the call",
  "management_commentary": ["key management point 1", "key point 2", "..."],
  "guidance": ["specific guidance given"] or ["No specific guidance was provided in this call"],
  "segment_performance": ["Segment name: performance detail"] or ["No segment breakdown discussed"],
  "key_metrics": [
    {{"metric": "metric name", "value": "exact value with units", "period": "quarter/period", "note": "context"}}
  ],
  "qa_highlights": [
    {{"question": "analyst question", "answer": "management response summary"}}
  ],
  "risks_and_concerns": ["risk 1", "risk 2"] or ["No specific risks mentioned"]
}}"""

CHUNK_PROMPT = """Analyze this portion of an earnings call transcript for {company}.
Extract faithfully — no fabrication.

{chunk}

Extract (write "NOT MENTIONED" if absent):
1. MANAGEMENT STATEMENTS
2. FINANCIAL METRICS (exact figures)
3. SEGMENT UPDATES
4. GUIDANCE
5. KEY Q&A
6. RISKS"""

AGGREGATE_PROMPT = """Combine these notes from an earnings call transcript for {company} into a final summary.
Only use what's in the notes. No fabrication.

{notes}

Respond with ONLY valid JSON (no markdown):
{{
  "tldr": "2-3 sentence executive summary",
  "management_commentary": ["point 1", "..."],
  "guidance": ["guidance item"] or ["No specific guidance provided"],
  "segment_performance": ["Segment: detail"] or ["No segments discussed"],
  "key_metrics": [{{"metric": "...", "value": "...", "period": "...", "note": "..."}}],
  "qa_highlights": [{{"question": "...", "answer": "..."}}],
  "risks_and_concerns": ["risk 1"] or ["No risks mentioned"]
}}"""


def _client():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise EnvironmentError("GEMINI_API_KEY not set")
    return genai.Client(api_key=key)


def _call(client, prompt: str, retries: int = 5) -> str:
    for attempt in range(retries):
        try:
            resp = client.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1),
            )
            time.sleep(INTER_CALL_DELAY)
            return resp.text
        except Exception as e:
            err = str(e)
            if "429" in err or "503" in err or "EXHAUSTED" in err or "UNAVAILABLE" in err:
                wait = 65  # default: wait 65s to reset the per-minute bucket
                m = re.search(r"(\d+)s", err)
                if m:
                    wait = int(m.group(1)) + 5
                print(f"  rate limit/unavailable, waiting {wait}s (attempt {attempt+1}/{retries})")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError(f"API failed after {retries} attempts")


def _parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```\w*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)


def _summarize_single(client, company: str, text: str) -> dict:
    """Single API call for the whole transcript."""
    raw = _call(client, SINGLE_PASS_PROMPT.format(company=company, text=text[:90000]))
    return _parse_json(raw)


def _summarize_chunked(client, company: str, text: str) -> dict:
    """Multi-chunk approach for very long transcripts."""
    start = 0
    chunks = []
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        if end < len(text):
            b = text.rfind("\n\n", start, end)
            if b > start + CHUNK_SIZE // 2:
                end = b
        chunks.append(text[start:end])
        start = end - OVERLAP

    print(f"  chunking into {len(chunks)} parts...")
    notes = []
    for i, chunk in enumerate(chunks):
        print(f"  chunk {i+1}/{len(chunks)}...")
        note = _call(client, CHUNK_PROMPT.format(company=company, chunk=chunk))
        notes.append(note)

    combined = "\n\n---\n\n".join(notes)
    raw = _call(client, AGGREGATE_PROMPT.format(company=company, notes=combined[:30000]))
    return _parse_json(raw)


def _valid(data: dict) -> bool:
    required = ["tldr", "management_commentary", "guidance",
                "segment_performance", "key_metrics", "qa_highlights", "risks_and_concerns"]
    return all(k in data for k in required)


def _to_markdown(filing: dict, s: dict) -> str:
    md = f"# {filing['company']} — Earnings Call Summary\n\n"
    md += f"**Exchange:** {filing['exchange']} | **Filed:** {filing['filed_at']}  \n"
    md += f"**Source:** [{filing['pdf_url']}]({filing['pdf_url']})\n\n---\n\n"
    md += f"## TL;DR\n\n{s['tldr']}\n\n---\n\n"

    for title, key in [("Management Commentary", "management_commentary"),
                       ("Guidance & Outlook", "guidance"),
                       ("Segment Performance", "segment_performance"),
                       ("Risks & Concerns", "risks_and_concerns")]:
        md += f"## {title}\n\n"
        for item in s.get(key, []):
            md += f"- {item}\n"
        md += "\n"

    md += "## Key Metrics\n\n"
    md += "| Metric | Value | Period | Notes |\n|--------|-------|--------|-------|\n"
    for m in s.get("key_metrics", []):
        if isinstance(m, dict):
            md += f"| {m.get('metric','')} | {m.get('value','')} | {m.get('period','')} | {m.get('note','')} |\n"

    md += "\n## Analyst Q&A Highlights\n\n"
    for qa in s.get("qa_highlights", []):
        if isinstance(qa, dict):
            md += f"**Q:** {qa.get('question','')}\n\n**A:** {qa.get('answer','')}\n\n---\n\n"

    md += f"\n---\n*Generated by The AfterCall on {s.get('generated_at', '')}*\n"
    return md


def summarize(filing: dict) -> tuple[Path, Path] | None:
    text_path = Path(filing["text_path"])
    if not text_path.exists():
        print(f"[summarizer] Missing: {text_path}")
        return None

    text = text_path.read_text(encoding="utf-8")
    if len(text.strip()) < MIN_TEXT_LEN:
        print(f"[summarizer] Too short ({len(text)} chars): {filing['company']}")
        return None

    out_dir = SUMMARY_DIR / filing["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "summary.json"
    md_path = out_dir / "summary.md"

    if json_path.exists() and md_path.exists():
        print(f"[summarizer] Already done: {filing['company']}")
        return json_path, md_path

    try:
        client = _client()
    except EnvironmentError as e:
        print(f"[summarizer] {e}")
        return None

    print(f"[summarizer] {filing['company']}: {len(text):,} chars")

    try:
        if len(text) <= CHUNK_SIZE:
            data = _summarize_single(client, filing["company"], text)
        else:
            data = _summarize_chunked(client, filing["company"], text)
    except Exception as e:
        print(f"[summarizer] Failed: {e}")
        return None

    if not _valid(data):
        print(f"[summarizer] Invalid schema")
        return None

    data.update({
        "filing_id": filing["id"],
        "company": filing["company"],
        "exchange": filing["exchange"],
        "filed_at": filing["filed_at"],
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source_url": filing["pdf_url"],
    })

    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_to_markdown(filing, data), encoding="utf-8")
    print(f"[summarizer] ✓ {filing['company']}")
    return json_path, md_path
