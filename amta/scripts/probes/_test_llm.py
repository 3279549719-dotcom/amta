"""测试 LLM 调用是否正常。"""
import os
import sys
from pathlib import Path

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from amta.chat_client import chat_text
from amta.config import get_chat_config

cfg = get_chat_config()
print(f"base_url: {cfg.get('base_url')}")
print(f"model: {cfg.get('model')}")
print(f"api_key: {'***' if cfg.get('api_key') else 'EMPTY'}")

messages = [
    {"role": "system", "content": "你是日文→中文漫画翻译。输出严格JSON数组，不要输出额外文字。"},
    {"role": "user", "content": '将以下日文漫画内容翻译成中文。输出JSON数组，长度和顺序与输入一致。\nr1|こんにちは'},
]

try:
    raw = chat_text(cfg["base_url"], cfg["model"], messages, api_key=cfg.get("api_key"), timeout=60, temperature=0.3)
    print(f"\nLLM 返回: {repr(raw[:200])}")
except Exception as e:
    print(f"\nLLM 调用失败: {type(e).__name__}: {e}")
