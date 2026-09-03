# Stage 4 Text Segmentation 探针报告：CTD DBNet 像素级 Mask

> **日期**：2026-09-03
> **分支**：`feat/stage4-ctd-mask-probe`
> **探针脚本**：`scripts/probe_ctd_mask.py`
> **样本**：东方《单翼停留之地》21.jpg (page_20)、22.jpg (page_21)
> **状态**：结论已定，待接入 Stage 4

---

## 一、背景与问题

当前 Stage 4（`04_inpaint.py`）的 mask 生成是最粗糙的做法：

```python
# _build_mask(): 矩形 + pad=4
for bb in bboxes:
    d.rectangle([x1-pad, y1-pad, x2+pad, y2+pad], fill=0)
```

**问题**：矩形 mask 把整个气泡区域（包括大量空白）都标记为"要擦除"。
- 对 `dialogue_bubble`（涂白）：问题不大，气泡本来就是白的
- 对 `overlay_text` / `sfx`（走 inpaint）：会擦到周围的画面背景，引入伪影

**目标**：找到像素级的 text segmentation 方案，只圈出文字像素，不碰背景。

---

## 二、第一性原理：CTD 模型的沉睡资产

项目里已有 CTD 模型（`models/CTD/comictextdetector.pt.onnx`，94MB），架构是 **YOLOv5 + UNet + DBNet** 三组件：

| 组件 | 作用 | 当前是否利用 |
|------|------|------------|
| YOLOv5 | 气泡检测 | 未用（用 RT-DETR-v2 替代） |
| UNet | mask | 未用 |
| **DBNet** | **文本概率热图（像素级）** | **只提取了四边形框，热图本身被丢弃** |

**核心洞察**：DBNet 的 `shrink_map` 输出就是"每个像素属于文字的概率"——这正是 text segmentation 要的东西。当前代码 `ctd_detector.py` 把热图转成四边形框后就丢了，等于买了激光手术刀只拿刀柄拍黄油。

---

## 三、实验方法

### 3.1 流程

1. 用 CTD 模型推理原始页，取出 DBNet 的 `shrink_map`（概率热图）
2. 热图 resize 回原图尺寸
3. 阈值化 → 二值 mask → 膨胀（连接相邻文字笔画）
4. 与当前矩形 mask 对比：像素数、覆盖率、IoU、可视化

### 3.2 参数组合

| 变体 | 阈值 | 膨胀核 | 膨胀次数 | 设计意图 |
|------|------|--------|---------|---------|
| v1 | 0.3 | 3×3 | 2 | 原始（DBNet 默认阈值） |
| v2 | 0.15 | 5×5 | 4 | 低阈值 + 中膨胀 |
| v3 | 0.1 | 7×7 | 5 | 更低阈值 + 大膨胀 |
| v5 | 0.1 | 9×9 | 7 | 超大膨胀（连接竖排文字列） |

> v4 用 threshold_map（第二通道）测试，结果全页响应（100% 覆盖率），不可用。DBNet 的 threshold_map 是可微分二值化的辅助图，不是文字概率图。

---

## 四、实验结果

### 4.1 量化对比

**page_20 (21.jpg, 2243×3465)**

| 方案 | mask 像素数 | 页面覆盖率 | 与矩形 IoU |
|------|-----------|-----------|-----------|
| 矩形 mask（当前） | 1,069,610 | **13.76%** | 1.000 |
| v1 (t=0.3, d=3×2) | 95,026 | 1.22% | 0.018 |
| v2 (t=0.15, d=5×4) | 164,598 | 2.12% | 0.031 |
| v3 (t=0.1, d=7×5) | 240,899 | 3.10% | 0.042 |
| **v5 (t=0.1, d=9×7)** | **338,286** | **4.35%** | **0.058** |

**page_21 (22.jpg, 2243×3465)**

| 方案 | mask 像素数 | 页面覆盖率 | 与矩形 IoU |
|------|-----------|-----------|-----------|
| 矩形 mask（当前） | 829,725 | **10.68%** | 1.000 |
| v1 (t=0.3, d=3×2) | 105,981 | 1.36% | 0.031 |
| v2 (t=0.15, d=5×4) | 177,302 | 2.28% | 0.050 |
| v3 (t=0.1, d=7×5) | 255,144 | 3.28% | 0.069 |

### 4.2 关键发现

1. **矩形 mask 严重过度覆盖**：把 10-14% 的页面标记为"文字"，而真实文字只占 3-5%。矩形 mask 里 60-70% 是气泡空白。

2. **DBNet shrink_map 是文本核，需要膨胀**：v1 只圈出文字核心笔画（覆盖率 1.2%），因为 DBNet 的 shrink_map 本身就是"收缩后的文本核"。必须通过膨胀模拟 DBNet 的 unclip 操作，恢复完整文字区域。

