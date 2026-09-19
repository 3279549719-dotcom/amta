# Handoff：下一个 cycle 要解决"误检"方向

> 交接给下个对话。上一个 cycle（2026-09-17）解决了长文本方向，结论见 `docs/lessons.md` L49。本文件记录**没解决、留到下轮**的另一个方向：不该翻的东西被翻了。

## 本次 cycle 一句话结论

长文本（后记/设定解说大段无框文字）纯本地无解，hayai 训练分布不覆盖，已停在 `experiment/ocr-longtext-maxtokens` 分支，将来 GUI 阶段按需接 VLM。**这轮不碰。**

---

## 下一个 cycle 要做：误检（false positive）

和长文本是**相反方向**的病：

| 方向 | 症状 | confidence | 根因层 |
|---|---|---|---|
| 长文本（已结案） | hayai 读不出，框被删，成品空白 | avg_conf 0.27 | OCR 能力边界 |
| **误检（下轮）** | hayai 读得很准，但读的是不该翻的东西 | avg_conf 0.97 | detect 框错了 / LLM 不该翻 |

**关键区别：误检靠 confidence 救不了。** "蓬莱" avg_conf 0.97——hayai 读对了，问题是 detect 根本不该把它框进来。这不是 OCR 没把握，是 detect 多管闲事。

### 三个已定位案例（精确到 region）

#### 案例 1：背景大字被当对话
- **位置**：单翼停留之地 `touhou-single-wing` page_12 region **r01**
- **bbox**：[290, 2484, 511, 2970]（竖长框 221×486）
- **OCR 文本**：`蓬莱`（avg_conf 0.9749，hayai 读得很准）
- **问题**：这是画面里竖排的"蓬莱"两个大字——门牌/招牌/背景装饰字，不是对话气泡。detect（RT-DETR-v2）把它框进来了，hayai 照读，LLM 照翻，inpaint 照擦。成品图上这两个字被涂掉换成中文"蓬莱"——但它本来就是画面的一部分，不该动。
- **canon**：`workspace/touhou-single-wing/artifacts/canon/page_12.json`

#### 案例 2：长省略号被走全流程
- **位置**：月天新地 `touhou-getten-shinchi` page_10 region **r02**
- **OCR 文本**：`................................................`（48 个英文句点）
- **translation**：`................................................`（LLM 原样吐回，没翻但走了流程）
- **问题**：一大段省略号表示沉默/停顿，不是要说的话。detect 框了它，OCR 读成 48 个点，LLM 不知道该干嘛就原样吐回，inpaint 擦了原文，typeset 画了 48 个点——读者看到一排点被换了位置。
- **canon**：`workspace/touhou-getten-shinchi/artifacts/canon/page_10.json`
- **translation**：`workspace/touhou-getten-shinchi/artifacts/translation/page_10.json`

#### 案例 3：短省略号被走全流程
- **位置**：月天新地 `touhou-getten-shinchi` page_5 region **r13**
- **OCR 文本**：`............`（12 个点）
- **translation**：`……`
- **问题**：同上，短省略号。LLM 至少聪明地转成了中文省略号，但这个框本来就不该进翻译流程。
- **canon**：`workspace/touhou-getten-shinchi/artifacts/canon/page_5.json`
- **translation**：`workspace/touhou-getten-shinchi/artifacts/translation/page_5.json`

---

## 下轮思考方向（不要直接上规则，先想清楚）

用户的方法论约束（ADR-034 + vibe coder 原则）：
- **不要**"超过 N 字就跳过""纯标点就不翻"这种硬编码阈值——和长文本切块一样是 handcrafted 规则，越叠越脆
- **不要**为 1-2 个假框预设规则
- 用第一性原理想：detect 为什么把"蓬莱"框进来？它和对话框在视觉上有什么本质区别？省略号为什么被框进来？

初步思路（待下轮验证，不是结论）：
1. **detect 层**：RT-DETR-v2 训练时见过"蓬莱"这种背景字吗？它是不是把所有"有字的地方"都当文字框了，不管是不是对话气泡？
2. **LLM 层**：能不能让 translate 阶段的 LLM 判断"这段要不要翻"——"蓬莱"是专有名词/地名，不该翻；省略号是标点，不该翻。但用户拒绝 VLM，LLM 只看文本不看图，它怎么知道"蓬莱"是门牌还是台词？
3. **保险丝方向**（和长文本那个保险丝呼应）：误检的框被 inpaint 擦了原文才是最大损失。能不能让 inpaint/typeset 在"文本纯标点/极短"时跳过擦除？——但这又是阈值。

**下轮第一件事**：先看图。打开单翼 p12 final 图和月天 p10 final 图，亲眼看看"蓬莱"和那排省略号在画面里长什么样、detect 框在哪，再决定从哪层治。别上来就改代码。

---

## 当前 git 状态

- 分支：`experiment/ocr-longtext-maxtokens`（已 commit `438b711`，L49 落盘）
- main：`b6da05e`
- 下轮从 main 拉新分支做误检方向，不要在实验分支上叠
