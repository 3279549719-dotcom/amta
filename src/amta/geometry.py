"""共享几何库：bbox 解析、IoU、并集聚合。

唯一归属（/simplify 合并产物）：
- bbox_from_block  ← 合并自 benchmark.py / ocr_detect.py / recall_detect.py
- iou             ← 合并自 benchmark._iou / recall_crop.iou
- union_boxes     ← 合并自 benchmark.union_boxes
"""
from __future__ import annotations

from typing import Sequence


def bbox_from_block(block: dict) -> list[float]:
    """从 block 提取 [x1, y1, x2, y2]（保留 1 位小数）。

    优先使用已算好的 bbox 字段（recall_detect/ocr_detect 的 compact 输出），
    否则从 koharu 节点 transform 推导。
    """
    bb = block.get("bbox")
    if isinstance(bb, (list, tuple)) and len(bb) == 4:
        return [round(float(v), 1) for v in bb]
    t = block.get("transform", {})
    x = float(t.get("x", 0))
    y = float(t.get("y", 0))
    w = float(t.get("w", t.get("width", 0)))
    h = float(t.get("h", t.get("height", 0)))
    return [round(x, 1), round(y, 1), round(x + w, 1), round(y + h, 1)]


def iou(a: Sequence[float], b: Sequence[float]) -> float:
    """两个 [x1,y1,x2,y2] 框的 IoU。"""
    ax0, ay0, ax1, ay1 = a
    bx0, by0, bx1, by1 = b
    ix = max(0, min(ax1, bx1) - max(ax0, bx0))
    iy = max(0, min(ay1, by1) - max(ay0, by0))
    inter = ix * iy
    ua = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
    return inter / ua if ua > 0 else 0.0


def union_boxes(detections: dict[str, list[dict]], threshold: float = 0.5) -> list[dict]:
    """多 detector 并集：仅保留唯一 bbox（IoU > threshold 视为重复）。"""
    seen: list[tuple[float, ...]] = []
    for blocks in detections.values():
        for b in blocks:
            bb = tuple(bbox_from_block(b))
            if any(iou(bb, s) > threshold for s in seen):
                continue
            seen.append(bb)
    return [{"bbox": list(s)} for s in seen]


def union_blocks(detections: dict[str, list[dict]], threshold: float = 0.5) -> list[dict]:
    """多 detector 并集，保留首个命中框的元数据（node_id/bubble_type/ocr 等）。

    union_boxes 只留 bbox；这里把 blocks 的附加字段一并带出，供 01_detect 输出扁平 blocks[]。
    去重判据与 union_boxes 一致（IoU > threshold 视为重复），重复时保留首个出现的完整 block。
    引擎溯源（ADR-023）：遍历 detections.items()，block 已含 source_engines 字段时，
    新框确保记录当前引擎名，重复命中时把当前引擎名追加到已保留框（去重、顺序稳定）；
    无该字段的 block 保持旧行为（不新增字段）。
    """
    seen: list[dict] = []
    for eng, blocks in detections.items():
        for b in blocks:
            bb = bbox_from_block(b)
            dup = next((s for s in seen if iou(bb, s["bbox"]) > threshold), None)
            if dup is not None:
                src = dup.get("source_engines")
                if isinstance(src, list) and eng not in src:
                    src.append(eng)
                continue
            item = dict(b)
            item["bbox"] = bb
            src = item.get("source_engines")
            if isinstance(src, list):
                item["source_engines"] = list(src)  # 拷贝，避免与调用方共享可变列表
                if eng not in item["source_engines"]:
                    item["source_engines"].append(eng)
            seen.append(item)
    return seen


def _area(bb: Sequence[float]) -> float:
    return max(0.0, bb[2] - bb[0]) * max(0.0, bb[3] - bb[1])


def absorb_contained(blocks: list[dict], ioa_thresh: float = 0.75) -> list[dict]:
    """包含度去重（IoA）：全嵌套于更大框内的碎片子框被吸收丢弃。

    修 L10/并集残留：竖排碎片框（u04「ぽ」在 u05「ぽっらん」内）因 IoU≈0 逃过
    union 去重，此处按 IoA（子框∩容器 / 子框）≥0.75 判定为同一文本区域的碎片，
    丢弃子框，保留更大的容器框。扁平 blocks[] 契约不变（Phase B-light）。
    """
    if not blocks:
        return []
    # 按面积降序：大框先入,后续小框若被某已保留框包含则丢弃
    ordered = sorted(blocks, key=lambda b: _area(b["bbox"]), reverse=True)
    kept: list[dict] = []
    for b in ordered:
        bb = b["bbox"]
        if any(_contained_in(bb, k["bbox"], ioa_thresh) for k in kept):
            continue
        kept.append(b)
    return kept


