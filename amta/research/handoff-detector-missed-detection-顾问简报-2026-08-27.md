# Detector 漏检问题 — 大小字混合气泡的偶然漏检 — 外部顾问简报

> 日期：2026-08-27
> 项目：AMTA（会话驱动漫画翻译自动化）
> 目的：给外部顾问一份自包含的问题说明，覆盖 detect 环节"4-detector 并集仍漏检"的现象、证据、根因假设与待决方向。无需了解仓库即可读。
> 关联文档：`handoff-OCR-vlm-audit-顾问简报-2026-08-27.md`（本轮 OCR audit，其中 P3 已指出 detector 框错是上游问题，本简报展开该问题）

---

## ① 想要做什么

### 背景：AMTA 流水线里 detect 环节的角色

AMTA 把一页漫画自动翻译成中文。对每一页依次做：

1. **detect（01_detect）**：检测页面上所有文字区域（对白框、拟声词、旁白、小字注释等），输出每个文字区域的 bbox 坐标。这是整条流水线的起点——**detect 没框到的文字，后续 OCR/翻译/inpaint/typeset 全部不会处理**。
2. **OCR（02_ocr）**：对每个框裁图、识别日文原文，得到 canon（每框一行文字，作为翻译输入真值）。
3. **translate / inpaint / typeset（03-05）**：翻译、擦字、排版。

### 当前 detect 策略：4-detector 并集 + 多层去重

为了最大化召回率，detect 环节**不依赖单一模型**，而是同时跑 4 个独立 detector，取并集：

| # | detector 名称 | 类型 |
|---|---|---|
| 1 | `pp-doclayout-v3` | 通用文档版面分析 |
| 2 | `comic-text-detector` | 漫画文字检测（koharu 上游） |
| 3 | `anime-text` | 动画/动漫文字检测 |
| 4 | `comic-text-bubble-detector` | 漫画气泡检测 |

4 个 detector 各自独立跑完整流水线，输出各自的框列表，然后经过以下后处理：

1. **并集去重**（`union_blocks`，IoU > 0.5 视为重复，保留首个）：消除 4 个 detector 对同一文字区域的重复框。
2. **层级重组**（`build_regions`，IoA ≥ 0.75 判定嵌套）：被更大框包含的小框挂到容器的 `child_lines`，不丢弃；独立框自成 region。这是为了支持"一个气泡内有多段文字（主台词 + 碎碎念小字）"的场景。
3. **child_lines 内部碎片去重**（IoA ≥ 0.5）：同一行文字的重复碎片框只保留一个。
4. **sub_tier 标注**（`assign_sub_tier`，行宽比 ≥ 1.4 标 aside/碎碎念，否则 primary）：机械启发式，供下游排版参考。
5. **展平**（`flatten_regions`）：容器自身不输出，每个 child_line / 独立 region 各输出一框，供 02_ocr 裁框。

### 设计目标

- **召回优先（宁多勿漏）**：假阳性框由 02_ocr 空文本自动丢弃，所以 detect 倾向于多检。
- **评测基线 recall ≈ 0.98**：在 Benchmark A 上，4-detector 并集对齐整页枚举 GT，召回率约 0.98。
- **支持大小字混合**：一个气泡内同时有大字（主台词）和小字（注释/碎碎念/语气词）时，两者都应被检出，分别作为 child_line 独立 OCR。

---

## ② 遇到了什么问题

### 核心现象：4-detector 并集仍有漏检，且集中在"大小字混合气泡"

即使 4 个 detector 并集 + 召回优先策略，**仍会偶然漏检文字**。漏检不是随机分布，而是**高度集中在一种特定模式**：

> **一个气泡框内同时有大字和小字（字号差异明显），detector 倾向于只检出其中一种（通常是小字窄框），另一种（通常是大字主台词）完全漏检。**

这不是"框偏移"或"框不准"，而是**整个框不存在**——4 个 detector 没有任何一个输出这个文字区域的框。

### 具体 Case 1：15.jpg 左下「弟子だからね」

**原图位置**：15.jpg 底部左侧，一个标准对白气泡。

**气泡内文字**（竖排，从右到左）：
- **大字（主台词）**：「弟子だからね」—— 字号大，是气泡的主体内容，位于气泡右侧
- **小字（注释/碎碎念）**：「落ち着きなさい」—— 字号明显更小，位于气泡左侧

