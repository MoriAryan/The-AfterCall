"""
PDF downloader with retry and dedup logic.
"""
import time
import hashlib
import requests
from pathlib import Path

PDF_DIR = Path(__file__).parent.parent / "data" / "pdfs"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.nseindia.com/",
}


def download_pdf(filing: dict) -> Path | None:
    """
    Download the PDF for a filing. Returns the local path on success, None on failure.
    Skips if already downloaded.
    """
    PDF_DIR.mkdir(parents=True, exist_ok=True)

    # Sanitize company name for filename
    safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in filing["company"])
    safe_name = safe_name.strip().replace(" ", "_")[:50]
    filename = f"{safe_name}_{filing['id']}.pdf"
    dest = PDF_DIR / filename

    if dest.exists() and dest.stat().st_size > 1024:
        return dest

    url = filing["pdf_url"]
    for attempt in range(3):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30, stream=True)
            resp.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            if dest.stat().st_size < 1024:
                dest.unlink()
                raise ValueError("PDF too small, likely an error page")
            print(f"[download] {filing['company']} -> {dest.name}")
            return dest
        except Exception as e:
            print(f"[download] attempt {attempt+1} failed for {url}: {e}")
            if attempt < 2:
                time.sleep(2 ** attempt)

    return None
