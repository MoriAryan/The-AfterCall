"""
AI summarizer using Google Gemini (google-genai SDK).

For transcripts under 50K chars we do a single-pass summarization.
For longer ones we chunk. Free tier: 15 req/min on 3.5-flash-lite.
"""
import os
import json
import re
import time
from pathlib import Path
from datetime import datetime
from backend.db import resolve_path

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
  "tldr": ["Concise executive-summary point 1", "Concise executive-summary point 2"],
  "management_commentary": ["key management point 1", "key point 2", "..."],
  "guidance": ["specific guidance given"] or ["No specific guidance was provided in this call"],
  "segment_performance": [{{"segment": "segment name", "notes": "performance detail"}}],
  "key_metrics": [
    {{"metric": "metric name", "value": "exact value with units", "context": "period and other context"}}
  ],
  "notable_qa": [
    {{"question": "analyst question", "answer": "management response summary", "asked_by": "analyst name or empty string"}}
  ],
  "risks": ["risk 1", "risk 2"] or ["No specific risks mentioned"]
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
  "tldr": ["Concise executive-summary point 1", "Concise executive-summary point 2"],
  "management_commentary": ["point 1", "..."],
  "guidance": ["guidance item"] or ["No specific guidance provided"],
  "segment_performance": [{{"segment": "...", "notes": "..."}}],
  "key_metrics": [{{"metric": "...", "value": "...", "context": "..."}}],
  "notable_qa": [{{"question": "...", "answer": "...", "asked_by": "..."}}],
  "risks": ["risk 1"] or ["No risks mentioned"]
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
                config=types.GenerateContentConfig(
                    temperature=0.1,
                    response_mime_type="application/json",
                ),
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
        if end == len(text):
            break
        start = max(start + 1, end - OVERLAP)

    print(f"  chunking into {len(chunks)} parts...")
    notes = []
    for i, chunk in enumerate(chunks):
        print(f"  chunk {i+1}/{len(chunks)}...")
        note = _call(client, CHUNK_PROMPT.format(company=company, chunk=chunk))
        notes.append(note)

    combined = "\n\n---\n\n".join(notes)
    raw = _call(client, AGGREGATE_PROMPT.format(company=company, notes=combined))
    return _parse_json(raw)


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def normalize_summary(data: dict) -> dict:
    """Convert model output and older prompt aliases to the assignment schema."""
    data["tldr"] = _as_list(data.get("tldr"))
    for key in ("management_commentary", "guidance", "segment_performance",
                "key_metrics", "notable_qa", "risks"):
        aliases = {
            "notable_qa": "qa_highlights",
            "risks": "risks_and_concerns",
        }
        data[key] = _as_list(data.get(key, data.get(aliases.get(key, ""))))

    segments = []
    for segment in data["segment_performance"]:
        if isinstance(segment, dict):
            segments.append({
                "segment": str(segment.get("segment", "")),
                "notes": str(segment.get("notes", segment.get("performance", ""))),
            })
        else:
            name, separator, notes = str(segment).partition(":")
            segments.append({
                "segment": name.strip() if separator else "",
                "notes": notes.strip() if separator else str(segment),
            })
    data["segment_performance"] = segments

    metrics = []
    for metric in data["key_metrics"]:
        if not isinstance(metric, dict):
            continue
        context = metric.get("context")
        if context is None:
            context = " — ".join(
                str(value) for value in (metric.get("period"), metric.get("note"))
                if value
            )
        metrics.append({
            "metric": str(metric.get("metric", "")),
            "value": str(metric.get("value", "")),
            "context": str(context),
        })
    data["key_metrics"] = metrics

    qa = []
    for item in data["notable_qa"]:
        if isinstance(item, dict):
            qa.append({
                "question": str(item.get("question", "")),
                "answer": str(item.get("answer", "")),
                "asked_by": str(item.get("asked_by", "")),
            })
    data["notable_qa"] = qa
    data.pop("qa_highlights", None)
    data.pop("risks_and_concerns", None)
    return data


