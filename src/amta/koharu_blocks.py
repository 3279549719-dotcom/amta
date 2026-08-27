"""koharu scene 节点 → 文字块 的纯结果整形（从 koharu_client 拆出的深模块）。

唯一归属：
- collect_blocks          节点 → blocks[]（含 bubble_type 推断）
- sort_by_reading_order   日漫阅读序排序（y 升、同行 x 降）

纯函数：无 I/O、无状态、不依赖 HTTP 客户端。koharu_client 只保留 REST 适配职责，
节点结构知识收敛于此（Locality：场景 schema 变只改这里）。
"""
from __future__ import annotations


def collect_blocks(nodes: dict[str, dict]) -> list[dict]:
    """从 scene 节点提取文字块（含 bubble_type 推断），与轮子逻辑一致。"""
    blocks = []
    for node_id, node in nodes.items():
        kind = node.get("kind", {})
        if not (isinstance(kind, dict) and "text" in kind):
            continue
        text_data = kind["text"]
        raw_type = kind.get("type", "")
        if not raw_type:
            kind_keys = set(kind.keys()) - {"text"}
            if "speech_bubble" in kind_keys:
                raw_type = "speech_bubble"
            elif "narration" in kind_keys:
                raw_type = "narration"
            elif "sfx" in kind_keys:
                raw_type = "sfx"
            else:
                raw_type = "dialogue"
        rt = raw_type.lower()
        if "narration" in rt:
            bubble_type = "narration"
        elif "sfx" in rt:
            bubble_type = "sfx"
        elif any(k in rt for k in ("speech", "bubble", "dialogue", "text")):
            bubble_type = "dialogue"
        else:
            bubble_type = "unknown"

        blocks.append({
            "node_id": node_id,
            "ocr": (text_data.get("text") or "").strip(),
            "translation": (text_data.get("translation") or "").strip(),
            "confidence": text_data.get("confidence"),
            "alternatives": text_data.get("alternatives"),
            "transform": node.get("transform") or {},
            "bubble_type": bubble_type,
        })
    return blocks


def sort_by_reading_order(blocks: list[dict]) -> list[dict]:
    """y 升序、同行 x 降序（日漫阅读序）。"""
    def key(b: dict) -> tuple[float, float]:
        t = b.get("transform", {})
        return (t.get("y", 0), -t.get("x", 0))
    return sorted(blocks, key=key)
