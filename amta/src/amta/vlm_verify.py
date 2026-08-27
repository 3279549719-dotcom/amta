"""VLM contact sheet 批量校验模块。

把所有 crop 图拼成 contact sheet，送 DeepSeek vision 做批量转写。
配置：thinking=disabled, detail=low（probe B 组验证最优，2-3s/页）。
输出：按输入顺序对应的转写文本列表。

Refs ADR-023 Stage 2 双引擎会诊。
"""
from __future__ import annotations

import base64
import io
import time
from typing import Optional

import requests
from PIL import Image


def make_contact_sheet(
    crops: list[Image.Image],
    cols: int = 3,
    pad: int = 12,
    bg: tuple = (255, 255, 255),
) -> Image.Image:
    """把 crop 图列表拼成网格 contact sheet。

    Args:
        crops: PIL Image 列表
        cols: 列数
        pad: 图片间距
        bg: 背景色

    Returns:
        拼接后的 PIL Image
    """
    if not crops:
        return Image.new("RGB", (10, 10), bg)

    rows = (len(crops) + cols - 1) // cols

    # 统一缩放到相同宽度（保持比例）
    target_w = max(c.width for c in crops)
    normalized: list[Image.Image] = []
    for c in crops:
        if c.width != target_w:
            ratio = target_w / c.width
            new_h = int(c.height * ratio)
            c = c.resize((target_w, new_h), Image.LANCZOS)
        normalized.append(c)

    cell_w = target_w + pad * 2
    cell_h = max(c.height for c in normalized) + pad * 2
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), bg)

    for i, c in enumerate(normalized):
        r, col = divmod(i, cols)
        x = col * cell_w + pad
        y = r * cell_h + pad
        sheet.paste(c, (x, y))

    return sheet


def parse_vlm_output(raw: str, expected_count: int) -> Optional[list[str]]:
    """解析 VLM 输出，按行对应输入顺序。

    Args:
        raw: VLM 原始输出文本
        expected_count: 预期的行数（与 crop 数量一致）

    Returns:
        文本列表（长度=expected_count），或 None（数量不符时触发容错）
    """
    lines = [line.strip() for line in raw.strip().split("\n")]
    if len(lines) != expected_count:
        return None
    return lines


def vlm_verify_batch(
    crops: list[Image.Image],
    api_key: str,
    model: str = "deepseek-v4-flash-vision-exp",
    base_url: str = "https://api.deepseek.com/chat/completions",
    max_retries: int = 2,
    timeout: int = 60,
) -> dict:
    """VLM contact sheet 批量校验主函数。

    Args:
        crops: crop 图列表
        api_key: DeepSeek API key
        model: VLM 模型名
        base_url: API 端点
        max_retries: 最大重试次数
        timeout: 单次调用超时（秒）

    Returns:
        {
            "texts": list[str] | None,  # 转写文本列表，失败时为 None
            "status": "ok" | "failed" | "count_mismatch",
            "raw_output": str,
            "elapsed": float,
            "retries": int,
        }
    """
    sheet = make_contact_sheet(crops)
    buf = io.BytesIO()
    sheet.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    prompt = (
        f"这是一页漫画的 {len(crops)} 个文字区域截图，按从左到右、从上到下的网格顺序排列。"
        f"请逐个转写每个区域中的日文文字，直接输出每行一个区域的转写结果，共 {len(crops)} 行。"
        f"如果某个区域没有文字，输出空行。不要输出编号、解释或其他内容。"
    )

    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{img_b64}",
                            "detail": "low",
                        },
                    },
                ],
            }
        ],
        "max_tokens": 4000,
        "temperature": 0.1,
        "extra_body": {"thinking": {"type": "disabled"}},
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(max_retries + 1):
        t0 = time.time()
        try:
            resp = requests.post(base_url, json=payload, headers=headers, timeout=timeout)
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            elapsed = time.time() - t0
            texts = parse_vlm_output(raw, len(crops))
            if texts is not None:
                return {
                    "texts": texts,
                    "status": "ok",
                    "raw_output": raw,
                    "elapsed": elapsed,
                    "retries": attempt,
                }
            else:
                # 数量不符，重试
                if attempt < max_retries:
                    time.sleep(2)
                    continue
                return {
                    "texts": None,
                    "status": "count_mismatch",
                    "raw_output": raw,
                    "elapsed": elapsed,
                    "retries": attempt,
                }
        except Exception as e:
            elapsed = time.time() - t0
            if attempt < max_retries:
                time.sleep(2)
                continue
            return {
                "texts": None,
                "status": "failed",
                "raw_output": str(e),
                "elapsed": elapsed,
                "retries": attempt,
            }
