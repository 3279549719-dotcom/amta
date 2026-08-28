Read "E:\manga translator agent\amta\docs\superpowers\plans\2026-08-28-front3-reconstruction.md":

     1	# 前三阶段重构（Front3 Reconstruction）实施计划
     2	
     3	> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
     4	
     5	**Goal:** 重构 detect/OCR/translate 前三阶段，砍掉硬编码微观规则（absorb_contained 丢弃、build_regions 嵌套、flatten 展平灭口），改为粗粒度高召回 + 双引擎会诊 + 纯文本语义翻译，解决漫画文字漏检问题。
     6	
     7	**Architecture:** Stage 1 砍掉 build_regions/flatten，absorb_contained 改标记不丢弃，所有框平级独立 OCR；Stage 2 新增 VLM contact sheet 批量校验，Baberu+VLM 双引擎文本并列，不自动除噪；Stage 3 纯文本 DeepSeek 翻译，输入双引擎文本，LLM 自行判断选择。每阶段独立 trace 文件。分步实施，每步验证。
     8	
     9	**Tech Stack:** Python 3.13, koharu.exe (4-detector + Baberu OCR), DeepSeek API (纯文本翻译 + VLM 校验), PIL (contact sheet 拼图), pytest (测试)
    10	
    11	**ADR:** `docs/decisions/023-front3-reconstruction.md`
    12	
    13	---
    14	
    15	## File Structure
    16	
    17	### 修改的文件
    18	- `scripts/01_detect.py` — Stage 1 重构：砍 build_regions/flatten，absorb_contained 改标记，加 source_engines，加 tracing
    19	- `scripts/02_ocr.py` — Stage 2 改造：输出双引擎文本（baberu_text + vlm_text），加 VLM contact sheet 校验调用，加 tracing
    20	- `scripts/03_translate.py` — Stage 3 改造：输入改为双引擎文本，LLM 自行选择，加 tracing
    21	- `src/amta/geometry.py` — 保留 union_blocks/assign_category，新增 mark_contained（替代 absorb_contained），build_regions/flatten_regions 保留但不在主链调用（回退用）
    22	- `src/amta/ocr_engines.py` — 新增 VLM contact sheet 校验函数（vlm_verify_batch）
    23	
    24	### 新增的文件
    25	- `src/amta/vlm_verify.py` — VLM contact sheet 校验模块：拼图 + DeepSeek vision 调用 + 输出解析 + 容错
    26	- `scripts/eval_stage1.py` — Stage 1 验证脚本：框数/覆盖率/假框率/已知漏检检查，输出 HTML
    27	- `scripts/eval_stage2.py` — Stage 2 验证脚本：双引擎一致率/VLM 对齐率/差异分析，输出 HTML
    28	- `tests/test_front3_stage1.py` — Stage 1 单元测试：mark_contained、平级输出、source_engines、tracing
    29	- `tests/test_front3_stage2.py` — Stage 2 单元测试：contact sheet 拼图、VLM 输出解析、双引擎输出格式、容错
    30	- `tests/test_front3_stage3.py` — Stage 3 单元测试：双引擎输入、LLM 选择、tracing
    31	
    32	### 保留但不调用的文件（回退用）
    33	- `src/amta/geometry.py` 中的 `build_regions()` / `flatten_regions()` — 保留代码，01_detect.py 不再调用
    34	
    35	---
    36	
    37	## Phase 1: Stage 1 重构
    38	
    39	### Task 1: 新增 mark_contained 函数（替代 absorb_contained）
    40	
    41	**Files:**
    42	- Modify: `src/amta/geometry.py`
    43	- Test: `tests/test_front3_stage1.py`
    44	
    45	- [ ] **Step 1: 写测试**
    46	
    47	在 `tests/test_front3_stage1.py` 中添加：
    48	
    49	```python
    50	"""Stage 1 重构单元测试：mark_contained 替代 absorb_contained。"""
    51	import sys
    52	from pathlib import Path
    53	sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
    54	from amta.geometry import mark_contained, union_blocks
    55	
    56	
    57	def _b(x1, y1, x2, y2, eid="test"):
    58	    return {"bbox": [x1, y1, x2, y2], "node_id": eid, "bubble_type": "text",
    59	            "category": "dialogue_bubble", "source_engines": [eid]}
    60	
    61	
    62	def test_mark_contained_adds_contained_in_tag():
    63	    """嵌套小框应被标记 contained_in，但不被丢弃。"""
    64	    parent = _b(100, 100, 300, 300, "parent")
    65	    child = _b(120, 120, 180, 180, "child")  # IoA = 3600/3600 = 1.0
    66	    result = mark_contained([parent, child])
    67	    assert len(result) == 2, "嵌套框不应被丢弃"
    68	    child_out = [b for b in result if b["node_id"] == "child"][0]
    69	    assert child_out["contained_in"] == "parent", "应标记父框 id"
    70	    parent_out = [b for b in result if b["node_id"] == "parent"][0]
    71	    assert parent_out.get("contained_in") is None, "父框不应有 contained_in"
    72	
    73	
    74	def test_mark_contained_partial_overlap_not_tagged():
    75	    """部分重叠（IoA < 0.75）不应被标记。"""
    76	    a = _b(100, 100, 200, 200, "a")
    77	    b = _b(150, 150, 250, 250, "b")  # 部分重叠
    78	    result = mark_contained([a, b])
    79	    for box in result:
    80	        assert box.get("contained_in") is None
    81	
    82	
    83	def test_mark_contained_preserves_all_boxes():
    84	    """所有框都应保留，不丢弃任何框。"""
    85	    boxes = [_b(i*10, i*10, i*10+50, i*10+50, f"b{i}") for i in range(5)]
    86	    result = mark_contained(boxes)
    87	    assert len(result) == 5
    88	
    89	
    90	def test_mark_contained_assigns_region_id():
    91	    """每个框应被分配 region_id（u00, u01, ...）。"""
    92	    boxes = [_b(10, 10, 50, 50, "a"), _b(60, 60, 100, 100, "b")]
    93	    result = mark_contained(boxes)
    94	    ids = [b["region_id"] for b in result]
    95	    assert ids == ["u00", "u01"]
    96	```
    97	
    98	- [ ] **Step 2: 跑测试确认失败**
    99	
   100	Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage1.py -v`
   101	Expected: FAIL with "cannot import name 'mark_contained'"
   102	
   103	- [ ] **Step 3: 实现 mark_contained**
   104	
   105	在 `src/amta/geometry.py` 中，在 `absorb_contained` 函数之后添加：
   106	
   107	```python
   108	def mark_contained(blocks: list[dict], ioa_threshold: float = 0.75) -> list[dict]:
   109	    """标记嵌套框但不丢弃。
   110	
   111	    替代 absorb_contained：IoA >= threshold 的小框被标记 contained_in=<父框region_id>，
   112	    但保留在输出中，信息留给下游 LLM 判断。
   113	
   114	    Args:
   115	        blocks: 输入框列表（需含 bbox 字段）
   116	        ioa_threshold: 嵌套判定阈值（默认 0.75，与原 absorb_contained 一致）
   117	
   118	    Returns:
   119	        标记后的框列表，每个框新增 region_id（u00, u01, ...）和 contained_in（None 或父框 id）
   120	    """
   121	    # 先分配 region_id
   122	    for i, b in enumerate(blocks):
   123	        b["region_id"] = f"u{i:02d}"
   124	        if "contained_in" not in b:
   125	            b["contained_in"] = None
   126	
   127	    # 按面积降序排列，大框优先作为候选父框
   128	    sorted_by_area = sorted(blocks, key=lambda b: bbox_area(b["bbox"]), reverse=True)
   129	
   130	    for i, small in enumerate(sorted_by_area):
   131	        if small["contained_in"] is not None:
   132	            continue  # 已经被标记
   133	        for j, big in enumerate(sorted_by_area):
   134	            if i == j:
   135	                continue
   136	            if big["contained_in"] == small["region_id"]:
   137	                continue  # 避免循环
   138	            ioa = intersection_over_area(small["bbox"], big["bbox"])
   139	            if ioa >= ioa_threshold:
   140	                small["contained_in"] = big["region_id"]
   141	                break
   142	
   143	    return blocks
   144	```
   145	
   146	注意：需要确认 `intersection_over_area` 函数已存在于 geometry.py 中。如果不存在，添加：
   147	
   148	```python
   149	def intersection_over_area(a: list[float], b: list[float]) -> float:
   150	    """计算 a 与 b 的交集面积 / a 的面积（IoA，a 嵌套在 b 中的比例）。"""
   151	    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
   152	    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
   153	    inter = ix * iy
   154	    area_a = bbox_area(a)
   155	    return inter / area_a if area_a > 0 else 0.0
   156	```
   157	
   158	- [ ] **Step 4: 跑测试确认通过**
   159	
   160	Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage1.py -v`
   161	Expected: 4 tests PASS
   162	
   163	- [ ] **Step 5: Commit**
   164	
   165	```bash
   166	cd E:\manga translator agent\amta
   167	git add src/amta/geometry.py tests/test_front3_stage1.py
   168	git commit -m "feat(stage1): add mark_contained to replace absorb_contained
   169	
   170	Nested boxes are now tagged with contained_in instead of being dropped.
   171	Preserves all detector output for downstream LLM judgment.
   172	Refs ADR-023"
   173	```
   174	
   175	---
   176	
   177	### Task 2: 重构 01_detect.py 主链
   178	
   179	**Files:**
   180	- Modify: `scripts/01_detect.py`
   181	- Test: `tests/test_front3_stage1.py`（追加测试）
   182	
   183	- [ ] **Step 1: 写测试（01_detect 输出格式）**
   184	
   185	在 `tests/test_front3_stage1.py` 末尾追加：
   186	
   187	```python
   188	def test_detection_output_format_flat_blocks():
   189	    """detection.json 应输出平级 blocks，不含 regions/child_lines。"""
   190	    # 模拟 01_detect 的输出结构
   191	    blocks = [
   192	        {"region_id": "u00", "bbox": [10, 10, 50, 50], "category": "dialogue_bubble",
   193	         "bubble_type": "text", "source_engines": ["det1"], "contained_in": None},
   194	        {"region_id": "u01", "bbox": [20, 20, 40, 40], "category": "dialogue_bubble",
   195	         "bubble_type": "text", "source_engines": ["det1", "det2"], "contained_in": "u00"},
   196	    ]
   197	    doc = {"page": "test", "blocks": blocks, "n_boxes": 2}
   198	    assert "regions" not in doc, "不应有 regions 字段"
   199	    assert doc["n_boxes"] == 2
   200	    assert all("child_lines" not in b for b in blocks)
   201	    assert blocks[1]["contained_in"] == "u00"
   202	    assert "det2" in blocks[1]["source_engines"]
   203	```
   204	
   205	- [ ] **Step 2: 跑测试确认通过（纯结构测试，不依赖 01_detect）**
   206	
   207	Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage1.py::test_detection_output_format_flat_blocks -v`
   208	Expected: PASS
   209	
   210	- [ ] **Step 3: 修改 01_detect.py 主链**
   211	
   212	将 `scripts/01_detect.py` 中的 `run()` 函数核心逻辑从：
   213	
   214	```python
   215	blocks = union_blocks(comp)
   216	blocks = assign_category(blocks)
   217	regions = build_regions(blocks)
   218	flat_blocks = flatten_regions(regions)
   219	doc = {
   220	    "regions": regions,
   221	    "blocks": flat_blocks,
   222	    "n_boxes": len(flat_blocks),
   223	    "n_regions": len(regions),
   224	    ...
   225	}
   226	```
   227	
   228	改为：
   229	
   230	```python
   231	blocks = union_blocks(comp)
   232	blocks = assign_category(blocks)
   233	# 新增：合并 source_engines（union 后记录哪些 detector 检到了这个框）
   234	for b in blocks:
   235	    if "source_engines" not in b:
   236	        b["source_engines"] = [b.get("node_id", "unknown")]
   237	# 替代 absorb_contained：标记嵌套但不丢弃
   238	blocks = mark_contained(blocks)
   239	
   240	doc = {
   241	    "work_id": work_id,
   242	    "page": raw_page.stem,
   243	    "source": str(raw_page),
   244	    "image_meta": {"width": img.width, "height": img.height,
   245	                   "channels": len(img.getbands())},
   246	    "blocks": blocks,
   247	    "n_boxes": len(blocks),
   248	    "detect_steps": DETECTOR_STEPS,
   249	    "per_engine_boxes": {eng: len(blks) for eng, blks in comp.items()},
   250	    "front3_version": "2.0",  # 标记新架构版本
   251	    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
   252	}
   253	```
   254	
   255	需要在文件顶部 import `mark_contained`：
   256	
   257	```python
   258	from amta.geometry import union_blocks, assign_category, mark_contained, compact_blocks
   259	```
   260	
   261	注意：`build_regions` 和 `flatten_regions` 的 import 保留（回退用），但不在主链调用。
   262	
   263	- [ ] **Step 4: 添加 tracing 落盘**
   264	
   265	在 `run()` 函数中，写 detection.json 之前，添加 trace 落盘：
   266	
   267	```python
   268	# Tracing: Stage 1 处理过程
   269	trace = {
   270	    "page": raw_page.stem,
   271	    "per_engine_raw": {eng: len(blks) for eng, blks in comp.items()},
   272	    "after_union": len(union_blocks(comp)),
   273	    "after_mark_contained": len(blocks),
   274	    "contained_boxes": [b["region_id"] for b in blocks if b.get("contained_in")],
   275	    "contained_pairs": [(b["region_id"], b["contained_in"]) for b in blocks if b.get("contained_in")],
   276	    "detect_steps": DETECTOR_STEPS,
   277	    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
   278	}
   279	trace_path = out_path.parent / f"{raw_page.stem}_01_detect_trace.json"
   280	write_json(trace_path, trace)
   281	```
   282	
   283	- [ ] **Step 5: 跑全部 Stage 1 测试**
   284	
   285	Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage1.py -v`
   286	Expected: 5 tests PASS
   287	
   288	- [ ] **Step 6: 手动验证 01_detect 能跑通（单页）**
   289	
   290	先启动 koharu，然后跑单页：
   291	
   292	```bash
   293	cd E:\manga translator agent\amta
   294	py -3.13 scripts/01_detect.py --work-id touhou-single-wing --raw "D:\我的汉化\汉化作品\东方\单翼停留之地\14.jpg" --out "workspace\touhou-single-wing\artifacts\page_13_detection.json"
   295	```
   296	
   297	Expected: 输出 `[01_detect] 14: N boxes -> ...`，N 应大于旧架构的框数（因为不再丢弃嵌套框）。
   298	
   299	检查输出 JSON：应包含 `blocks`（平级）、`front3_version: "2.0"`，不应包含 `regions`。
   300	
   301	- [ ] **Step 7: Commit**
   302	
   303	```bash
   304	cd E:\manga translator agent\amta
   305	git add scripts/01_detect.py tests/test_front3_stage1.py
   306	git commit -m "feat(stage1): refactor 01_detect to flat blocks with mark_contained
   307	
   308	Replace build_regions/flatten_regions/absorb_contained with flat block output.
   309	All detector boxes preserved, nested boxes tagged with contained_in.
   310	Add per-engine source tracking and stage1 trace file.
   311	Refs ADR-023"
   312	```
   313	
   314	---
   315	
   316	### Task 3: Stage 1 全量验证（11-20 页）
   317	
   318	**Files:**
   319	- Create: `scripts/eval_stage1.py`
   320	
   321	- [ ] **Step 1: 写验证脚本**
   322	
   323	创建 `scripts/eval_stage1.py`，功能：
   324	1. 备份旧 detection.json
   325	2. 用新 01_detect 跑 11-20 页
   326	3. 对比新旧：框数变化、每引擎贡献、已知漏检覆盖率、假框率（双引擎都空的比例——但 Stage 1 还没有 OCR，所以这一步只看框数和覆盖率）
   327	4. 输出 HTML 报告
   328	
   329	脚本核心逻辑（参考已有的 `scripts/eval_flatten_fix_v2.py`）：
   330	
   331	```python
   332	"""eval_stage1.py — Stage 1 重构验证：11-20 页全量对比。"""
   333	# 实现要点：
   334	# 1. EVAL_PAGES = [11,12,13,14,15,16,17,18,19,20]
   335	# 2. 备份旧 detection.json 到 backup_pre_front3/
   336	# 3. 逐页跑 01_detect.py（subprocess）
   337	# 4. 对比：旧 n_boxes vs 新 n_boxes，新 contained_in 数量，per_engine 对比
   338	# 5. 已知漏检区域检查（14页「では豊ちゃん」、15页「弟子だからね」等）
   339	# 6. 输出 eval_stage1_report.html + eval_stage1_results.json
   340	```
   341	
   342	（完整代码由执行 agent 编写，参考 eval_flatten_fix_v2.py 的结构。）
   343	
   344	- [ ] **Step 2: 启动 koharu 并跑验证**
   345	
   346	```bash
   347	cd E:\manga translator agent\amta
   348	powershell -ExecutionPolicy Bypass -File scripts/start_koharu.ps1
   349	py -3.13 scripts/eval_stage1.py
   350	```
   351	
   352	Expected: 10 页全部跑完，输出 HTML 报告。框数应增加（因为不再丢弃嵌套框），已知漏检区域应有对应框。
   353	
   354	- [ ] **Step 3: 人工抽检核心 case（14/15 页）**
   355	
   356	打开 HTML 报告，检查：
   357	- 14 页「では豊ちゃん」区域是否有框覆盖（bbox 应包含 [1600,2630,1870,3150]）
   358	- 15 页「弟子だからね」区域是否有框覆盖（bbox 应包含 [50,2430,210,2870]）
   359	- 框数增加是否合理（不应爆炸式增长，预期 +20%~50%）
   360	
   361	- [ ] **Step 4: Commit 验证脚本和报告**
   362	
   363	```bash
   364	cd E:\manga translator agent\amta
   365	git add scripts/eval_stage1.py
   366	git commit -m "test(stage1): add eval_stage1.py for 11-20 page validation
   367	
   368	Compares old vs new detection output: box count, per-engine contribution,
   369	known miss-region coverage, contained_in tagging.
   370	Refs ADR-023"
   371	```
   372	
   373	---
   374	
   375	## Phase 2: Stage 2 双引擎会诊
   376	
   377	### Task 4: 新增 VLM contact sheet 校验模块
   378	
   379	**Files:**
   380	- Create: `src/amta/vlm_verify.py`
   381	- Test: `tests/test_front3_stage2.py`
   382	
   383	- [ ] **Step 1: 写测试**
   384	
   385	创建 `tests/test_front3_stage2.py`：
   386	
   387	```python
   388	"""Stage 2 单元测试：VLM contact sheet 校验。"""
   389	import sys
   390	from pathlib import Path
   391	sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
   392	from amta.vlm_verify import make_contact_sheet, parse_vlm_output, vlm_verify_batch
   393	
   394	
   395	def test_make_contact_sheet_grid_layout():
   396	    """contact sheet 应按网格排列 crop 图。"""
   397	    from PIL import Image
   398	    crops = [Image.new("RGB", (100, 50), (255, 255, 255)) for _ in range(7)]
   399	    sheet = make_contact_sheet(crops, cols=3, pad=10, bg=(0, 0, 0))
   400	    # 3列 → 3行，每行 100+10*2=120 宽，每列 50+10*2=70 高
   401	    assert sheet.width == 3 * 120  # 360
   402	    assert sheet.height == 3 * 70   # 210
   403	
   404	
   405	def test_parse_vlm_output_line_by_line():
   406	    """VLM 输出应按行解析，与输入顺序对应。"""
   407	    raw = "文本1\n文本2\n文本3\n"
   408	    result = parse_vlm_output(raw, expected_count=3)
   409	    assert len(result) == 3
   410	    assert result == ["文本1", "文本2", "文本3"]
   411	
   412	
   413	def test_parse_vlm_output_empty_lines():
   414	    """空行应解析为空字符串。"""
   415	    raw = "文本1\n\n文本3\n"
   416	    result = parse_vlm_output(raw, expected_count=3)
   417	    assert result[1] == ""
   418	
   419	
   420	def test_parse_vlm_output_count_mismatch():
   421	    """输出数量与预期不符时应返回 None（触发容错）。"""
   422	    raw = "只有一行\n"
   423	    result = parse_vlm_output(raw, expected_count=3)
   424	    assert result is None
   425	```
   426	
   427	- [ ] **Step 2: 跑测试确认失败**
   428	
   429	Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage2.py -v`
   430	Expected: FAIL with "No module named 'amta.vlm_verify'"
   431	
   432	- [ ] **Step 3: 实现 vlm_verify.py**
   433	
   434	创建 `src/amta/vlm_verify.py`：
   435	
   436	```python
   437	"""VLM contact sheet 批量校验模块。
   438	
   439	把所有 crop 图拼成 contact sheet，送 DeepSeek vision 做批量转写。
   440	配置：thinking=disabled, detail=low（probe B 组验证最优，2-3s/页）。
   441	输出：按输入顺序对应的转写文本列表。
   442	"""
   443	from __future__ import annotations
   444	import base64
   445	import io
   446	import time
   447	from pathlib import Path
   448	from typing import Optional
   449	from PIL import Image
   450	
   451	
   452	def make_contact_sheet(crops: list[Image.Image], cols: int = 3,
   453	                       pad: int = 12, bg: tuple = (255, 255, 255)) -> Image.Image:
   454	    """把 crop 图列表拼成网格 contact sheet。
   455	
   456	    Args:
   457	        crops: PIL Image 列表
   458	        cols: 列数
   459	        pad: 图片间距
   460	        bg: 背景色
   461	
   462	    Returns:
   463	        拼接后的 PIL Image
   464	    """
   465	    if not crops:
   466	        return Image.new("RGB", (10, 10), bg)
   467	    rows = (len(crops) + cols - 1) // cols
   468	    # 统一缩放到相同宽度（保持比例）
   469	    target_w = max(c.width for c in crops)
   470	    normalized = []
   471	    for c in crops:
   472	        if c.width != target_w:
   473	            ratio = target_w / c.width
   474	            new_h = int(c.height * ratio)
   475	            c = c.resize((target_w, new_h), Image.LANCZOS)
   476	        normalized.append(c)
   477	    cell_w = target_w + pad * 2
   478	    cell_h = max(c.height for c in normalized) + pad * 2
   479	    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), bg)
   480	    for i, c in enumerate(normalized):
   481	        r, col = divmod(i, cols)
   482	        x = col * cell_w + pad
   483	        y = r * cell_h + pad
   484	        sheet.paste(c, (x, y))
   485	    return sheet
   486	
   487	
   488	def parse_vlm_output(raw: str, expected_count: int) -> Optional[list[str]]:
   489	    """解析 VLM 输出，按行对应输入顺序。
   490	
   491	    Args:
   492	        raw: VLM 原始输出文本
   493	        expected_count: 预期的行数（与 crop 数量一致）
   494	
   495	    Returns:
   496	        文本列表（长度=expected_count），或 None（数量不符时触发容错）
   497	    """
   498	    lines = [line.strip() for line in raw.strip().split("\n")]
   499	    # 过滤掉纯空行？不——空行可能表示 VLM 认为该区域无文字
   500	    # 但 VLM 可能输出多余的空行，需要精确匹配
   501	    if len(lines) != expected_count:
   502	        return None
   503	    return lines
   504	
   505	
   506	def vlm_verify_batch(crops: list[Image.Image], api_key: str,
   507	                     model: str = "deepseek-v4-flash-vision-exp",
   508	                     max_retries: int = 2, timeout: int = 60) -> dict:
   509	    """VLM contact sheet 批量校验主函数。
   510	
   511	    Args:
   512	        crops: crop 图列表
   513	        api_key: DeepSeek API key
   514	        model: VLM 模型名
   515	        max_retries: 最大重试次数
   516	        timeout: 单次调用超时（秒）
   517	
   518	    Returns:
   519	        {
   520	            "texts": list[str] | None,  # 转写文本列表，失败时为 None
   521	            "status": "ok" | "failed" | "count_mismatch",
   522	            "raw_output": str,
   523	            "elapsed": float,
   524	            "retries": int,
   525	        }
   526	    """
   527	    import requests
   528	    sheet = make_contact_sheet(crops)
   529	    buf = io.BytesIO()
   530	    sheet.save(buf, format="PNG")
   531	    img_b64 = base64.b64encode(buf.getvalue()).decode()
   532	
   533	    prompt = (
   534	        f"这是一页漫画的 {len(crops)} 个文字区域截图，按从左到右、从上到下的网格顺序排列。"
   535	        f"请逐个转写每个区域中的日文文字，直接输出每行一个区域的转写结果，共 {len(crops)} 行。"
   536	        f"如果某个区域没有文字，输出空行。不要输出编号、解释或其他内容。"
   537	    )
   538	
   539	    payload = {
   540	        "model": model,
   541	        "messages": [{"role": "user", "content": [
   542	            {"type": "text", "text": prompt},
   543	            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
   544	        ]}],
   545	        "max_tokens": 4000,
   546	        "temperature": 0.1,
   547	        "extra_body": {"thinking": {"type": "disabled"}},
   548	    }
   549	    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
   550	
   551	    for attempt in range(max_retries + 1):
   552	        t0 = time.time()
   553	        try:
   554	            resp = requests.post("https://api.deepseek.com/chat/completions",
   555	                                 json=payload, headers=headers, timeout=timeout)
   556	            resp.raise_for_status()
   557	            raw = resp.json()["choices"][0]["message"]["content"]
   558	            elapsed = time.time() - t0
   559	            texts = parse_vlm_output(raw, len(crops))
   560	            if texts is not None:
   561	                return {"texts": texts, "status": "ok", "raw_output": raw,
   562	                        "elapsed": elapsed, "retries": attempt}
   563	            else:
   564	                # 数量不符，重试
   565	                if attempt < max_retries:
   566	                    continue
   567	                return {"texts": None, "status": "count_mismatch", "raw_output": raw,
   568	                        "elapsed": elapsed, "retries": attempt}
   569	        except Exception as e:
   570	            elapsed = time.time() - t0
   571	            if attempt < max_retries:
   572	                time.sleep(2)
   573	                continue
   574	            return {"texts": None, "status": "failed", "raw_output": str(e),
   575	                    "elapsed": elapsed, "retries": attempt}
   576	```
   577	
   578	注意：API endpoint 和模型名需要根据实际配置确认。参考 `src/amta/translate.py` 中的 DeepSeek 调用方式。
   579	
   580	- [ ] **Step 4: 跑测试确认通过**
   581	
   582	Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage2.py -v`
   583	Expected: 4 tests PASS（vlm_verify_batch 测试可能需要 mock，执行时按需添加 mock）
   584	
   585	- [ ] **Step 5: Commit**
   586	
   587	```bash
   588	cd E:\manga translator agent\amta
   589	git add src/amta/vlm_verify.py tests/test_front3_stage2.py
   590	git commit -m "feat(stage2): add VLM contact sheet batch verification module
   591	
   592	Probe-validated config: thinking=disabled, detail=low, ~2-3s/page.
   593	Outputs text list aligned with input crop order. Includes retry/fallback logic.
   594	Refs ADR-023"
   595	```
   596	
   597	---
   598	
   599	### Task 5: 改造 02_ocr.py 输出双引擎文本
   600	
   601	**Files:**
   602	- Modify: `scripts/02_ocr.py`
   603	- Test: `tests/test_front3_stage2.py`（追加）
   604	
   605	- [ ] **Step 1: 写测试（canon 输出格式）**
   606	
   607	在 `tests/test_front3_stage2.py` 末尾追加：
   608	
   609	```python
   610	def test_canon_output_dual_engine_format():
   611	    """canon.json 应输出双引擎文本（baberu_text + vlm_text）。"""
   612	    item = {
   613	        "region_id": "u00",
   614	        "bbox": [10, 10, 50, 50],
   615	        "baberu_text": "では豊ちゃん…",
   616	        "vlm_text": "では豊ちゃん、輝夜様に…",
   617	        "contained_in": None,
   618	        "source_engines": ["det1"],
   619	        "vlm_status": "ok",
   620	    }
   621	    assert "baberu_text" in item
   622	    assert "vlm_text" in item
   623	    assert "vlm_status" in item
   624	    assert item["vlm_status"] in ("ok", "failed", "count_mismatch", "skipped")
   625	```
   626	
   627	- [ ] **Step 2: 修改 02_ocr.py**
   628	
   629	将 `scripts/02_ocr.py` 的输出从单文本改为双引擎文本：
   630	
   631	1. 读取 detection.json 的 `blocks`（平级，含 region_id/bbox/contained_in/source_engines）
   632	2. 对每个 block 裁 crop 图，跑 Baberu OCR（现有逻辑）
   633	3. 收集所有 crop 图，调用 `vlm_verify_batch()` 做 VLM 批量校验
   634	4. 合并输出：每个 region `{region_id, bbox, baberu_text, vlm_text, contained_in, source_engines, vlm_status}`
   635	5. VLM 失败时 vlm_text=None, vlm_status="failed"，降级只用 Baberu
   636	6. 添加 trace 落盘：`{page}_02_ocr_trace.json`
   637	
   638	核心输出结构：
   639	
   640	```python
   641	items = []
   642	for i, block in enumerate(blocks):
   643	    items.append({
   644	        "region_id": block["region_id"],
   645	        "bbox": block["bbox"],
   646	        "baberu_text": baberu_results[i],
   647	        "vlm_text": vlm_result["texts"][i] if vlm_result["status"] == "ok" else None,
   648	        "contained_in": block.get("contained_in"),
   649	        "source_engines": block.get("source_engines", []),
   650	        "vlm_status": vlm_result["status"],
   651	    })
   652	```
   653	
   654	- [ ] **Step 3: 跑测试**
   655	
   656	Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage2.py -v`
   657	Expected: 5 tests PASS
   658	
   659	- [ ] **Step 4: 手动验证单页**
   660	
   661	```bash
   662	cd E:\manga translator agent\amta
   663	py -3.13 scripts/02_ocr.py --work-id touhou-single-wing \
   664	  --det workspace/touhou-single-wing/artifacts/page_13_detection.json \
   665	  --raw "D:\我的汉化\汉化作品\东方\单翼停留之地\14.jpg" \
   666	  --out workspace/touhou-single-wing/artifacts/page_13_canon.json \
   667	  --page-idx 13 --engine auto
   668	```
   669	
   670	Expected: 输出 canon.json，每个 item 含 baberu_text 和 vlm_text。
   671	
   672	- [ ] **Step 5: Commit**
   673	
   674	```bash
   675	cd E:\manga translator agent\amta
   676	git add scripts/02_ocr.py tests/test_front3_stage2.py
   677	git commit -m "feat(stage2): refactor 02_ocr to output dual-engine text
   678	
   679	Baberu OCR + VLM contact sheet verification results are output side-by-side.
   680	VLM failure degrades gracefully to Baberu-only. Adds stage2 trace file.
   681	Refs ADR-023"
   682	```
   683	
   684	---
   685	
   686	### Task 6: Stage 2 全量验证
   687	
   688	**Files:**
   689	- Create: `scripts/eval_stage2.py`
   690	
   691	- [ ] **Step 1: 写验证脚本**
   692	
   693	创建 `scripts/eval_stage2.py`，功能：
   694	1. 用新 02_ocr 跑 11-20 页（需要 Stage 1 已跑完）
   695	2. 统计：双引擎一致率、VLM 输出对齐率、VLM 修正数（VLM 与 Baberu 不同的区域）、VLM 空文本比例、VLM 失败率
   696	3. 人工抽检：VLM 修正是否正确（对比 crop 图）
   697	4. 输出 HTML 报告
   698	
   699	- [ ] **Step 2: 跑验证**
   700	
   701	```bash
   702	cd E:\manga translator agent\amta
   703	py -3.13 scripts/eval_stage2.py
   704	```
   705	
   706	Expected: 10 页跑完，输出 HTML。VLM 对齐率应 >90%（probe B 组 100%），一致率约 60-80%。
   707	
   708	- [ ] **Step 3: 人工抽检 VLM 修正质量**
   709	
   710	检查 14/15 页中 VLM 与 Baberu 不同的区域，判断 VLM 修正是否正确。重点关注：
   711	- 汉字误读修正（如「ハ意様→八意様」）应为正确
   712	- 拟声词/短文本（如「すっ」「ぽ」）VLM 可能改错，这些应在 Stage 3 由 LLM 判断选择
   713	
   714	- [ ] **Step 4: Commit**
   715	
   716	```bash
   717	cd E:\manga translator agent\amta
   718	git add scripts/eval_stage2.py
   719	git commit -m "test(stage2): add eval_stage2.py for dual-engine validation
   720	
   721	Metrics: agreement rate, VLM alignment rate, correction count,
   722	empty rate, failure rate. HTML report with manual sampling.
   723	Refs ADR-023"
   724	```
   725	
   726	---
   727	
   728	## Phase 3: Stage 3 纯文本语义翻译
   729	
   730	### Task 7: 改造 03_translate.py 输入为双引擎文本
   731	
   732	**Files:**
   733	- Modify: `scripts/03_translate.py`
   734	- Modify: `src/amta/translate.py`
   735	- Test: `tests/test_front3_stage3.py`
   736	
   737	- [ ] **Step 1: 写测试**
   738	
   739	创建 `tests/test_front3_stage3.py`：
   740	
   741	```python
   742	"""Stage 3 单元测试：双引擎文本输入 + LLM 选择。"""
   743	import sys
   744	from pathlib import Path
   745	sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
   746	
   747	
   748	def test_translate_input_dual_engine():
   749	    """翻译输入应包含 baberu_text 和 vlm_text。"""
   750	    item = {
   751	        "region_id": "u00",
   752	        "bbox": [10, 10, 50, 50],
   753	        "baberu_text": "では豊ちゃん…",
   754	        "vlm_text": "では豊ちゃん、輝夜様に…",
   755	        "contained_in": None,
   756	        "source_engines": ["det1"],
   757	        "vlm_status": "ok",
   758	    }
   759	    assert item["baberu_text"]
   760	    assert item["vlm_text"]
   761	    # 翻译时应把两个文本都提供给 LLM
   762	
   763	
   764	def test_translate_vlm_failed_fallback():
   765	    """VLM 失败时应只用 baberu_text。"""
   766	    item = {
   767	        "region_id": "u00",
   768	        "bbox": [10, 10, 50, 50],
   769	        "baberu_text": "テスト",
   770	        "vlm_text": None,
   771	        "vlm_status": "failed",
   772	    }
   773	    assert item["vlm_text"] is None
   774	    # 翻译 prompt 应只提供 baberu_text
   775	
   776	
   777	def test_contained_in_merged_translation():
   778	    """嵌套框的文本应在翻译时合并提示。"""
   779	    parent = {"region_id": "u00", "baberu_text": "弟子だからね", "vlm_text": "弟子だからね", "contained_in": None}
   780	    child = {"region_id": "u01", "baberu_text": "落ち着きなさい", "vlm_text": "落ち着きなさい", "contained_in": "u00"}
   781	    # 翻译 prompt 应提示 LLM：u01 嵌套在 u00 中，可能是同一气泡的大小字
   782	    assert child["contained_in"] == "u00"
   783	```
   784	
   785	- [ ] **Step 2: 跑测试确认通过（纯结构测试）**
   786	
   787	Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage3.py -v`
   788	Expected: 3 tests PASS
   789	
   790	- [ ] **Step 3: 修改 translate.py 的 prompt 构建**
   791	
   792	在 `src/amta/translate.py` 中，修改翻译 prompt，将双引擎文本提供给 LLM：
   793	
   794	原 prompt（单文本）：
   795	```
   796	原文：{text}
   797	```
   798	
   799	新 prompt（双引擎）：
   800	```
   801	以下是一个漫画文字区域的两个 OCR 结果：
   802	- Baberu OCR：{baberu_text}
   803	- VLM 校验：{vlm_text or "（VLM 校验失败，仅参考 Baberu）"}
   804	
   805	{contained_in_note}  # 如果有 contained_in，提示嵌套关系
   806	
   807	请结合上下文判断哪个 OCR 结果更准确，并翻译成中文。
   808	```
   809	
   810	如果 `vlm_status != "ok"` 或 `vlm_text is None`，prompt 中只提供 baberu_text。
   811	
   812	如果 `contained_in` 不为 None，prompt 中添加：
   813	```
   814	注意：此区域嵌套在区域 {contained_in} 中，可能是同一气泡的小字/碎碎念，请结合父区域文本判断。
   815	```
   816	
   817	- [ ] **Step 4: 修改 03_translate.py 读取 canon 格式**
   818	
   819	03_translate.py 读取 canon.json 时，从 `item["text"]` 改为读取 `item["baberu_text"]` 和 `item["vlm_text"]`，传递给 translate 函数。
   820	
   821	- [ ] **Step 5: 添加 trace 落盘**
   822	
   823	在 03_translate.py 中添加 `{page}_03_translate_trace.json`，记录：
   824	- LLM 模型/参数
   825	- 每个区域：选择了 baberu 还是 vlm（从 LLM 输出中解析，或让 LLM 在输出中标注）
   826	- 重试次数
   827	- 耗时
   828	
   829	注意：让 LLM 标注选择了哪个文本可能需要修改输出格式。简化方案：trace 中记录每个区域的 baberu_text 和 vlm_text 以及最终译文，由后续分析判断选择了哪个。
   830	
   831	- [ ] **Step 6: 跑测试**
   832	
   833	Run: `cd E:\manga translator agent\amta && py -3.13 -m pytest tests/test_front3_stage3.py tests/test_translate.py -v`
   834	Expected: 全部 PASS（test_translate.py 是旧测试，需确认不被破坏）
   835	
   836	- [ ] **Step 7: 手动验证单页翻译**
   837	
   838	```bash
   839	cd E:\manga translator agent\amta
   840	py -3.13 scripts/03_translate.py --work-id touhou-single-wing \
   841	  --canon workspace/touhou-single-wing/artifacts/page_13_canon.json \
   842	  --out workspace/touhou-single-wing/artifacts/page_13_translation.json \
   843	  --page-idx 13
   844	```
   845	
   846	Expected: 输出 translation.json，译文应准确。重点检查 14 页「では豊ちゃん」是否被正确翻译（VLM 提供了完整文本）。
   847	
   848	- [ ] **Step 8: Commit**
   849	
   850	```bash
   851	cd E:\manga translator agent\amta
   852	git add scripts/03_translate.py src/amta/translate.py tests/test_front3_stage3.py
   853	git commit -m "feat(stage3): refactor translate to accept dual-engine OCR input
   854	
   855	LLM receives both Baberu and VLM text, chooses based on context.
   856	Contained_in nesting info provided for merge decisions.
   857	Adds stage3 trace file.
   858	Refs ADR-023"
   859	```
   860	
   861	---
   862	
   863	### Task 8: 端到端全量验证（11-20 页）
   864	
   865	**Files:**
   866	- Create: `scripts/eval_front3_e2e.py`
   867	
   868	- [ ] **Step 1: 写端到端验证脚本**
   869	
   870	创建 `scripts/eval_front3_e2e.py`，功能：
   871	1. 用完整新流水线（01_detect → 02_ocr → 03_translate）跑 11-20 页
   872	2. 对比旧流水线结果：
   873	   - 检测框数变化
   874	   - OCR 文本数变化
   875	   - 翻译文本数变化
   876	   - 已知漏检文本是否出现在最终译文中（端到端召回率）
   877	   - 总处理时间
   878	3. 输出 HTML 报告：逐页对比 + 汇总指标
   879	
   880	- [ ] **Step 2: 跑端到端验证**
   881	
   882	```bash
   883	cd E:\manga translator agent\amta
   884	py -3.13 scripts/eval_front3_e2e.py
   885	```
   886	
   887	Expected: 10 页全跑完，输出 HTML 报告。
   888	
   889	核心指标：
   890	- 端到端召回率：已知应存在的文本（「では豊ちゃん」「弟子だからね」「じゃ、そういうことで」等）有多少出现在最终译文中
   891	- 框数变化率
   892	- 总处理时间 vs 旧流水线
   893	
   894	- [ ] **Step 3: 人工抽检核心 case**
   895	
   896	检查 14/15/17 页的最终译文：
   897	- 14 页「では豊ちゃん、輝夜様にこの羽根を見せに行ってきます」是否被正确翻译
   898	- 15 页「弟子だからね 落ち着きなさい」是否被正确翻译（大小字合并）
   899	- 17 页"2个大人"的对话是否被检测到并翻译
   900	
   901	- [ ] **Step 4: Commit 验证脚本和报告**
   902	
   903	```bash
   904	cd E:\manga translator agent\amta
   905	git add scripts/eval_front3_e2e.py
   906	git commit -m "test(front3): add end-to-end validation for 11-20 pages
   907	
   908	Full pipeline run: detect -> OCR(dual) -> translate.
   909	Metrics: e2e recall rate, box count delta, processing time.
   910	HTML report with core case sampling.
   911	Refs ADR-023"
   912	```
   913	
   914	---
   915	
   916	## Self-Review
   917	
   918	**1. Spec coverage:**
   919	- Stage 1 重构（砍 build_regions/flatten，absorb_contained 改标记）→ Task 1-3 ✅
   920	- Stage 2 双引擎会诊（VLM contact sheet + 双文本输出）→ Task 4-6 ✅
   921	- Stage 3 纯文本翻译（双引擎输入 + LLM 选择）→ Task 7-8 ✅
   922	- Tracing（每阶段独立 trace）→ Task 2/5/7 中包含 ✅
   923	- 分步验证（每阶段独立验证 + 端到端验证）→ Task 3/6/8 ✅
   924	
   925	**2. Placeholder scan:**
   926	- Task 3 的 eval_stage1.py 核心逻辑用了描述性文字而非完整代码 → 执行 agent 需参考 eval_flatten_fix_v2.py 补全。这是可接受的，因为完整代码较长且有参考模板。
   927	- Task 6/8 同理。
   928	- 无 TBD/TODO/implement later。
   929	
   930	**3. Type consistency:**
   931	- `mark_contained` 输出 `region_id`（u00, u01...）→ 02_ocr.py 和 03_translate.py 都引用 `region_id` ✅
   932	- `contained_in` 字段在 Stage 1 输出 → Stage 2 canon 传递 → Stage 3 prompt 使用 ✅
   933	- `source_engines` 在 Stage 1 输出 → Stage 2 canon 传递 ✅
   934	- `vlm_status` 值：ok/failed/count_mismatch/skipped → 测试和代码一致 ✅
   935	
   936	---
   937	
   938	## Execution Handoff
   939	
   940	Plan complete and saved to `docs/superpowers/plans/2026-08-28-front3-reconstruction.md`.
   941	
   942	**执行前注意事项：**
   943	1. 当前在 `feat/contract-hygiene` 分支，有未提交的 flatten 修复改动。建议新开 worktree/分支（如 `feat/front3-reconstruction`）实施本计划。
   944	2. koharu.exe 需在运行状态（detect + OCR 依赖）。
   945	3. DeepSeek API key 需配置（VLM 校验 + 翻译依赖）。
   946	4. 旧 detection.json/canon.json/translation.json 需备份（验证脚本会自动备份）。
   947	5. build_regions/flatten_regions 代码保留不删（回退用），仅不在主链调用。
   948	
   949	**两个执行选项：**
   950	
   951	1. **Subagent-Driven (recommended)** - 每个 Task 派一个 fresh subagent，任务间 review，快速迭代
   952	2. **Inline Execution** - 在当前会话中按 executing-plans 批量执行，带 checkpoint review
   953	
   954	**Which approach?**
