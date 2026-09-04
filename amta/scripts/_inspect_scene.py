import sys
import json
sys.path.insert(0, 'src')
from amta.koharu_client import KoharuClient

c = KoharuClient()
c.wait_server(30)
scene = c.get_scene()
pages = scene.get('scene', {}).get('pages', {})
for pid, page in pages.items():
    print(f'Page: {pid}')
    nodes = page.get('nodes', {})
    print(f'  {len(nodes)} nodes')
    for nid, node in nodes.items():
        kind = node.get('kind', {})
        if isinstance(kind, dict):
            keys = list(kind.keys())
            print(f'  node {nid}: keys={keys}')
            for k, v in kind.items():
                if isinstance(v, dict):
                    print(f'    {k}: {json.dumps(v, ensure_ascii=False)[:300]}')
                else:
                    print(f'    {k}: {v}')
        else:
            print(f'  node {nid}: kind={kind}')
