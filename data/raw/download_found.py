"""
Download real transcripts from the found list and add to DB.
Uses the transcripts_found.json built by find_transcripts.py.
Targets diverse sectors for a good sample.
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.downloader import download_pdf
from backend.db import init_db, filing_exists, insert_filing, update_filing

# Pick companies we want - diverse sectors from the found list
WANTED = [
    "Kalyan Jewellers India Limited",        # Retail/Jewellery
    "IndusInd Bank Limited",                 # Banking
    "Colgate Palmolive (India) Limited",     # FMCG
    "Hexagon Nutrition Limited",             # Healthcare/Nutrition
    "Siemens Limited",                       # Industrial/Engineering
    "Prince Pipes And Fittings Limited",     # Manufacturing
    "Home First Finance Company India Limited",  # NBFC/Housing Finance
    "Patanjali Foods Limited",               # FMCG
]

data = json.loads(Path('data/raw/transcripts_found.json').read_text())
print(f"Found {len(data)} transcripts in cache")

init_db()
downloaded = 0

# First do wanted companies
for wanted_name in WANTED:
    matching = [f for f in data if f['company'] == wanted_name]
    if not matching:
        print(f"Not found: {wanted_name}")
        continue
    
    filing = matching[0]
    if filing_exists(filing['id']):
        print(f"Already have: {filing['company']}")
        continue
    
    insert_filing({k: v for k, v in filing.items() if k != '_size_kb'})
    path = download_pdf(filing)
    if path:
        update_filing(filing['id'], pdf_path=str(path), status='extracted_pending')
        downloaded += 1
        print(f"Downloaded ({downloaded}): {filing['company']} ({filing.get('_size_kb', '?')}KB)")
    else:
        update_filing(filing['id'], status='failed', error='download failed')

print(f"\nDone. {downloaded} new PDFs downloaded.")