def transcript_metadata(filing: dict, text: str) -> dict:
    scrip_code = re.search(
        r"\bBSE\s*Scrip\s*Code\s*[:\-]\s*([0-9]{5,6})", text, re.IGNORECASE
    )
    nse_symbol = re.search(
        r"\bNSE\s*Symbol\s*[:\-]\s*([A-Z0-9&.-]+)", text, re.IGNORECASE
    )
    quarter = re.search(
        r"\bQ[1-4](?:\s*(?:&|and)\s*H[1-2])?\s*FY\s*\d{2,4}\b",
        text,
        re.IGNORECASE,
    )
    call_date = ""
    date_match = re.search(
        r"\bheld\s+on\s+([A-Za-z]+\s+\d{1,2},?\s+\d{4})",
        text,
        re.IGNORECASE,
    )
    if date_match:
        date_text = date_match.group(1).replace(",", "")
        for date_format in ("%B %d %Y", "%b %d %Y"):
            try:
                call_date = datetime.strptime(date_text, date_format).date().isoformat()
                break
            except ValueError:
                continue

    return {
        "scrip_code": scrip_code.group(1) if scrip_code else "",
        "nse_symbol": nse_symbol.group(1) if nse_symbol else str(filing.get("symbol") or ""),
        "quarter": re.sub(r"\s+", " ", quarter.group(0)).upper() if quarter else "",
        "call_date": call_date,
    }


def _valid(data: dict) -> bool:
    required = {
        "tldr": list,
        "management_commentary": list,
        "guidance": list,
        "segment_performance": list,
        "key_metrics": list,
        "notable_qa": list,
        "risks": list,
    }
    return (
        all(isinstance(data.get(key), expected) for key, expected in required.items())
        and bool(data["tldr"])
    )


def _has_summary_fields(data: dict) -> bool:
    required = {
        "tldr",
        "management_commentary",
        "guidance",
        "segment_performance",
        "key_metrics",
    }
    return (
        required.issubset(data)
        and ("notable_qa" in data or "qa_highlights" in data)
        and ("risks" in data or "risks_and_concerns" in data)
    )


def _to_markdown(filing: dict, s: dict) -> str:
    md = f"# {filing['company']} — Earnings Call Summary\n\n"
    md += f"**Exchange:** {filing['exchange']} | **Filed:** {filing['filed_at']}  \n"
    md += f"**Quarter:** {s.get('quarter') or 'Not identified'} | "
    md += f"**Call date:** {s.get('call_date') or 'Not identified'}  \n"
    md += f"**Source:** [{filing['pdf_url']}]({filing['pdf_url']})\n\n---\n\n"
    md += "## TL;DR\n\n"
    md += "".join(f"- {item}\n" for item in s["tldr"]) + "\n---\n\n"

    for title, key in [("Management Commentary", "management_commentary"),
                       ("Guidance & Outlook", "guidance"),
                       ("Risks & Concerns", "risks")]:
        md += f"## {title}\n\n"
        for item in s.get(key, []):
            md += f"- {item}\n"
        md += "\n"

    md += "## Segment Performance\n\n"
    for item in s["segment_performance"]:
        md += f"- **{item['segment'] or 'Segment'}:** {item['notes']}\n"
    md += "\n"

    md += "## Key Metrics\n\n"
    md += "| Metric | Value | Context |\n|--------|-------|---------|\n"
    for m in s.get("key_metrics", []):
        if isinstance(m, dict):
            md += f"| {m.get('metric','')} | {m.get('value','')} | {m.get('context','')} |\n"

    md += "\n## Analyst Q&A Highlights\n\n"
    for qa in s.get("notable_qa", []):
        if isinstance(qa, dict):
            asked_by = f" ({qa['asked_by']})" if qa.get("asked_by") else ""
            md += f"**Q{asked_by}:** {qa.get('question','')}\n\n"
            md += f"**A:** {qa.get('answer','')}\n\n---\n\n"

    md += f"\n---\n*Generated by The AfterCall on {s.get('generated_at', '')}*\n"
    return md


def summarize(filing: dict) -> tuple[Path, Path] | None:
    text_path = resolve_path(filing["text_path"])
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

    if not isinstance(data, dict) or not _has_summary_fields(data):
        print("[summarizer] Invalid schema")
        return None
    data = normalize_summary(data)
    if not _valid(data):
        print(f"[summarizer] Invalid schema")
        return None

    data.update(transcript_metadata(filing, text))
    data.update({
        "filing_id": filing["id"],
        "company": filing["company"],
        "source": filing["exchange"],
        "exchange": filing["exchange"],
        "filed_at": filing["filed_at"],
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "source_url": filing["pdf_url"],
    })

    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_to_markdown(filing, data), encoding="utf-8")
    print(f"[summarizer] ✓ {filing['company']}")
    return json_path, md_path
