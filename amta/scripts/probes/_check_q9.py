import json
from pathlib import Path

canon = json.loads(Path('workspace/exp-q9-remove-fill-white/artifacts/canon/page_6.json').read_text(encoding='utf-8'))
print('=== canon items ===')
for item in canon['items']:
    print(f"  {item['region_id']}: '{item['text']}'")

print()
old = json.loads(Path('workspace/exp-q9-remove-fill-white/artifacts/page_6_translation.json').read_text(encoding='utf-8'))
print('=== old translations ===')
for k, v in old['translations'].items():
    print(f'  {k}: {v}')