def _contained_in(child: Sequence[float], parent: Sequence[float], ioa_thresh: float) -> bool:
    """child 是否全嵌套于 parent（IoA ≥ 阈值，即 child 被 parent 覆盖的比例）。"""
    c = _area(child)
    if c <= 0:
        return False
    x0 = max(child[0], parent[0])
    y0 = max(child[1], parent[1])
    x1 = min(child[2], parent[2])
    y1 = min(child[3], parent[3])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return inter / c >= ioa_thresh


def mark_contained(blocks: list[dict], ioa_threshold: float = 0.75) -> list[dict]:
    """标记嵌套框但不丢弃。

    替代 absorb_contained：IoA >= threshold 的小框被标记 contained_in=<父框region_id>，
    但保留在输出中，信息留给下游 LLM 判断。

    Args:
        blocks: 输入框列表（需含 bbox 字段）
        ioa_threshold: 嵌套判定阈值（默认 0.75，与原 absorb_contained 一致）

    Returns:
        标记后的框列表，每个框新增 region_id（u00, u01, ...）和 contained_in（None 或父框 id）
    """
    if not blocks:
        return []

    # 先分配 region_id（按原始顺序）
    for i, b in enumerate(blocks):
        b["region_id"] = f"u{i:02d}"
        if "contained_in" not in b:
            b["contained_in"] = None

    # 按面积降序排列，大框优先作为候选父框
    sorted_by_area = sorted(blocks, key=lambda b: _area(b["bbox"]), reverse=True)

    for i, small in enumerate(sorted_by_area):
        if small["contained_in"] is not None:
            continue  # 已经被标记
        for j, big in enumerate(sorted_by_area):
            if i == j:
                continue
            if big["contained_in"] == small["region_id"]:
                continue  # 避免循环引用
            if _contained_in(small["bbox"], big["bbox"], ioa_threshold):
                small["contained_in"] = big["region_id"]
                break

    return blocks


def assign_category(blocks: list[dict]) -> list[dict]:
    """bubble_type 值域统一映射到 3 级 category(Phase 1 / ADR-019)。

    koharu 推断的 bubble_type(dialogue/narration/sfx/unknown/overlay_text)
    → category ∈ {dialogue_bubble, overlay_text, sfx}。
    映射规则: dialogue/narration/unknown → dialogue_bubble(旁白归气泡类,
    未知默认保守——避免误判 overlay 被错误 inpaint); sfx → sfx;
    overlay_text 透传。保留原 bubble_type 字段(兼容下游)。
    """
    _MAP = {
        "dialogue": "dialogue_bubble",
        "narration": "dialogue_bubble",
        "unknown": "dialogue_bubble",
        "sfx": "sfx",
        "overlay_text": "overlay_text",
    }
    out = []
    for b in blocks:
        item = dict(b)
        bt = item.get("bubble_type")
        item["category"] = _MAP.get(bt if isinstance(bt, str) else "",
                                     "dialogue_bubble")
        out.append(item)
    return out


def assign_sub_tier(lines: list[dict], ratio: float = 1.4) -> list[dict]:
    """机械主次分段: 容器内每行, 与最大行宽比 >= ratio 则标 aside(碎碎念), 否则 primary。

    Gemini v1.1 Stage 1 原案: 行宽比>=1.4 自动拆分主台词与碎碎念 sub_tier。
    bbox = [x1,y1,x2,y2], 宽 = x2-x1。最大宽行为基准(primary), 明显更窄的行标 aside。
    """
    if not lines:
        return list(lines)
    widths = [b["bbox"][2] - b["bbox"][0] for b in lines]
    max_w = max(widths) or 1.0
    out = []
    for b, w in zip(lines, widths):
        item = dict(b)
        item["sub_tier"] = "aside" if (w / max_w) < (1.0 / ratio) else "primary"
        out.append(item)
    return out


