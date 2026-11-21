import json
data = json.loads(open('data/raw/transcripts_found.json').read())
data.sort(key=lambda x: x.get('_size_kb', 0), reverse=True)
for d in data[:15]:
    print(d['company'], '|', d.get('_size_kb', 0), 'KB')
