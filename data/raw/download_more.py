import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.downloader import download_pdf
from backend.db import init_db, filing_exists, insert_filing, update_filing

WANTED = [
    "Allcargo Global Limited",
    "DOMS Industries Limited",
    "Avanti Feeds Limited",
    "Vaibhav Global Limited",
    "Archean Chemical Industries Limited",
    "Dishman Carbogen Amcis Limited",
    "GE Power India Limited",
]

data = json.loads(Path('data/raw/transcripts_found.json').read_text())
init_db()
downloaded = 0

for name in WANTED:
    matching = [f for f in data if f['company'] == name]
    if not matching:
        print(f"Not found: {name}")
        continue
    filing = matching[0]
    if filing_exists(filing['id']):
        print(f"Already have: {filing['company']}")
        continue
    clean = {k: v for k, v in filing.items() if k != '_size_kb'}
    insert_filing(clean)
    path = download_pdf(clean)
    if path:
        update_filing(filing['id'], pdf_path=str(path), status='extracted_pending')
        downloaded += 1
        print(f"Downloaded ({downloaded}): {filing['company']}")
    else:
        update_filing(filing['id'], status='failed', error='download failed')

print(f"Done. {downloaded} downloaded.")
