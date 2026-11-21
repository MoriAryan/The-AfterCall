"""
AI summarizer using Google Gemini.

Handles long transcripts by chunking and doing a two-pass summarization:
1. Summarize each chunk into structured notes
2. Aggregate chunk notes into a final coherent summary

Always grounded in the transcript — no hallucination of figures or statements.
"""
import os
import json
import textwrap
from pathlib import Path
from datetime import datetime

import google.generativeai as genai

SUMMARY_DIR = Path(__file__).parent.parent / "data" / "summaries"

CHUNK_SIZE = 12000      # characters per chunk
OVERLAP = 500           # overlap between chunks to preserve context

SUMMARY_SCHEMA = {
    "filing_id": str,
    "company": str,
    "exchange": str,
    "filed_at": str,
    "tldr": str,
    "management_commentary": list,
    "guidance": list,
    "segment_performance": list,
    "key_metrics": list,
    "qa_highlights": list,
    "risks_and_concerns": list,
    "generated_at": str,
}

CHUNK_PROMPT = """You are analyzing a portion of an earnings conference call transcript.
Extract all important information from this chunk. Be precise and faithful to the text.
Do not invent or extrapolate any figures, statements, or facts.

Transcript chunk:
{chunk}

Extract:
1. Key management statements (quote or paraphrase faithfully)
2. Financial metrics mentioned (exact numbers only)
3. Business segment updates
4. Guidance or forward-looking statements (only if explicitly stated)
5. Analyst questions and management answers (key exchanges only)
6. Any risks, concerns, or challenges mentioned

Format as structured notes. Mark "NOT MENTIONED" for any category with no content in this chunk."""

FINAL_PROMPT = """You are creating the final summary of an earnings conference call transcript for {company}.
Below are structured notes extracted from all chunks of the transcript.

IMPORTANT RULES:
- Only include information that appears in the notes below
- Never invent financial figures, guidance numbers, or management statements
- If information is unclear or missing, say so explicitly rather than guessing
- Preserve exact financial figures as stated

Chunk notes:
{notes}

Generate a JSON response with this exact structure:
{{
  "tldr": "2-3 sentence executive summary",
  "management_commentary": ["key point 1", "key point 2", ...],
  "guidance": ["guidance item 1", ...] or ["No specific guidance was provided"],
  "segment_performance": ["segment: description", ...] or ["No segment breakdown discussed"],
  "key_metrics": [
    {{"metric": "Revenue", "value": "X", "period": "Q2 FY25", "note": "optional"}},
    ...
  ],
  "qa_highlights": [
    {{"question": "analyst question", "answer": "management response"}},
    ...
  ],
  "risks_and_concerns": ["risk 1", "risk 2", ...] or ["No risks explicitly mentioned"]
}}

Respond with valid JSON only. No markdown, no explanation."""


def _setup_gemini():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY not set in environment")
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-1.5-flash")


def _chunk_text(text: str) -> list[str]:
    if len(text) <= CHUNK_SIZE:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + CHUNK_SIZE
        # Try to break at a paragraph boundary
        if end < len(text):
            boundary = text.rfind("\n\n", start, end)
            if boundary > start + CHUNK_SIZE // 2:
                end = boundary
        chunks.append(text[start:end])
        start = end - OVERLAP

    return chunks


def _summarize_chunks(model, chunks: list[str]) -> list[str]:
    notes = []
    for i, chunk in enumerate(chunks):
        print(f"[summarizer] Processing chunk {i+1}/{len(chunks)}...")
        try:
            prompt = CHUNK_PROMPT.format(chunk=chunk)
            response = model.generate_content(prompt)
            notes.append(response.text)
        except Exception as e:
            print(f"[summarizer] Chunk {i+1} failed: {e}")
            notes.append(f"[Chunk {i+1} extraction failed: {e}]")
    return notes


