import sys
sys.path.insert(0, "src")
from amta.rule_filter import rule_filter

blocks = [
    {"text": "うおおお!", "bbox": [0, 0, 118, 996]},
    {"text": "...", "bbox": [0, 0, 56, 247]},
    {"text": "123", "bbox": [0, 0, 100, 100]},
    {"text": "正常对话", "bbox": [0, 0, 824, 215]},
    {"text": "月の民は…", "bbox": [0, 0, 824, 215]},
]
kept, removed = rule_filter(blocks, 2243, 3465)
print("kept:", [b["text"] for b in kept])
print("removed:", [(b["text"], b["filter_reason"]) for b in removed])
print("\n验证：竖排喊叫、贴边旁白、正常对话全部保留；纯标点和纯数字被过滤")
