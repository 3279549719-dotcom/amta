# Stage 4 Inpainting 速度优化 — A/B 实验设计

> **日期**：2026-09-04
> **分支**：`feat/stage4-inpaint-speed-optimization`（基于 `feat/stage4-outside-text-removal @ f50985a`）
> **状态**：设计待评审

---

## 一、背景与问题

当前 Stage 4 框外字去除（`04_inpaint.py`）对 `text_free` 区域采用**整页 Koharu lama-manga 推理**：

- 每页调用 Koharu REST API（`127.0.0.1:4000`），完整走 `wait_server → close_project → create_project → import_page → run_inpaint → fetch_inpainted` 六步
- 即使只有 3 个小 text_free 框，也把整页（2243×3465 ≈ 777 万像素）送给深度学习模型
- 实测 3 个 free 框耗时 **130-400 秒/页**，与框面积和数量成正比

瓶颈根因（第一性原理）：
1. **计算量与像素面积成正比**：LaMa 是全卷积网络，整页推理计算量远大于实际文字区域
2. **Koharu 服务化开销**：每次调用 6 次 HTTP 往返 + project 重建 + 整页上传下载
3. **CPU 推理**：当前 Koharu 服务为 CPU 推理，单页 1920×1280 级别约 23s

---

## 二、实验目标

通过 A/B 测试量化两种优化手段的单独收益和叠加收益，为是否合入主线提供数据依据：

- **P0（裁剪 inpaint）**：只 crop text_free 区域（+padding）送模型，结果贴回原图
- **P1（去 Koharu 本地推理）**：用 `simple-lama-inpainting`（ONNX）本地加载模型，消除 HTTP 开销
- **P1+GPU（核显加速）**：在 P1 基础上尝试 `onnxruntime-directml` 调用 Intel 核显

---

## 三、测试样本

| 项目 | 值 |
|---|---|
| 作品 | 东方《单翼停留之地》 |
| 原始图片 | `D:\我的汉化\汉化作品\东方\单翼停留之地\11.jpg` ~ `15.jpg` |
| Detection 工件 | `workspace/touhou-single-wing-fresh/artifacts/page_10_detection.json` ~ `page_14_detection.json`（0-based 命名） |
| 页码映射 | `page_{N-1}_detection.json` ↔ `N.jpg` |

各页 text_free 框数量：

| 页 | jpg | detection 文件 | text_bubble | text_free |
|---|---|---|---|---|
| 11 | 11.jpg | page_10_detection.json | 4 | 3 |
| 12 | 12.jpg | page_11_detection.json | 3 | 1 |
| 13 | 13.jpg | page_12_detection.json | 3 | 3 |
| 14 | 14.jpg | page_13_detection.json | 8 | 4 |
| 15 | 15.jpg | page_14_detection.json | 3 | 4 |

---

## 四、四组对比方案

### 组 A：Baseline（当前方案）

- 整页送 Koharu lama-manga（CPU）
- `--refine-mask --engine lama-manga`
- 作为速度和质量的基准

### 组 B：P0-only（裁剪 + Koharu）

- 每个 text_free 框 crop 出来（padding=64px），单独送 Koharu inpaint
- 结果贴回原图，text_bubble 仍直接涂白
- 变量：只验证"裁剪"的收益，仍走 Koharu HTTP

### 组 C：P0+P1-CPU（裁剪 + 本地 LaMa CPU）

- 裁剪同上
- 用 `simple-lama-inpainting`（ONNX 模型）本地推理，消除 Koharu HTTP 开销
- CPU 推理

### 组 D：P0+P1-GPU（裁剪 + 本地 LaMa 核显）

- 在组 C 基础上，`onnxruntime` 替换为 `onnxruntime-directml`
- 尝试调用 Intel 核显加速
- 若环境不支持（驱动/DirectML 不可用），本组降级为"不适用"，不阻塞实验

---

## 五、速度测量

- **端到端耗时**：mask 精修 + crop + inpaint + 贴回，每页计时
- **重复次数**：每组每页跑 3 次取平均（排除首次模型加载冷启动，P1 组单独记录模型加载时间）
- **分项计时**（P1 组）：模型加载 / 单次推理 / mask 生成 / 贴回，分别记录
- **Koharu 组**：记录 HTTP 总开销 vs 纯推理等待时间