def _build_final_summary(model, company: str, notes: list[str]) -> dict:
    combined_notes = "\n\n---CHUNK BOUNDARY---\n\n".join(notes)
    prompt = FINAL_PROMPT.format(company=company, notes=combined_notes[:30000])

    response = model.generate_content(prompt)
    raw = response.text.strip()

    # Strip markdown code fences if model wrapped it
    if raw.startswith("```"):
        raw = re.sub(r"^```\w*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)

    return json.loads(raw)


def _validate_summary(data: dict) -> bool:
    required = ["tldr", "management_commentary", "guidance", "segment_performance",
                "key_metrics", "qa_highlights", "risks_and_concerns"]
    return all(k in data for k in required)


def _to_markdown(filing: dict, summary: dict) -> str:
    md = f"""# {filing['company']} — Earnings Call Summary

**Exchange:** {filing['exchange']} | **Filed:** {filing['filed_at']}  
**Source:** [{filing['pdf_url']}]({filing['pdf_url']})

---

## TL;DR

{summary['tldr']}

---

## Management Commentary

"""
    for point in summary.get("management_commentary", []):
        md += f"- {point}\n"

    md += "\n## Guidance & Outlook\n\n"
    for item in summary.get("guidance", []):
        md += f"- {item}\n"

    md += "\n## Segment Performance\n\n"
    for seg in summary.get("segment_performance", []):
        md += f"- {seg}\n"

    md += "\n## Key Metrics\n\n"
    md += "| Metric | Value | Period | Notes |\n"
    md += "|--------|-------|--------|-------|\n"
    for m in summary.get("key_metrics", []):
        if isinstance(m, dict):
            md += f"| {m.get('metric','')} | {m.get('value','')} | {m.get('period','')} | {m.get('note','')} |\n"

    md += "\n## Analyst Q&A Highlights\n\n"
    for qa in summary.get("qa_highlights", []):
        if isinstance(qa, dict):
            md += f"**Q:** {qa.get('question','')}\n\n"
            md += f"**A:** {qa.get('answer','')}\n\n---\n\n"

    md += "## Risks & Concerns\n\n"
    for risk in summary.get("risks_and_concerns", []):
        md += f"- {risk}\n"

    md += f"\n\n---\n*Generated by The AfterCall on {summary.get('generated_at', '')}*\n"
    return md


def summarize(filing: dict) -> tuple[Path, Path] | None:
    """
    Summarize a filing's transcript. Returns (json_path, md_path) or None on failure.
    """
    import re  # needed in _build_final_summary closure

    text_path = Path(filing["text_path"])
    if not text_path.exists():
        print(f"[summarizer] Text file not found: {text_path}")
        return None

    text = text_path.read_text(encoding="utf-8")
    if len(text.strip()) < 200:
        print(f"[summarizer] Text too short, skipping {filing['company']}")
        return None

    out_dir = SUMMARY_DIR / filing["id"]
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "summary.json"
    md_path = out_dir / "summary.md"

    if json_path.exists() and md_path.exists():
        print(f"[summarizer] Already summarized: {filing['company']}")
        return json_path, md_path

    try:
        model = _setup_gemini()
    except EnvironmentError as e:
        print(f"[summarizer] {e}")
        return None

    chunks = _chunk_text(text)
    print(f"[summarizer] {filing['company']}: {len(text):,} chars in {len(chunks)} chunks")

    chunk_notes = _summarize_chunks(model, chunks)
    
    try:
        summary_data = _build_final_summary(model, filing["company"], chunk_notes)
    except (json.JSONDecodeError, Exception) as e:
        print(f"[summarizer] Final summary failed for {filing['company']}: {e}")
        return None

    if not _validate_summary(summary_data):
        print(f"[summarizer] Invalid summary schema for {filing['company']}")
        return None

    # Enrich with metadata
    summary_data["filing_id"] = filing["id"]
    summary_data["company"] = filing["company"]
    summary_data["exchange"] = filing["exchange"]
    summary_data["filed_at"] = filing["filed_at"]
    summary_data["generated_at"] = datetime.utcnow().isoformat() + "Z"
    summary_data["source_url"] = filing["pdf_url"]

    json_path.write_text(json.dumps(summary_data, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_to_markdown(filing, summary_data), encoding="utf-8")

    print(f"[summarizer] Done: {filing['company']}")
    return json_path, md_path
