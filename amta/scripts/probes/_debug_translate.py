"""调试 translate_plain 批量调用。"""
import os
import sys
import json
from pathlib import Path

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from amta.translate import translate_plain, parse_translation_array
from amta.guardrails import mechanical_guardrails
from amta.chat_client import chat_text
from amta.config import get_chat_config

# 加载目标框数据
data = json.loads(open("workspace/exp-q1-tiling-garbled/q1_target_audit/q1_target_boxes.json", encoding="utf-8").read())

# 取第一批 5 个
batch_data = data[:5]
canon = [{"region_id": f"p{b['page']}_{b['region_id']}", "text": b["ocr_text"]} for b in batch_data]
print("=== 第一批输入 ===")
for c in canon:
    print(f"  {c['region_id']}: '{c['text'][:30]}'")

# 直接调用 LLM
cfg = get_chat_config()
def llm(messages):
    return chat_text(cfg["base_url"], cfg["model"], messages, api_key=cfg.get("api_key"), timeout=180, temperature=0.3)

system_extra = "如果输入内容是乱码、无法识别的字符或非日文常用文字，输出空字符串。"
system = f"你是日文→中文漫画翻译。输出严格JSON数组，不要输出额外文字。\n{system_extra}".strip()

instr = '将以下日文漫画内容翻译成中文。输出JSON数组，长度和顺序与输入一致。\n'
blocks = [f"{c['region_id']}|{c['text']}" for c in canon]
user_content = instr + "\n".join(blocks)

print("\n=== 调用 LLM ===")
messages = [
    {"role": "system", "content": system},
    {"role": "user", "content": user_content},
]
raw = llm(messages)
print(f"raw output: {repr(raw[:500])}")

print("\n=== parse_translation_array ===")
arr = parse_translation_array(raw, len(canon))
print(f"arr: {arr}")

if arr is not None:
    parsed = {c["region_id"]: arr[i] for i, c in enumerate(canon)}
    print(f"\n=== parsed ===")
    for k, v in parsed.items():
        print(f"  {k}: '{v}'")

    print(f"\n=== mechanical_guardrails ===")
    problems = mechanical_guardrails(canon, parsed)
    print(f"problems: {problems}")

print("\n=== translate_plain 直接调用 ===")
result = translate_plain(canon, llm, system_extra=system_extra, context_enabled=False, max_retries=0)
for k, v in result.items():
    print(f"  {k}: '{v}'")
