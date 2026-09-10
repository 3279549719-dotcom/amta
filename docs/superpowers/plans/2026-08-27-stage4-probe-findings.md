# Stage 4 探针结论：koharu v0.59.1 lama-manga inpaint 链路（2026-08-27）

> 探针位置：`scripts/probe_inpaint.py`（一次性，已跑完，可删）；证据：`output/tmp/probe_inpainted.png`
> 状态：**四问全部定案**，Task 2 封装以此为准。

## (a) mask role 与上传格式

- **role 用 `segment` + `bubble` 两个都要**（lama-manga 的 ENGINE_NEEDS = SegmentMask + BubbleMask，缺任一即 completed_with_errors）
- payload 必须是 **PNG 编码字节**（裸像素 `Image.tobytes()` 会 400 Bad Request）：
  ```python
  buf = io.BytesIO(); mask_img.save(buf, format="PNG"); png = buf.getvalue()
  ```
- 接口：`PUT /api/v1/pages/{page_id}/masks/{role}`，返回 `{"node": ..., "blob": ...}`（客户端 `put_mask(page_id, role, png_bytes, engine=None)` 已封装）

## (b) run_pipeline 前置条件

- 上传双 mask 后：`run_pipeline([page_id], ["lama-manga"])` → **completed，~20s（400×600 CPU）**
- 不需要先跑 speech-bubble-segmentation（bubble mask 自备）
- 上传 mask 时带 `engine="lama-manga"` 参数可选（koharu 支持上传即触发）

## (c) 结果取回（export 走不通，改用 blob）

- `export_page(page_id, "png"/"rendered", dest)` → 400/422（本项目不需要 renderer 节点，export 契约不符），**弃用**
- **正解**：`get_page_nodes(page_id)` → 节点 `kind = {"image": {"role": "inpainted", "blob": "..."}}` → `get_blob(blob)` → **WEBP 字节**（RIFF 头，PIL 可直接 `Image.open(io.BytesIO(data))` 转换）
- 节点 kind 结构：`{"image": {"role": "source"|"inpainted", "blob"}}` / `{"mask": {"role": "segment"|"bubble", "blob"}}`

## (d) 耗时

- lama-manga CPU（i5-1135G7）400×600：**~20s**；2243×3465 整页预计 1-3 分钟（探针未测整页，按面积线性外推）

## 对 Task 2/4 的修正（Ruling）

1. `run_inpaint` 签名改为 **`masks: dict[role, png_bytes]`**（原计划单 mask + steps 参数作废——双 mask 是硬前置）
2. 新增 `fetch_inpainted(page_id) -> bytes`（WEBP 原字节），由 04 工位转 PIL 贴回
3. 04 工位贴回实现：inpaint 完成后 fetch_inpainted → 整页覆盖（inpaint 结果已是整页图，直接作为 clean 底图，fill_white 区域在 mask 外不受影响——注意：整页替换会丢失我们本地 fill_white 的涂白？不会：fill_white 区域没进 mask，lama 不动它们，inpainted 整页保留原像素；但保险起见 04 工位在贴回后**重放一遍 fill_white**）
4. `pixel_diff_ratio` = clean 与原图 diff 比例（PIL 逐像素 or ImageChops.difference，>0 证明有擦除）