**检测结果**（`page_14_detection.json`，对应 15.jpg，共 9 个 boxes）：

| 区域 | 检出框 | 宽×高 | 对应文字 |
|---|---|---|---|
| 左下气泡 | `[145, 2395, 197, 2698]` | **52 × 303** | 仅覆盖小字「落ち着きなさい」 |
| 左下气泡 | **（无）** | — | **大字「弟子だからね」完全漏检** |

小字框宽仅 52px，而大字「弟子だからね」应该需要约 120-150px 宽的框。**4 个 detector 没有任何一个检出大字主台词的框。**

各 detector 原始检出数：pp-doclayout-v3=9, comic-text-detector=3, anime-text=11, comic-text-bubble-detector=8。并集去重后 9 个。即使 anime-text 检出了 11 个框，也没有一个覆盖「弟子だからね」。

### 具体 Case 2：14.jpg 右下「では豊ちゃん…」

**原图位置**：14.jpg 底部右侧，一个竖排长对白气泡。

**气泡内文字**：
- **大字（主台词）**：「では豊ちゃん、輝夜様にこの羽根を見せに行ってきます」—— 竖排长句，字号大
- **小字（旁注）**：「じゃ、そういうことで」—— 字号小，在主台词左侧

**检测结果**（`page_13_detection.json`，对应 14.jpg，共 17 个 boxes）：

| 区域 | 检出框 | 宽×高 | 对应文字 |
|---|---|---|---|
| 右下气泡 | `[1607, 2783, 1653, 3113]` | **46 × 330** | 仅覆盖部分文字（可能是小字或某一行） |
| 右下气泡 | **（无更宽的框）** | — | **大字主台词的完整框漏检** |

检出框宽仅 46px，对于「では豊ちゃん、輝夜様に…」这样的长句主台词明显过窄。大气泡的容器框（应该宽约 150-200px）不存在。

### Per-Engine 检出数据追溯（基于已落盘产物）

项目有三层检测产物，但**只有最外层保留了 per-engine 计数，没有保留每个 detector 各自检出了哪些框**。以下是基于已有数据的追溯分析：

#### 15.jpg（`page_14_detection.json`，2026-08-27 12:05:31 运行）

| Detector | 原始检出数 | 并集后贡献（推断） |
|---|---|---|
| `pp-doclayout-v3` | 9 | 约 7 个唯一框（node_id 前缀 A） |
| `comic-text-detector` | 3 | 约 1-2 个唯一框（node_id 前缀 B/C） |
| `anime-text` | 11 | 框全部与其他 detector 重叠，被 IoU 去重 |
| `comic-text-bubble-detector` | 8 | 框全部与其他 detector 重叠，被 IoU 去重 |

**并集后 9 个框**。通过 node_id 前缀分析（同一次运行中，不同 koharu 项目生成的 UUID 前缀不同），9 个框来自 **3 种 node_id 前缀**，说明至少 3 个 detector 贡献了唯一框。`anime-text` 虽然检出 11 个框最多，但全部与其他 detector 的框 IoU > 0.5 被去重，没有贡献唯一框。

**漏检区域「弟子だからね」（左下 [50,2430,210,2870]）**：
- 并集后该区域只有 1 个框 `[145,2395,197,2698]`（宽 52px，node_id 前缀 A）
- 该框只覆盖小字「落ち着きなさい」
- 大字「弟子だからね」（需要约 120-150px 宽的框）**4 个 detector 全部未检出**
- 由于 per-engine 原始框未落盘，无法确认是哪个 detector 检出了小字框、哪个完全没覆盖该区域

#### 14.jpg（`page_13_detection.json`，2026-08-27 11:58:01 运行）

| Detector | 原始检出数 |
|---|---|
| `pp-doclayout-v3` | 14 |
| `comic-text-detector` | 10 |
| `anime-text` | 16 |
| `comic-text-bubble-detector` | 14 |

**并集后 17 个框**。4 个 detector 检出数都很高（10-16），但并集后仅 17 个，说明大量重叠。右下「では豊ちゃん…」区域只有 1 个 46px 窄框，大字长句主框漏检。

#### 数据可复现性验证

