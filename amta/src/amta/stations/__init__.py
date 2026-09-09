"""amta.stations — 各 Stage 顶层薄工位（脚本 CLI 对接的确定性入口）。

工位把 {detect|ocr}Artifact 契约对接具体引擎/库；stage 编排见 amta.orchestrator
与 scripts/ 下的顺序 CLI 流水线。

- detect_station — Stage 1 检测工位薄封装（RT-DETR-v2，脚本在 scripts/detect_rtdetr.py）
- ocr_station    — Stage 2 OCR 工位（裁框 → OCR(baberu/hayai) → confidence 过滤 → canon）

依赖: 各下层域 + amta.common/backends/guards；仅被 scripts 与 orchestrator 消费。
"""