---

## 六、质量测量

1. **四格对比图**：原图 / Baseline / P0 / P0+P1，同页并排
2. **框区域放大**：每个 text_free 框 4x 放大，观察：
   - 背景修复质量（纹理/渐变是否连贯）
   - 边缘拼接痕迹（crop 边界是否有色差/硬边）
   - 是否有文字残留
3. **pixel_diff_ratio**：与原图的像素差异比（越低说明只改了文字区域，未误伤背景）
4. **人工评分**：报告中留 1-5 分空栏，由用户填写

---

## 七、实施步骤

### Step 1：环境准备
- `pip install simple-lama-inpainting onnxruntime`（P1 依赖）
- 尝试 `pip install onnxruntime-directml`（核显组，可选）
- 确认 Koharu 服务运行在 `127.0.0.1:4000`

### Step 2：写实验脚本 `scripts/exp_inpaint_speed.py`
- 支持 `--mode baseline|p0|p1_cpu|p1_gpu`
- 支持 `--pages 11,12,13,14,15`
- 支持 `--repeat 3`
- 输出：`output/tmp/inpaint_speed_exp/` 下每组每页的 clean 图 + timing JSON
- **不修改主线 `04_inpaint.py`**，实验脚本独立

### Step 3：实现 P0 裁剪逻辑
- 对每个 text_free 框：crop（bbox + padding=64，边界 clamp）
- 构造 crop 级 mask（精修 mask 只在 crop 区域）
- 送 Koharu / 本地模型推理
- 结果贴回原图对应位置

### Step 4：实现 P1 本地推理
- 封装 `LocalLamaInpainter` 类：加载 ONNX 模型，`inpaint(image, mask) -> image`
- 支持 CPU / DirectML 两种 provider
- 模型首次加载计时，后续复用

### Step 5：跑实验
- 5 页 × 4 组 × 3 次 = 60 次推理
- Baseline 组耗时最长（130-400s/页 × 5 × 3 ≈ 33-100 分钟），可后台运行

### Step 6：生成 HTML 报告
- 复用 `scripts/gen_stage4_results_html.py` 的 base64 嵌入 + 自包含 HTML 模式
- 内容：速度柱状图 + 每页四格对比 + 框放大 + 结论表格
- 输出：`output/tmp/inpaint_speed_exp/report.html`

---

## 八、输出物

| 产物 | 路径 |
|---|---|
| 实验脚本 | `scripts/exp_inpaint_speed.py` |
| 本地推理封装 | `src/amta/local_lama_inpainter.py` |
| 实验结果（clean 图 + timing） | `output/tmp/inpaint_speed_exp/` |
| HTML 对比报告 | `output/tmp/inpaint_speed_exp/report.html` |
| 设计文档（本文档） | `docs/superpowers/specs/2026-09-04-inpaint-speed-ab-test.md` |

---

## 九、风险与回退

| 风险 | 应对 |
|---|---|
| P0 裁剪贴回有边缘痕迹 | 报告中放大展示，由用户判断是否可接受；可增加 feather 边缘融合 |
| 本地 simple-lama ≠ Koharu lama-manga（模型不同） | 报告中明确标注，质量差异部分来自模型而非架构 |
| 核显 DirectML 调不起来 | 组 D 降级为"不适用"，不阻塞 A/B 结论 |
| Baseline 组跑太久（>2小时） | 可先跑 11-13 页（3页），14-15 页后续补 |
| 实验脚本影响主线 | 独立脚本，不改 `04_inpaint.py`，实验完可删 |

---

## 十、决策标准

实验完成后，根据以下标准决定是否合入：

1. **速度**：P0+P1 组端到端耗时 < 30s/页（当前 130-400s 的 1/4 以下）
2. **质量**：P0+P1 组与 Baseline 组视觉质量无显著下降（用户评分 ≥ Baseline 的 80%）
3. **可维护性**：本地推理依赖（simple-lama + onnxruntime）可接受，不引入过重依赖

若满足以上条件，将 P0+P1 整合进 `04_inpaint.py` 主线；否则保留 Koharu 方案，仅合入 P0 裁剪优化。
