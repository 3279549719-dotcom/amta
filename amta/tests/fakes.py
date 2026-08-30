"""测试假适配器：FakeKoharu（KoharuClient 协议面）+ 共享 fixtures 工厂。

koharu scene 节点形状（koharu_blocks.collect_blocks 可消费）：
make_node 产出 {kind: {text, type}, transform}；get_page_nodes 按索引回填 node_id。
"""
from __future__ import annotations

from pathlib import Path


def make_node(node_id: str, x: float, y: float, w: float, h: float,
              text: str = "", kind_type: str = "speech_bubble") -> dict:
    """koharu scene 节点形状（koharu_blocks.collect_blocks 可消费）。"""
    return {"kind": {"text": {"text": text}, "type": kind_type},
            "transform": {"x": x, "y": y, "w": w, "h": h}}


class FakeKoharu:
    """按 engine steps 返回 canned nodes；满足 runner.run_all_pages 的调用面。"""

    def __init__(self, nodes_by_engine: dict[str, list[dict]]):
        self.nodes_by_engine = nodes_by_engine
        self._last_engine: str | None = None

    def wait_server(self, timeout: int = 60) -> None:
        pass

    def close_current_project(self) -> None:
        pass

    def create_project(self, name: str) -> str:
        return name

    def import_page(self, image_path: Path) -> str:
        return "p1"

    def run_pipeline(self, page_ids: list[str], steps: list[str], **kw) -> str:
        for eng in self.nodes_by_engine:
            if steps == [eng]:
                self._last_engine = eng
                break
        return f"op-{self._last_engine}"

    def wait_operation(self, op_id: str, timeout: int = 0) -> dict:
        return {"status": "completed", "id": op_id}

    def get_page_nodes(self, page_id: str) -> dict[str, dict]:
        eng = self._last_engine
        nodes = self.nodes_by_engine.get(eng, [])
        return {n.get("node_id", f"n{i}"): n for i, n in enumerate(nodes)} if nodes else {}
