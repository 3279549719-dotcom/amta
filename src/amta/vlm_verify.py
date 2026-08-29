"""VLM contact sheet 批量校验模块。

把所有 crop 图拼成 contact sheet,送 DeepSeek vision 做批量转写。
配置:thinking=disabled, detail=low(probe B 组验证最优,2-3s/页)。
输出:按输入顺序对应的转写文本列表。

Refs ADR-023 Stage 2 双引擎会诊。
"""
from __future__ import annotations

import base64
import io
import json
import re
import time
from typing import Optional

import requests
from PIL import Image


def make_contact_sheet(
    crops: list[Image.Image],
    cols: int = 4,
    pad: int = 12,
    bg: tuple = (255, 255, 255),
    max_cell_h: int = 320,
    max_side: int = 4000,
    draw_index: bool = True,
) -> Image.Image:
    """把 crop 图列表拼成网格 contact sheet,每个 crop 左上角画序号徽章。

    VLM 按图上编号转写(不依赖位置),避开宽窄不一导致的视觉顺序错位。

    Args:
        crops: PIL Image 列表
        cols: 列数
        pad: 图片间距
        bg: 背景色
        max_cell_h: 单个 crop 归一化后的最大高度(竖排长条先缩到该高,防 sheet 超长)
        max_side: 最终 sheet 最长边上限(超出则整体等比缩放,DeepSeek 拒超长图)
        draw_index: 是否在左上角画序号徽章

    Returns:
        拼接后的 PIL Image
    """
    if not crops:
        return Image.new("RGB", (10, 10), bg)

    normalized: list[Image.Image] = []
    for c in crops:
        if c.height > max_cell_h:
            ratio = max_cell_h / c.height
            c = c.resize((max(1, int(c.width * ratio)), max_cell_h), Image.Resampling.LANCZOS)
        normalized.append(c)

    if draw_index:
        from PIL import ImageDraw, ImageFont

        try:
            font = ImageFont.truetype("arial.ttf", 26)
        except Exception:
            font = ImageFont.load_default(size=26)
        tagged: list[Image.Image] = []
        for i, c in enumerate(normalized):
            tagged_img = c.copy()
            d = ImageDraw.Draw(tagged_img)
            label = str(i + 1)
            bbox = d.textbbox((0, 0), label, font=font)
            tw, th = bbox[2] - bbox[0] + 10, bbox[3] - bbox[1] + 8
            d.rectangle([0, 0, tw, th], fill=(20, 90, 200))
            d.text((5, 3), label, fill=(255, 255, 255), font=font)
            tagged.append(tagged_img)
        normalized = tagged

    # 逐行拼: cell 高度按行内最大(修复全局最大高度导致的超长 sheet)
    row_heights: list[int] = []
    row_imgs: list[list[Image.Image]] = []
    for i in range(0, len(normalized), cols):
        row = normalized[i : i + cols]
        row_imgs.append(row)
        row_heights.append(max(c.height for c in row))

    sheet_w = max(sum(c.width + pad * 2 for c in row) for row in row_imgs)
    sheet_h = sum(h + pad * 2 for h in row_heights)
    sheet = Image.new("RGB", (sheet_w, sheet_h), bg)

    y = 0
    for row, rh in zip(row_imgs, row_heights):
        x = 0
        for c in row:
            sheet.paste(c, (x + pad, y + pad))
            x += c.width + pad * 2
        y += rh + pad * 2

    # 最终保护: 最长边超限则整体缩放
    if max(sheet.size) > max_side:
        ratio = max_side / max(sheet.size)
        sheet = sheet.resize(
            (max(1, int(sheet.width * ratio)), max(1, int(sheet.height * ratio))),
            Image.Resampling.LANCZOS,
        )

    return sheet


