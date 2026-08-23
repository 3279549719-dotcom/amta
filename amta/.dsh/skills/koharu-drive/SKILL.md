---
name: koharu-drive
description: 驱动本地 koharu v0.59.1 headless（REST :4000）——项目/页面/流水线/mask 读写/导出/场景回读。任何需要调用 koharu 的任务先读本 skill。
---

# Koharu Drive（koharu v0.59.1 headless）

## 启动与健康

- `npm start` → `scripts/start_koharu.ps1`（`--port 4000 --headless --cpu`，自带 NO_PROXY + 就绪轮询）
- `npm run precheck` → 4000 端口可达性（exit 0/1）
- `npm run smoke` → 冒烟测试（当前回归门槛）

## 稳定接口（src/amta/koharu_client.py — KoharuClient，16 方法）

### 生命周期
- `wait_server(timeout=120)` — 等服务就绪
- `llm_status()` / `ensure_llm_ready()` — 翻译链路前置检查（当前 not-ready，Benchmark 不需要）
- `create_project(name) -> id` — 每批先 `close_current_project()` 再建
- `close_current_project()`

### 页面
- `import_page(image_path) -> page_id` — multipart 传图
- `get_scene()` / `get_page_nodes(page_id)` — 场景/节点

### 流水线
- `run_pipeline(page_ids, steps, target_language="zh", system_prompt=None, default_font="SimHei") -> operationId`
- `wait_operation(op_id, timeout=1200)` — 轮询至 completed/failed/cancelled

### mask（修复循环核心）
- `get_mask_blob_hash(page_id, role)` — role: `segment` | `bubble`
- `get_blob(ref) -> bytes` / `save_mask(page_id, role, dest)`
- `put_mask(page_id, role, png_bytes, engine=None)` — 回写 mask，可带引擎重跑

### 导出 / 回读
- `export_page(page_id, fmt, dest)` — fmt: `rendered` | `psd`，zip 自动解包
- `collect_blocks(nodes)` — 文字块 + bubble_type 推断
- `sort_by_reading_order(blocks)` — y 升、同行 x 降（日漫阅读序）

## 引擎 DAG（src/amta/pipeline.py）

```
detectors → TextBoxes      pp-doclayout-v3 / comic-text-detector / anime-text / comic-text-bubble-detector
ctd_seg   → SegmentMask    comic-text-detector-seg（needs TextBoxes，只细化已有框）
bubble    → BubbleMask     speech-bubble-segmentation
OCR       → OcrText        manga-ocr / paddle-ocr-vl-1.5 / mit48px-ocr（needs TextBoxes）
llm       → Translations   （needs OcrText）
inpaint   → Inpainted      lama-manga / flux2-klein / aot-inpainting（needs Segment+Bubble Mask）
font      → FontPredictions yuzumarker-font-detection（needs TextBoxes）
render    → FinalRender    koharu-renderer（needs Inpainted+Translations+FontPredictions）
```

## 修复循环（Repair Loop）标准动作

1. 读 scene → 定位问题节点/region
2. `save_mask` 取当前 mask 检查（或交 VLM 判定）
3. `put_mask(role=segment|brushInpaint)` 回写修正 mask
4. 重跑 inpainting（region 限定）→ 重跑 `koharu-renderer` → 导出
5. **patch 译文后必须重跑 koharu-renderer，否则导出缓存旧图**

## 坑（本 skill 相关）

- NO_PROXY 由 client 自动处理；不要关。
- 一次只能一个 pipeline job（processing 互斥），workers=1。
- `systemPrompt` 是唯一注入点（角色表/术语表/Story Memory 都从这里进）。
- 引擎变更（如换 OCR）后过一遍 `npm run smoke`。
