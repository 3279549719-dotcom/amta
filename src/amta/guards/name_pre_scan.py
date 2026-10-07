"""Whole-book katakana name extraction via LLM (one-time pre-scan).

Runs ONCE per book (when no glossary.json exists yet). Feeds all OCR text
to the LLM and asks for a JSON array of {surface, translation} for every
katakana name / recurring honorific term. The result is then shown in the
GUI for human confirmation before being locked as hard pre-dict.

Note: currently extracts katakana names only. Ordinary vocabulary extraction
is a reserved extension point — the parse function already accepts any
{surface, translation} pair, so adding vocab later is just a prompt change.
"""
from __future__ import annotations

import json
import re


EXTRACTION_PROMPT = """以下是一本东方Project同人志的全部OCR文本。请提取其中所有片假名人名、固定称呼（包括"さん"、"ちゃん"等敬称结尾的称呼）。

要求：
1. 只提取人名和固定称呼，不要提取普通词汇、招式名、地名
2. 每个人名给出你建议的中文译名
3. 以 JSON 格式返回，不要有其他文字

返回格式：
{{"names": [{{"surface": "日文原文", "translation": "建议中文译名"}}]}}

OCR文本：
{text}
"""


def build_extraction_prompt(all_ocr_text: str) -> str:
    """Build the LLM prompt for name extraction."""
    return EXTRACTION_PROMPT.format(text=all_ocr_text)


def parse_extraction_response(raw: str) -> dict[str, str]:
    """Parse LLM JSON response into {surface: translation} dict.

    Tolerates markdown code fences. Returns empty dict on parse failure.
    """
    # Strip code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return {}
    names = data.get("names", [])
    result = {}
    for item in names:
        surface = (item.get("surface") or "").strip()
        translation = (item.get("translation") or "").strip()
        if surface and translation:
            result[surface] = translation
    return result