def parse_vlm_output(raw: str, expected_count: int) -> Optional[list[str]]:
    """解析 VLM 输出,按序号前缀对应输入顺序。

    优先解析「序号: 文本」格式(序号 1 基,与网格顺序对应);长气泡的内部换行
    已由 prompt 要求折叠为空格。无编号时回退纯行模式(行数必须恰好相等)。

    Args:
        raw: VLM 原始输出文本
        expected_count: 预期的区域数量(与 crop 数量一致)

    Returns:
        文本列表(长度=expected_count),或 None(解析失败触发容错)
    """
    texts: list[Optional[str]] = [None] * expected_count
    found = 0
    for line in raw.strip().splitlines():
        m = re.match(r"^\s*(\d{1,3})\s*[:：、.]\s*(.*)$", line)
        if m:
            idx = int(m.group(1)) - 1
            if 0 <= idx < expected_count and texts[idx] is None:
                texts[idx] = m.group(2).strip()
                found += 1
    if found == expected_count and all(t is not None for t in texts):
        return texts  # type: ignore[return-value]
    # 兜底: 无编号纯行模式(行数恰好相等才接受)
    lines = [line.strip() for line in raw.strip().split("\n")]
    if len(lines) == expected_count:
        return lines
    return None


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
        timeout: 单次调用超时(秒)

    Returns:
        {
            "texts": list[str] | None,  # 转写文本列表,失败时为 None
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
        f"这是一页漫画的 {len(crops)} 个文字区域截图,每个区域的左上角有蓝色数字编号(1~{len(crops)})。"
        f"请按编号逐个转写对应区域中的日文文字,输出恰好 {len(crops)} 行,每行格式为「编号: 转写文本」"
        f"(例如 1: こんにちは)。区域内部的换行用空格连接成一行;如果某个区域没有文字或编号不清,"
        f"该行冒号后留空。除这 {len(crops)} 行外不要输出任何其他内容。"
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
        "max_tokens": 8000,
        "temperature": 0.1,
        "thinking": {"type": "disabled"},
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
                # 数量不符,重试
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
    # 不可达(最后一次 attempt 必然 return); pyright 要求全路径返回
    return {
        "texts": None,
        "status": "failed",
        "raw_output": "unreachable",
        "elapsed": 0.0,
        "retries": max_retries,
    }


def vlm_verify_ocr_single(
    crop_image: Image.Image,
    baberu_text: str,
    api_key: str,
    model: str = "deepseek-v4-flash-vision-exp",
    base_url: str = "https://api.deepseek.com/chat/completions",
    max_retries: int = 1,
    timeout: int = 30,
) -> dict:
    """单图 OCR 验证：VLM 看 crop 图 + baberu_text，判断 OCR 是否正确，返回视觉信息。

    与 vlm_verify_batch（contact sheet 批量转写）的关键区别：
    - 单图高清（detail=high），VLM 能看清小字
    - 任务是"验证 + 分类"，不是"重新转写"——VLM 不需要从零转写，只需判断 baberu 结果是否正确
    - 输出结构化 JSON，不是纯文本列表
    - 看不清时允许返回 uncertain，不强迫编造（这是与批量转写的核心差异）

    Args:
        crop_image: 单个 crop 的 PIL Image
        baberu_text: Baberu OCR 出的文本（待验证）
        api_key: DeepSeek API key
        model: VLM 模型名
        base_url: API 端点
        max_retries: 最大重试次数
        timeout: 单次调用超时（秒）

    Returns:
        {
            "ocr_correct": "correct" | "incorrect" | "partial" | "uncertain",
            "corrected_text": str,          # OCR 不对时的修正，正确/不确定时为空
            "visual_type": "dialogue_bubble" | "narration" | "sign" | "illustration" | "noise" | "other",
            "speaker_hint": str,            # 能判断说话人时给出，否则空
            "description": str,              # 视觉描述
            "status": "ok" | "failed",
            "raw_output": str,
            "elapsed": float,
        }
    """
    buf = io.BytesIO()
    crop_image.save(buf, format="PNG")
    img_b64 = base64.b64encode(buf.getvalue()).decode()

    prompt = f"""你是一个漫画文字验证助手。请查看这张裁剪图，验证以下 OCR 文本是否正确。

OCR 文本：「{baberu_text if baberu_text else '(空)'}」

请输出严格 JSON（不要输出 markdown 代码块，不要输出任何其他文字）：
{{
  "ocr_correct": "correct" | "incorrect" | "partial" | "uncertain",
  "corrected_text": "如果 OCR 不正确且你确信正确文字，填在这里；否则留空字符串",
  "visual_type": "dialogue_bubble" | "narration" | "sign" | "illustration" | "noise" | "other",
  "speaker_hint": "如果能判断说话人，给出角色名或简短描述；否则留空字符串",
  "description": "简短描述图片内容（文字方向、字体大小、背景等，不超过 50 字）"
}}

重要规则：
- 如果你看不清文字，ocr_correct 必须设为 "uncertain"，corrected_text 留空，不要编造
- corrected_text 只在你确信 OCR 错误时才填写，不确定就留空
- "illustration" 表示这不是文字，是插画/装饰/符号
- "noise" 表示这是噪点/污渍/页码/线条，不是有效文字
- "sign" 表示招牌/标题/背景文字（非对话气泡）
"""

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
                            "detail": "high",
                        },
                    },
                ],
            }
        ],
        "max_tokens": 1000,
        "temperature": 0.1,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
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
            # 解析 JSON
            text = (raw or "").strip()
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                if attempt < max_retries:
                    time.sleep(1)
                    continue
                return {
                    "ocr_correct": "uncertain",
                    "corrected_text": "",
                    "visual_type": "other",
                    "speaker_hint": "",
                    "description": "",
                    "status": "failed",
                    "raw_output": raw,
                    "elapsed": elapsed,
                }
            # 字段归一化
            ocr_correct = str(data.get("ocr_correct", "uncertain")).lower()
            if ocr_correct not in ("correct", "incorrect", "partial", "uncertain"):
                ocr_correct = "uncertain"
            visual_type = str(data.get("visual_type", "other")).lower()
            if visual_type not in ("dialogue_bubble", "narration", "sign", "illustration", "noise", "other"):
                visual_type = "other"
            return {
                "ocr_correct": ocr_correct,
                "corrected_text": str(data.get("corrected_text", "") or "").strip(),
                "visual_type": visual_type,
                "speaker_hint": str(data.get("speaker_hint", "") or "").strip(),
                "description": str(data.get("description", "") or "").strip(),
                "status": "ok",
                "raw_output": raw,
                "elapsed": elapsed,
            }
        except Exception as e:
            elapsed = time.time() - t0
            if attempt < max_retries:
                time.sleep(1)
                continue
            return {
                "ocr_correct": "uncertain",
                "corrected_text": "",
                "visual_type": "other",
                "speaker_hint": "",
                "description": "",
                "status": "failed",
                "raw_output": str(e),
                "elapsed": elapsed,
            }
    return {
        "ocr_correct": "uncertain",
        "corrected_text": "",
        "visual_type": "other",
        "speaker_hint": "",
        "description": "",
        "status": "failed",
        "raw_output": "unreachable",
        "elapsed": 0.0,
    }
