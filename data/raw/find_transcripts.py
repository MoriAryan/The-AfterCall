"""
Find actual transcript PDFs (not just meeting schedule notices).
NSE files both: a brief notice when meeting is scheduled, and the actual transcript after.
Transcripts are significantly larger files (>100KB typically).
"""
import sys, json, hashlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.nse import _get_session, _parse_filing
from datetime import datetime, timedelta
import time

# Real transcripts are PDFs with actual call content -- much larger than notices
MIN_TRANSCRIPT_SIZE_KB = 80  # kb, to filter out 1-page cover letters

def discover_real_transcripts(days_back=14, max_results=20):
    import requests
    
    session = _get_session()
    today = datetime.now()
    
    found = []
    seen_ids = set()
    
    for start in range(0, days_back, 7):
        end = min(start + 7, days_back)
        date_to = (today - timedelta(days=start)).strftime("%d-%m-%Y")
        date_from = (today - timedelta(days=end)).strftime("%d-%m-%Y")
        
        try:
            resp = session.get(
                'https://www.nseindia.com/api/corporate-announcements',
                params={'index': 'equities', 'from_date': date_from, 'to_date': date_to},
                timeout=20
            )
            data = resp.json()
        except Exception as e:
            print(f"Error fetching {date_from}-{date_to}: {e}")
            continue

        for item in data:
            if item.get('desc') != 'Analysts/Institutional Investor Meet/Con. Call Updates':
                continue
            
            # Check file size field - NSE provides this in the response
            size_str = item.get('attFileSize', '') or ''
            # size is like "175.72 KB" or "1.26 MB"
            try:
                parts = size_str.strip().split()
                if len(parts) == 2:
                    val = float(parts[0])
                    unit = parts[1].upper()
                    size_kb = val * 1024 if unit == 'MB' else val
                else:
                    size_kb = 0
            except:
                size_kb = 0
            
            # Only keep large files - actual transcripts
            if size_kb < MIN_TRANSCRIPT_SIZE_KB:
                continue
            
            filing = _parse_filing(item)
            if filing and filing['id'] not in seen_ids:
                seen_ids.add(filing['id'])
                filing['_size_kb'] = round(size_kb, 1)
                found.append(filing)
                print(f"  TRANSCRIPT: {filing['company']} | {size_kb:.0f}KB | {item.get('an_dt','')}")
                
                if len(found) >= max_results:
                    return found
        
        time.sleep(1)
    
    return found

if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 14
    max_r = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    results = discover_real_transcripts(days, max_r)
    print(f"\nFound {len(results)} real transcript filings")
    with open('data/raw/transcripts_found.json', 'w') as f:
        json.dump(results, f, indent=2)