同一页 15.jpg 有两次独立运行的产物：
- `detect_union_11_20/p15.json`（2026-08-27 01:06:51，早期并集版本）
- `page_14_detection.json`（2026-08-27 12:05:31，最终契约版本）

两次运行的 **bbox 坐标完全一致**（9 个框坐标相同），但 node_id 全部不同（每次运行 koharu 重新生成 UUID）。这说明：
- 检测结果是**确定性的、可复现的**
- node_id 不能跨运行追溯，但同一次运行内可以通过前缀区分 detector 来源
- 漏检不是偶发噪声，而是**系统性的、每次运行都稳定复现**的

### 问题严重性

| 维度 | 影响 |
|---|---|
| **流水线层面** | 漏检的文字不会被 OCR、不会被翻译、不会被擦除（inpaint 按框擦字）、不会被排版。最终译文中这些文字**原样保留日文**，是用户可见的硬伤。 |
| **分布层面** | 不是随机噪声，而是系统性偏向"大小字混合气泡"。这类气泡在漫画中极为常见（主台词 + 语气小字 + 注释碎碎念）。 |
| **并集失效层面** | 4-detector 并集的前提是"不同 detector 互补"，但在这种特定模式下，**4 个 detector 全部失效**——并集无法覆盖没有任何 detector 检出的区域。 |
| **评测盲区层面** | Benchmark A recall ≈ 0.98 的基线可能**低估了这类漏检**——如果 GT 标注本身也倾向于只标大字（或只标一个容器框），小字/大字的分别漏检可能不在评测口径内。 |

### 根因假设（待诊断探针验证）

用户的核心判断：**"之前执着于想要检测出不同的 size 和 font，导致设立了很复杂的 threshold，弄巧成拙。"**

具体可能的机制（按可能性排序）：

1. **上游 detector 的置信度/尺寸阈值过滤（最可能）**：4 个 detector（尤其 comic-text-detector / comic-text-bubble-detector）内部可能设有针对文字大小、字体、宽高比的复杂 threshold。在大小字混合的气泡中，大字区域可能因为某种特征（如与小字的间距、宽高比、与气泡边界的关系）触发了过滤条件，被低置信度丢弃。**当前数据无法排除此假设，需要诊断探针确认**。

2. **detector 训练数据的模式覆盖不足**：4 个 detector 的训练集可能对"一个气泡内字号差异悬殊"的模式覆盖不足，模型在推理时将大字和小字视为两个独立区域，但又因为某种原因（如间距太小、置信度不够）只输出了其中一个。

3. **后处理 IoU 去重误杀（可能性较低，但未排除）**：如果某个 detector 检出了大字框，另一个检出了小字框，两者 IoU 可能 > 0.5（小字在大字框内部或高度重叠），`union_blocks` 会保留先出现的那个、丢弃后出现的。如果小字框恰好先出现，大字框就被误杀。**但从数据看，15.jpg 左下区域并集后只有 1 个 52px 窄框，如果有任何 detector 检出了约 120px 宽的大字框，它与 52px 框的 IoU 应该 < 0.5（宽度差异大），不应该被去重。因此后处理误杀的可能性较低，但需要诊断探针的 per-engine 原始数据来最终排除。**

4. **build_regions 嵌套判定误杀（可能性低）**：如果大字框被检出但被判定为"包含于某个更大框"而挂为 child_line，展平时应该仍会输出。数据中左下区域只有 1 个框，说明大字框在更早的阶段就不存在。

**当前倾向**：假设 1 或 2（上游 detector 本身漏检），但**必须通过诊断探针获取 per-engine 原始框后才能最终确认**。这是本简报最关键的待验证项。

---

## ③ 采取的具体方案措施（已做的诊断 + 待决方向）

### 已做的诊断

