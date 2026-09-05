import json

for page in [11, 12, 13, 14, 15]:
    d = json.load(open(f'amta/workspace/touhou-e2e-orchestrator/artifacts/page_{page}_detection.json', encoding='utf-8'))
    print(f'p{page}: source={d.get("source", "N/A")}, page={d.get("page", "N/A")}, n_boxes={d.get("n_boxes", "N/A")}')
    blocks = d.get('blocks', [])
    if blocks:
        print(f'  first block bbox={blocks[0].get("bbox")}, type={blocks[0].get("bubble_type")}')
