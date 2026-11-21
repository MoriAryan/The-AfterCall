import sys, json
sys.path.insert(0,'.')
from ingestion.nse import _get_session, CONCALL_DESC
from datetime import datetime, timedelta

s = _get_session()
today = datetime.now()
found = []
seen_urls = set()

for days_back in [7, 14, 30, 60]:
    date_from = (today - timedelta(days=days_back)).strftime('%d-%m-%Y')
    date_to = today.strftime('%d-%m-%Y')
    try:
        r = s.get(
            'https://www.nseindia.com/api/corporate-announcements',
            params={'index':'equities','from_date':date_from,'to_date':date_to},
            timeout=20
        )
        data = r.json()
        matches = [x for x in data if x.get('desc') == CONCALL_DESC]
        print(f'days_back={days_back}: total={len(data)}, concall={len(matches)}')
        for m in matches:
            url = m.get('attchmntFile','')
            if url and url not in seen_urls:
                seen_urls.add(url)
                found.append(m)
                print(f'  -> {m.get("sm_name")} | {m.get("an_dt")}')
    except Exception as e:
        print(f'days_back={days_back} error: {e}')

print(f'Total unique concall filings: {len(found)}')