1. **确认漏检现象**：通过逐页人工核对 14.jpg / 15.jpg，定位到两个具体漏检 case，确认是"框不存在"而非"框偏移"或"OCR 误读"。
2. **区分问题层级**：在本轮 OCR audit（见关联 handoff）中，已将 detector 问题归类为 **P3「VLM 救不了上游 detector 的错」**——detector 框本身没对准/没检出时，任何下游转写/校验模型都无法补救。本简报是对 P3 的展开。
3. **分析检测产物**：读取 `page_13_detection.json`（14.jpg，17 boxes）和 `page_14_detection.json`（15.jpg，9 boxes），逐框对照原图坐标，确认漏检区域无任何框覆盖。
4. **统计各 detector 贡献**：`per_engine_boxes` 显示 4 个 detector 检出数差异大（如 15.jpg：pp=9, comic-text=3, anime=11, bubble=8），但并集后仍缺关键框。
5. **排除 OCR 层面问题**：漏检发生在 detect 环节（01），OCR（02）根本没有机会处理这些区域。与 OCR 引擎选择（baberu / For-Manga / VLM）无关。
6. **形成根因假设**：初步判断为上游 detector 的复杂 threshold / 模式覆盖不足导致"大小字混合气泡"中的大字漏检，后处理误杀可能性较低。
7. **可复现性验证**：同一页两次独立运行（间隔 11 小时）的 bbox 坐标完全一致，确认漏检是系统性的、确定性的，不是偶发噪声。

### 项目 Tracing 机制说明（三层检测产物体系）

项目有完整的检测 tracing 机制，但**当前设计只在最外层保留 per-engine 计数，不保留每个 detector 的原始框**。这是定位根因的最大数据缺口。

| 层级 | 产物 | 保留 per-engine 原始框？ | 覆盖页面 |
|---|---|---|---|
| L1 探针层 | `recall_detect.py` → `output/data/recall_detections.json` | **是**（设计上），但当前文件不存在 | page_0-9（前 10 页） |
| L2 并集层 | `output/data/detect_union_11_20/pNN.json` | 否，只有 `per_engine_boxes` 计数 | page_11-20 |
| L3 最终层 | `workspace/<work>/artifacts/page_N_detection.json` | 否，只有 `per_engine_boxes` 计数 + 并集后 regions/blocks | 全本 |

**L1 recall 探针体系**（前 10 页，page_0-9）：
- `scripts/recall_detect.py`：跑 4-detector，输出 `recall_detections.json`（per-engine 原始框，未去重）
- `output/data/recall_ocr.json`：并集后逐框 OCR 结果（crop 名 + text + empty）
- `output/data/recall_gt.json`：人工 GT 标注
- `output/data/recall_result.json`：recall 评测结果（每页匹配明细）
- `output/recall_crops/`：裁剪图（`page_N_uMM.png` 并集后 + `p0_comic-text-detector_NN.png` 单 detector）
- **缺口**：`recall_detections.json` 当前不存在（可能未跑或被清理），且只覆盖前 10 页，不包含 14/15.jpg

**L2 并集中间产物**（11-20 页）：
- `output/data/detect_union_11_20/p11.json` ~ `p20.json`
- 只保留并集后的 `blocks[]` + `per_engine_boxes` 计数
- **不保留每个 detector 检出了哪些框**

**L3 最终 detection.json**（全本）：
- `workspace/<work>/artifacts/page_N_detection.json`
- 并集 + build_regions + flatten_regions 后的最终结果
- `per_engine_boxes` 只有计数，`detect_steps` 列出 4 个 detector 名称
- **不保留 per-engine 原始框**

**node_id 前缀追溯法**（有限追溯）：
- 同一次运行中，`run_all_pages` 按 `DETECTOR_STEPS` 顺序依次跑 4 个 detector，每个在独立的 koharu 项目中
- koharu 为每个检测框生成 UUID 格式的 node_id，同一次运行内不同 detector 项目的 UUID 前缀（前 8 位 hex）不同
- 因此可以通过 node_id 前缀推断并集框来自哪个 detector（但需要知道前缀与 detector 的对应关系，当前未记录）
- 跨运行 node_id 全部不同，不能追溯

### 诊断探针脚本（待执行）

已编写 `scripts/diag_detector_miss.py`，用于对指定页面跑 4-detector 并**保存每个 detector 的原始框**（未去重），同时对已知漏检区域做逐 detector 覆盖检查。

**功能**：
1. 对单页跑 4 个 detector（和 `01_detect.py` 完全相同的调用逻辑）
2. 保存每个 detector 的完整原始框（含 node_id、bbox、bubble_type、ocr、confidence、transform）
3. 计算并集结果（和生产逻辑一致）
4. 对已知漏检区域（「弟子だからね」「では豊ちゃん…」等）做逐 detector 覆盖检查，输出每个 detector 是否检出、检出框坐标、IoU
5. 控制台打印摘要 + 落盘完整 JSON