def build_regions(blocks: list[dict], ioa_thresh: float = 0.75, ratio: float = 1.4,
                  iou_frag: float = 0.5) -> list[dict]:
    """把扁平 blocks 重组为层级 regions[]（容器 + child_lines + sub_tier）。

    契约升级(Gemini DetectionArtifact): 被更大框包含的子框挂到容器 child_lines;
    独立框自成 region(child_lines=[])。child_lines 内每行由 assign_sub_tier 标
    primary/aside, 供 02_ocr 展平翻译 + 未来 05 复合排版。

    碎片去重(Q11 定案): 容器 child_lines 内部, 与已收录行 IoU>=iou_frag(0.5) 视为
    同一文字碎片, 丢弃当前框(只保留首个)。消除 p17「まあ…」primary 与嵌套 aside
    几乎完全重合(IoA≈1.0)导致的重复 OCR。

    返回: [{node_id, bbox, bubble_type, text, child_lines: [line_with_sub_tier]}, ...]
    """
    if not blocks:
        return []
    ordered = sorted(blocks, key=lambda b: _area(b["bbox"]), reverse=True)
    regions: list[dict] = []
    for b in ordered:
        bb = b["bbox"]
        parent = next((r for r in regions if _contained_in(bb, r["bbox"], ioa_thresh)), None)
        if parent is not None:
            # 碎片去重: 与容器内已收录行高度重合(被包含 IoA>=iou_frag)则丢弃
            if any(_contained_in(bb, line["bbox"], iou_frag) for line in parent["child_lines"]):
                continue
            parent["child_lines"].append(dict(b))
        else:
            item = dict(b)
            item["child_lines"] = []
            regions.append(item)
    for r in regions:
        r["child_lines"] = assign_sub_tier(r["child_lines"], ratio)
    return regions


def flatten_regions(regions: list[dict], min_coverage_ratio: float = 0.60) -> list[dict]:
    """把层级 regions[] 展平为扁平 blocks[]（容器自身 + 每个 child_line 各一框）。

    02_ocr 按展平后的 bbox 裁框出独立 region_id；03 保持扁平翻译。兼容旧 blocks[] 消费方。

    【残差保底律 Residual Container Fallback — 修复"展平吞噬"bug】
    旧规则"容器自身不输出，只输出 child_lines"在"容器很宽但只检出一根极窄子行"时
    会丢弃母体容器，导致容器内未被独立检出的大字主台词被吞噬
    （15.jpg「弟子だからね」案：160px 容器只包了 52px 小字，大字被灭口）。

    修复：计算 child_lines 对容器的覆盖率，若覆盖率不足或单子行极窄，触发保底——
    丢弃不完全的子行，直接输出完整母体气泡容器送 OCR（Manga-OCR ViT 具有多行整气泡
    自回归识别能力，不需要在 Stage 1 强行切碎）。

    触发条件（任一）：
      - coverage_ratio < min_coverage_ratio（默认 0.60）
      - len(child_lines) == 1 且 容器宽度 > 1.5 × 子行宽度
    """
    out: list[dict] = []
    for r in regions:
        child_lines = r.get("child_lines", [])

        # 1. 孤立区域（无子行），直接输出
        if not child_lines:
            out.append(dict(r))
            continue

        # 2. 计算子行总面积对容器的覆盖率
        container_area = _area(r["bbox"])
        if container_area == 0:
            continue
        child_total_area = sum(_area(c["bbox"]) for c in child_lines)
        coverage_ratio = child_total_area / container_area

        # 3. 残差保底判定：覆盖率不足 或 单子行极窄
        container_w = r["bbox"][2] - r["bbox"][0]
        first_child_w = child_lines[0]["bbox"][2] - child_lines[0]["bbox"][0]
        is_severely_undercovered = (
            coverage_ratio < min_coverage_ratio
            or (len(child_lines) == 1 and container_w > first_child_w * 1.5)
        )

        if is_severely_undercovered:
            # 触发保底：丢弃不完全的子行，直接输出完整大气泡容器
            fallback_region = dict(r)
            fallback_region["child_lines"] = []  # 清空单子行，作为完整气泡送 OCR
            fallback_region["fallback_triggered"] = True
            out.append(fallback_region)
        else:
            # 正常多行完整覆盖，展平输出各子行
            for line in child_lines:
                item = dict(line)
                out.append(item)
    return out
