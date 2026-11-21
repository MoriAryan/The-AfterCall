"""
PDF text extractor.
Primary: pdfplumber for clean digital PDFs.
Fallback: pytesseract OCR for scanned pages.

Cleans headers, footers, page numbers, and formatting noise
while preserving speaker names and financial figures.
"""
import re
import pdfplumber
from pathlib import Path

from backend.db import resolve_path

TEXT_DIR = Path(__file__).parent.parent / "data" / "texts"

# Lines that are almost certainly boilerplate to drop
_BOILERPLATE = re.compile(
    r"^\s*(page\s+\d+\s*(of\s*\d+)?|confidential|safe\s+harbor|forward.looking|"
    r"www\.\S+|©|\d{1,2}/\d{1,2}/\d{2,4}|\d+\s*$)\s*$",
    re.IGNORECASE,
)

# Speaker pattern: "John Doe: " or "ANALYST:" at the start of a line
_SPEAKER = re.compile(r"^[A-Z][A-Za-z .,'-]{2,40}:\s+")


def _clean_page(text: str) -> str:
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _BOILERPLATE.match(stripped):
            continue
        cleaned.append(stripped)
    return "\n".join(cleaned)


def extract_text(pdf_path: Path) -> str | None:
    """
    Extract text from a PDF. Returns clean text or None on failure.
    Tries OCR on pages with very little extractable text.
    """
    try:
        pages = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text(x_tolerance=2, y_tolerance=2) or ""
                if len(text.strip()) < 50:
                    text = _ocr_page(page, i)
                cleaned = _clean_page(text)
                if cleaned:
                    pages.append(cleaned)

        full_text = "\n\n".join(pages)
        full_text = _remove_repeated_headers(full_text)
        return full_text if full_text.strip() else None

    except Exception as e:
        print(f"[extract] Failed for {pdf_path.name}: {e}")
        return None


def _ocr_page(page, page_num: int) -> str:
    """OCR fallback using pytesseract."""
    try:
        import pytesseract
        from PIL import Image
        import io

        img = page.to_image(resolution=200).original
        return pytesseract.image_to_string(img)
    except Exception as e:
        print(f"[extract] OCR failed on page {page_num}: {e}")
        return ""


def _remove_repeated_headers(text: str) -> str:
    """
    Detect lines that appear frequently (likely headers/footers) and remove them.
    Only removes lines shorter than 100 chars that appear 3+ times.
    """
    lines = text.splitlines()
    from collections import Counter
    counts = Counter(l.strip() for l in lines if l.strip() and len(l.strip()) < 100)
    repeated = {line for line, count in counts.items() if count >= 3}
    if not repeated:
        return text
    cleaned = [l for l in lines if l.strip() not in repeated]
    return "\n".join(cleaned)


def extract_and_save(filing: dict) -> Path | None:
    """Extract text from a filing's PDF and save to data/texts/."""
    pdf_path = resolve_path(filing["pdf_path"])
    if not pdf_path.exists():
        print(f"[extract] PDF not found: {pdf_path}")
        return None

    TEXT_DIR.mkdir(parents=True, exist_ok=True)
    text_path = TEXT_DIR / f"{filing['id']}.txt"

    if text_path.exists() and text_path.stat().st_size > 100:
        return text_path

    text = extract_text(pdf_path)
    if not text:
        return None

    text_path.write_text(text, encoding="utf-8")
    print(f"[extract] {filing['company']}: {len(text):,} chars -> {text_path.name}")
    return text_path