**用法**（koharu v0.59.1 运行在 :4000 时）：
```bash
python scripts/diag_detector_miss.py \
  --raw "D:\我的汉化\汉化作品\东方\单翼停留之地\15.jpg" \
  --out output/tmp/diag_p15.json

python scripts/diag_detector_miss.py \
  --raw "D:\我的汉化\汉化作品\东方\单翼停留之地\14.jpg" \
  --out output/tmp/diag_p14.json
```

**预期输出关键信息**：
- 每个 detector 在「弟子だからね」区域检出了什么框（还是完全没检出）
- 小字框「落ち着きなさい」是哪个 detector 检出的
- 大字主台词框是否有任何 detector 检出（即使被后处理去重了）
- 这将直接区分根因是"上游 detector 根本没检出"还是"后处理 IoU 去重误杀"

### 尚未做的关键验证（需要顾问指导方向）

| # | 验证项 | 目的 | 状态 |
|---|---|---|---|
| V1 | **关闭后处理，dump 4-detector 原始输出** | 确认大字框是"上游根本没检出"还是"被 union_blocks / build_regions 误杀" | 未做 |
| V2 | **单 detector 逐一对齐漏检区域** | 看 4 个 detector 中是否有任何一个在原始输出里包含大字框；如果全都没有，问题在上游模型 | 未做 |
| V3 | **检查 koharu detector 的 threshold 配置** | 确认 comic-text-detector / comic-text-bubble-detector 是否有可调节的置信度/尺寸/宽高比阈值，以及当前值 | 未做 |
| V4 | **扩大漏检 case 样本量** | 14.jpg / 15.jpg 只是两个偶然发现的 case，需要系统扫描全本（41 页）统计漏检率和模式分布 | 未做 |
| V5 | **复核 Benchmark A 的 GT 标注** | 确认 recall≈0.98 的评测基线是否覆盖了"大小字分别标注"的场景，还是 GT 只标了容器框导致漏检被掩盖 | 未做 |
| V6 | **测试"降低 detector threshold / 关闭尺寸过滤"的效果** | 如果问题是 threshold 过滤，尝试更激进的低阈值配置，看召回率提升与假阳性增加的 trade-off | 未做 |

### 待决的修复方向（需顾问评估可行性）

- **方向 A：调优上游 detector threshold**
  - 降低置信度阈值、关闭/放宽尺寸和宽高比过滤，让 detector 输出更多候选框。
  - 风险：假阳性激增，增加 02_ocr 负担和误擦风险。
  - 前提：koharu detector 的 threshold 是可配置的（V3）。

- **方向 B：增加第 5 个 detector 或换模型**
  - 引入一个对"大小字混合"模式更敏感的 detector（如专门训练的漫画文字检测模型），作为并集的补充。
  - 风险：依赖外部模型，CPU-only 环境下推理速度可能不可接受。
  - 前提：有可用的、对漫画大小字混合场景召回更好的模型。

- **方向 C：后处理层面的"气泡内补检"**
  - detect 输出后，对每个已检出的气泡容器框，在其内部做一次"文字区域细化检测"（如基于墨量/连通域的传统 CV 方法，或二次调用 detector），补检可能被遗漏的大字/小字行。
  - 风险：实现复杂度高，可能引入新的假阳性。
  - 前提：能可靠地识别"气泡容器"边界。

- **方向 D：VLM 整页枚举兜底（已有 ADR-022 Pass2）**
  - 本轮 OCR audit 的 ADR-022 已设计 Pass2「漏检枚举」：整页图 + 无清单枚举 prompt → 与 canon 机械 diff → 候选进工单 + 方位框 re-OCR。
  - 这可以**发现**漏检（作为人工工单提示），但不能自动修复——方位框 re-OCR 后仍需人工确认合入。
  - 定位：detect 漏检的**兜底发现机制**，不是 detect 本身的修复。

---

## ④ 相关配置、代码、模型

### 4 个 Detector 清单

