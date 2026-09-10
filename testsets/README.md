# testsets — Benchmark 测试集

- `pages/`：漫画原图，**不入库**（.gitignore 已忽略；版权/体积原因）；`testsets/README.md` 等文本照常入库。
- `ground_truth/`：JSON，每页一条，VLM 当标注 oracle 产出：`{"page": "01.jpg", "blocks": [{"bbox": [...], "ocr": "...", "translation": "...", "bubble_type": "..."}]}`。
- `results/`：JSON，每轮 benchmark 一条，供汇总对比：`{"bench": "a", "engine": "...", "page": "...", "blocks": [...], "scores": {...}}`。

约定：`pages/` 只放原图不入库；`ground_truth/`、`results/` 的 JSON 均为 UTF-8 文本、入库。
