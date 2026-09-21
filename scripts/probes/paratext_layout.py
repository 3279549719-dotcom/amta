"""Experimental visual reading contract. No book/page-specific decisions."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw

from amta.backends.chat_client import chat
from amta.common.config import get_dashscope_key

PROMPT = """Read the supplied manga page and its numbered text crops. The full page gives context;
each crop is the authoritative content for its region. Transcribe all Japanese exactly, do not translate.
Observe typography visually, never infer boldness from exclamation marks or direction from box aspect ratio.
Return JSON {"regions": [{"region_id": "r00", "text": "...", "source_lines": ["..."],
"direction": "horizontal", "align": "center", "font": "sans", "background": "paper"}]}.
Include EVERY supplied region_id, empty text only for genuinely unreadable/non-text art.
source_lines: the original printed lines (or vertical columns in reading order).
text: join soft line wraps into coherent paragraphs, keep meaningful paragraph breaks as newline.
For title/date/event and credit/contact fields preserve distinct lines with newline.
direction: horizontal or vertical, following the actual characters' reading direction.
align: left, center, right, as observed in the source.
font: sans, serif, handwritten, bold, based only on visible glyphs.
background: paper for plain paper/white panel, artwork when text overlaps art/texture.
Do not include anything outside the region. Do not invent missing content.
Detection crops can overlap. Assign each physical text exactly once to the crop that shows it
most completely. Ignore clipped fragments of a neighbouring line already fully visible in another crop.
Use the full page to resolve ownership and restore the correct reading order, never duplicate fragments.
"""


def validate_regions(blocks: list[dict], size: tuple[int, int]) -> None:
    seen = set()
    for b in blocks:
        rid = b["region_id"]
        if rid in seen:
            raise ValueError(f"duplicate region {rid}")
        seen.add(rid)
        x1, y1, x2, y2 = b["bbox"]
        if not (0 <= x1 < x2 <= size[0] and 0 <= y1 < y2 <= size[1]):
            raise ValueError(f"{rid}: bbox outside current image {size}: {b['bbox']}")


def image_part(img: Image.Image, max_side: int = 2200) -> dict:
    img = img.copy().convert("RGB")
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return {"type": "image_url", "image_url": {
        "url": "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")}}


def exclusive_crop(img: Image.Image, region: dict, blocks: list[dict]) -> Image.Image:
    """Assign overlapping pixels to the smallest containing detection rectangle."""
    x1, y1, x2, y2 = region["bbox"]
    crop = img.crop((x1, y1, x2, y2))
    area = (x2-x1)*(y2-y1)
    for other in blocks:
        a, b, c, d = other["bbox"]
        other_area = (c-a)*(d-b)
        if (other_area, other["region_id"]) >= (area, region["region_id"]):
            continue
        left, top, right, bottom = max(a,x1), max(b,y1), min(c,x2), min(d,y2)
        if left < right and top < bottom:
            ImageDraw.Draw(crop).rectangle((left-x1,top-y1,right-x1-1,bottom-y1-1), fill="white")
    return crop


def parse_json(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("expected JSON object")
    return data


def read_layout(raw: Path, blocks: list[dict], cached: dict | None = None) -> dict:
    img = Image.open(raw).convert("RGB")
    validate_regions(blocks, img.size)
    model = os.environ.get("VISION_MODEL", "qwen3.5-omni-plus")
    endpoint = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    signature = hashlib.sha256(raw.read_bytes() + json.dumps(blocks, sort_keys=True).encode()
                               + PROMPT.encode() + model.encode() + endpoint.encode() + b"exclusive-crops-v1").hexdigest()
    if cached and cached.get("request_sha256") == signature:
        return cached
    content = [{"type": "text", "text": "Full page for context:"}, image_part(img)]
    for b in blocks:
        content.extend([{"type": "text", "text": f"Crop {b['region_id']} (read only this crop):"},
                        image_part(exclusive_crop(img, b, blocks))])
    response = chat(endpoint,
                    model, [{"role": "system", "content": PROMPT}, {"role": "user", "content": content}],
                    api_key=get_dashscope_key(), timeout=240, temperature=0.1, max_tokens=14000)
    data = parse_json(response.get("content", ""))
    regions = data.get("regions", [])
    if len(regions) != len(blocks) or {r["region_id"] for r in regions} != {b["region_id"] for b in blocks}:
        raise ValueError("VLM region coverage mismatch")
    by_id = {b["region_id"]: b for b in blocks}
    for r in regions:
        if r.get("direction") not in ("horizontal", "vertical"):
            raise ValueError("invalid reading direction")
        if r.get("align") not in ("left", "center", "right"):
            raise ValueError("invalid alignment")
        if r.get("font") not in ("sans", "serif", "handwritten", "bold"):
            raise ValueError("invalid font observation")
        if not isinstance(r.get("text"), str) or not isinstance(r.get("source_lines"), list):
            raise ValueError("invalid transcription")
        r["bbox"] = by_id[r["region_id"]]["bbox"]
    return {"regions": regions, "image_size": list(img.size), "source_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
            "model": model, "endpoint": endpoint, "request_sha256": signature, "raw_response": response.get("content", "")}