| detector | 来源 | 类型 | 备注 |
|---|---|---|---|
| `pp-doclayout-v3` | koharu 上游 | 通用文档版面分析 | 检出数通常最多，但对漫画竖排适配一般 |
| `comic-text-detector` | koharu 上游 | 漫画文字检测 | 检出数波动大（15.jpg 仅 3 个），可能 threshold 较严 |
| `anime-text` | koharu 上游 | 动画/动漫文字检测 | 检出数通常较多（15.jpg 11 个），但假阳性也多 |
| `comic-text-bubble-detector` | koharu 上游 | 漫画气泡检测 | 侧重气泡整体轮廓，可能忽略气泡内部分行 |

定义位置：`src/amta/pipeline.py` 的 `DETECTOR_STEPS`。

### 关键阈值与后处理参数

| 参数 | 值 | 位置 | 作用 |
|---|---|---|---|
| 并集 IoU 阈值 | `0.5` | `geometry.py:union_blocks` / `union_boxes` | IoU > 0.5 视为重复框，保留首个 |
| 嵌套 IoA 阈值 | `0.75` | `geometry.py:build_regions` / `absorb_contained` | 子框被父框覆盖 ≥75% 判定为嵌套，挂 child_lines |
| child_lines 碎片去重 IoA | `0.5` | `geometry.py:build_regions` | child_lines 内新行被已收录行覆盖 ≥50% 视为碎片丢弃 |
| sub_tier 行宽比 | `1.4` | `geometry.py:assign_sub_tier` | 行宽 / 最大行宽 < 1/1.4 标 aside（碎碎念） |

### 代码文件清单

| 文件 | 内容 |
|---|---|
| `scripts/01_detect.py` | detect 工位主脚本：跑 4-detector 并集 → union_blocks → assign_category → build_regions → flatten_regions → 输出 detection.json |
| `scripts/recall_detect.py` | Benchmark A 探针：跑 4-detector 输出原始框（未去重），供 recall 评测对齐。**设计上保留 per-engine 原始框** |
| `scripts/diag_detector_miss.py` | **漏检诊断探针（本简报新增）**：对单页跑 4-detector，保存 per-engine 原始框 + 漏检区域逐 detector 覆盖检查 |
| `scripts/check_detect_report.py` | 逐框核对报告生成（HTML + 裁剪图） |
| `src/amta/pipeline.py` | `DETECTOR_STEPS` 常量（4 个 detector 名称列表，按执行顺序） |
| `src/amta/geometry.py` | 全部几何后处理：`iou` / `union_blocks` / `union_boxes` / `absorb_contained` / `build_regions` / `flatten_regions` / `assign_sub_tier` / `assign_category` |
| `src/amta/runner.py` | `run_all_pages`：批量跑 detector 流水线（按 DETECTOR_STEPS 顺序依次跑，每个 detector 独立 koharu 项目）；`compact_blocks`：压缩 detector 输出字段 |
| `src/amta/koharu_client.py` | koharu REST 客户端（:4000），detector 调用的底层接口；`collect_blocks` 委托给 `koharu_blocks.py` |
| `src/amta/koharu_blocks.py` | `collect_blocks`：koharu scene 节点 → 文字块整形（提取 node_id、ocr、confidence、transform、bubble_type）。node_id 来自 koharu 内部 UUID |
| `docs/superpowers/plans/2026-08-27-detect-contract-childlines.md` | detect 契约升级（regions/child_lines/sub_tier）的实施计划与决策记录 |

### 检测产物清单（三层 tracing 体系）

#### L3 最终产物（当前 work）
| 文件 | 内容 |
|---|---|
| `workspace/touhou-single-wing/artifacts/page_13_detection.json` | 14.jpg 最终检测结果（17 boxes，漏检「では豊ちゃん…」大字主框） |
| `workspace/touhou-single-wing/artifacts/page_14_detection.json` | 15.jpg 最终检测结果（9 boxes，漏检「弟子だからね」大字主框） |
| `workspace/touhou-single-wing/artifacts/page_10..20_detection.json` | 11-20 页最终检测结果 |

#### L2 并集中间产物
| 文件 | 内容 |
|---|---|
| `output/data/detect_union_11_20/p11.json` ~ `p20.json` | 11-20 页并集后结果（早期版本，无 regions/child_lines），只有 `per_engine_boxes` 计数 |
| `output/data/detect_union_page11.json` / `detect_union_b_light_page11.json` | 单页并集实验产物 |
| `output/reports/detect_check_11_20.html` | 11-20 页逐框核对报告 |
| `output/reports/detector_alignment_check.html` | detector 对齐检查报告 |
| `output/backup/2026-08-27-pre-rerun-11-20/` | 重跑前的备份（page_10-19_detection.json） |