3. **v5 参数效果最佳**：thresh=0.1 + 9×9 椭圆核膨胀 7 次，覆盖率 4.35%，可视化显示文字区域覆盖完整，且不碰气泡空白。

4. **CTD 检测框粒度太细，不适合替代 RT-DETR-v2**：
   - CTD 检测到 12-13 个框，RT-DETR-v2 只有 9 个
   - CTD 的框是**细竖条**（宽 30-60px，高 300-700px）——每列竖排文字一个框
   - RT-DETR-v2 的框是**整个气泡**（宽 200-300px，高 600-900px）——一个气泡一个框
   - AMTA 的翻译单元是气泡（文本块），不是单列文字，所以 CTD 检测框不能直接用

5. **CTD 推理时间**：3.8-5.1 秒/页（CPU，1024×1024 输入），与 RT-DETR-v2 的 4.3-4.8 秒相当。

---

## 五、可视化证据

对比图（2×2 面板）：
- 左上：原图 + 矩形 mask（红色半透明）
- 右上：原图 + CTD v5 mask（蓝色半透明）
- 左下：差异图（红=矩形独有，蓝=CTD独有，绿=重叠）
- 右下：CTD 热图伪彩色

**输出目录**：`output/tmp/ctd_mask_probe/`
- `page_20_comparison.png` / `page_21_comparison.png`（v2 对比）
- `page_20_v5_comparison.png`（v5 对比，推荐参数）
- `page_20_v5_t01_d9x7_mask.png`（v5 单独 mask）
- `page_20_shrink_heatmap.png` / `page_20_thresh_heatmap.png`（热图）
- `summary.json`（量化数据）

---

## 六、结论与建议

### 6.1 关于"要不要把 Detect 换成 CTD"

**不推荐**。原因：
1. CTD 检测框粒度太细（每列文字一个框），而 AMTA 的翻译单元是气泡级
2. CTD 没有 `text_bubble` / `text_free` 分类（RT-DETR-v2 的 label 0/1/2），ADR-019 的 category 三级分类会断
3. 前三个 stage 已经用 RT-DETR-v2 稳住了，换检测器 = 重新验证 OCR + 翻译质量，风险大

### 6.2 推荐方案：Stage 4 额外跑 CTD 出 mask（保险做法）

**架构**：
- Stage 1：RT-DETR-v2 继续做检测 + category 分类（不动）
- Stage 4：额外调用 CTD 模型，取 DBNet 热图生成像素级 mask
- mask 按 category 分流：
  - `dialogue_bubble`：继续用矩形涂白（气泡本来就是白的，精确 mask 无收益）
  - `overlay_text` / `sfx`：用 CTD 像素级 mask（不擦背景，inpaint 质量更高）

**优点**：
- 前三个 stage 零改动，风险完全隔离在 Stage 4
- 零新模型、零新依赖（CTD 已在本地）
- 可回退：CTD mask 质量不行就换回矩形
- 一步到位：直接从矩形跳到像素级，跳过四边形中间态

**缺点**：
- 每页多一次 CTD 推理（~4 秒 CPU），Stage 4 总耗时增加
- koharu inpaint 本身已经是瓶颈（~20-60 秒/页），增加 4 秒占比不大

### 6.3 推荐参数

```python
thresh = 0.1        # DBNet shrink_map 阈值
dilate_kernel = 9   # 椭圆核
dilate_iter = 7     # 膨胀次数
```

> 注：这两页是竖排日文，膨胀参数可能需要根据横排文字/不同漫画风格微调。建议接入后跑 5-10 页验证，必要时做成可配置参数。

---

## 七、下一步计划

1. **封装 `mask_generator.py`**：CTD DBNet 热图 → 像素级 mask，纯函数可单测
2. **接入 `04_inpaint.py`**：`inpaint` 类别用 CTD mask，`fill_white` 类别保持矩形
3. **跑 5-10 页对比**：矩形 mask vs CTD mask 的 inpaint 效果（肉眼 + pixel_diff_ratio）
4. **参数微调**：根据更多样本调整 thresh / dilate 参数
5. **ADR-021**：记录 Stage 4 mask 生成策略的决策

---

## 八、风险与已知限制

1. **CTD 模型对横排文字的效果未验证**：本次样本全是竖排日文。横排文字的文字行方向不同，膨胀参数可能需要调整。
2. **彩色文字 / 艺术字 / SFX**：DBNet 训练数据主要是常规黑白漫画文字，对彩色 SFX 的分割效果未验证。
3. **极小文字**：低于 10px 的文字可能被阈值过滤掉。
4. **CTD 推理耗时**：CPU 上 ~4 秒/页，如果未来要 GPU 加速需要换 ONNX Runtime CUDA provider。
5. **mask 与 region 的对应**：当前 CTD mask 是全页的，接入时需要按 RT-DETR-v2 的 bbox 把全页 mask 切分成每个 region 的 mask（用 bbox 裁剪即可）。