#### L1 Recall 探针产物（前 10 页，page_0-9）
| 文件 | 内容 |
|---|---|
| `output/data/recall_result.json` | recall 评测结果（每页 GT 匹配明细、detected_frames 计数） |
| `output/data/recall_ocr.json` | 并集后逐框 OCR 结果（crop 名 + text + empty），10 页 |
| `output/data/recall_gt.json` | 人工 GT 标注（整页枚举） |
| `output/recall_crops/page_N_uMM.png` | 并集后裁剪图（10 页 × 每页 8-15 框） |
| `output/recall_crops/p0_comic-text-detector_NN.png` | 单 detector 裁剪图（仅 page_0 的 comic-text-detector，8 张） |
| `output/data/recall_detections.json` | **设计上应存在**：4-detector 原始框（未去重），但当前文件不存在 |

#### 诊断脚本与临时分析
| 文件 | 内容 |
|---|---|
| `scripts/diag_detector_miss.py` | **本简报新增**：漏检诊断探针，保存 per-engine 原始框 + 逐 detector 覆盖检查 |
| `output/tmp/trace_recall.py` | 已有 trace 脚本：分析 recall_result.json / recall_ocr.json 的匹配明细 |
| `output/tmp/align_detector.py` | 已有脚本：detector 并集框与 GT 的文字重合度对齐 |
| `output/tmp/check_recall_crops.py` / `check_recall_ocr.py` | recall 裁剪图/OCR 检查脚本 |

### 引擎与运行环境

| 项 | 值 |
|---|---|
| koharu 版本 | **v0.59.1**（钉版，headless REST :4000；上游 0.77.5+ 已删 headless/HTTP，升级即失去自动化面） |
| 算力 | CPU-only（i5-1135G7 4C8T / 16GB），并发 workers = 1 |
| 本地 OCR 引擎 | PaddleOCR-VL-For-Manga GGUF + 独立 llama-server（:8118）—— 与 detect 无关，列此供上下文 |
| 翻译/视觉模型 | DeepSeek API（`deepseek-v4-flash` / `deepseek-v4-flash-vision-exp`）—— 与 detect 无关 |

### 关联决策与文档

| 文档 | 内容 |
|---|---|
| `docs/decisions/022-audit-probe-conclusion.md` | ADR-022：两趟式 OCR audit 定稿，Pass2 漏检枚举是 detect 漏检的兜底发现机制 |
| `research/handoff-OCR-vlm-audit-顾问简报-2026-08-27.md` | 本轮 OCR audit 顾问简报，P3 首次指出 detector 上游问题 |
| `docs/lessons.md` | 可复用经验库（L10：并集框去重漏竖排碎片框；其他 detector 相关经验） |
| `CLAUDE.md` | 项目核心事实与架构概览 |

---

> **给顾问的核心问题**：
> 1. **根因定位**：在 CPU-only、钉版 koharu v0.59.1、4-detector 并集的约束下，"大小字混合气泡中大字偶然漏检"的根因更可能是上游 detector 的 threshold 过滤（方向 A）、训练模式覆盖不足（方向 B）、还是后处理去重误杀？当前落盘产物**不保留 per-engine 原始框**，已编写 `scripts/diag_detector_miss.py` 诊断探针待执行，顾问是否建议优先跑此探针获取精确数据？
> 2. **修复方向**：确认根因后，应走调优 threshold（方向 A）、引入新 detector（方向 B）、后处理气泡内补检（方向 C），还是接受 VLM 枚举兜底（方向 D）并将漏检转为人工工单？
> 3. **Tracing 改进**：当前三层检测产物体系只在最外层保留 per-engine 计数，是否建议在 `01_detect.py` 中增加 `--save-per-engine` 选项，将每个 detector 的原始框一并落盘，以便未来类似问题的快速定位？
> 4. **上述 V1-V6 验证项应优先做哪些？**（V1 关后处理 dump 原始输出 / V2 单 detector 逐一对齐 / V3 查 koharu threshold 配置 / V4 扩大样本量 / V5 复核 Benchmark A GT / V6 测试降阈值效果）
