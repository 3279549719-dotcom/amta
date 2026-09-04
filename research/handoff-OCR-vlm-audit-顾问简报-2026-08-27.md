# OCR 校验中的「整页通用 VLM」与「baberu-OCR」问题 — 外部顾问简报

> 日期：2026-08-27
> 项目：AMTA（会话驱动漫画翻译自动化）
> 目的：给外部顾问一份自包含的背景说明，覆盖本轮 OCR 校验链路里"整页通用 VLM 转写"与"此前 baberu-OCR"的对比、问题与方案。无需了解仓库即可读。

---

## ① 想要做什么

### 背景：AMTA 一条漫画翻译流水线里，OCR 环节的角色

AMTA 把一页漫画自动翻译成中文。对每一页要依次做：

1. **detect**：检测页面上所有文字区域（对白框、拟声词、旁白等），框出坐标。
2. **OCR**：对每个框识别日文原文，得到 `canon`（每框一行文字，作为后续翻译的输入真值）。
3. **translate / inpaint / typeset**：翻译、擦字、排版（本简报不涉及）。

**OCR 这一步有两个引擎来源**，是本次讨论的核心：

- **baberu-OCR（ONNX）**：此前默认的 OCR 引擎，来自 koharu 上游，**快**（约 1s/图，比本地 For-Manga OCR 快约 28 倍），对白 CER 与本地引擎相当 → 作为 fast path 和当前 canon 的生产来源。
- **整页通用 VLM（`deepseek-v4-flash-vision-exp`）**：DeepSeek 通用视觉模型。项目里已用于"翻译语义评审"。本轮想把它引入 **OCR 校验/audit** 环节。

### 本轮要解决的问题：OCR 结果有没有错？

OCR 会犯三类错，翻译前必须尽量抓出来：

| 错误类 | 含义 | 例子 |
|---|---|---|
| **幻觉 hallucination** | 框里本来没字，OCR 却"编"出了字 | 空白背景编出"い、意味" |
| **误读 misread** | 框里有字但认错 | サグメ 读成 サグさ |
| **漏检 missed** | 页面有字但 detector 没框到，OCR 根本没机会认 | 框外小字、大拟声词 |

**想做的事**：做一个两趟式 **audit 工位（02.5）+ repair 工位（02.6）**，用 VLM 当"差异提示器"来发现这三类错，再用确定性机制（本地 For-Manga 重 OCR + 机械规则）二次确认后修复或进人工工单。

**另一个附带目标**：测试"整页通用 VLM 能不能批量转写/判空"——即能不能用一次全页 crop 批量调用，又快又准地替代或复核逐框 OCR。

---

## ② 遇到了什么问题

按严重性排序，本轮踩到的都是真实数据（pages 10–14，54 个 region）测出来的。

### P1｜推理模型 token 螺旋：旧单趟 audit 设计几乎不可用
- `deepseek-v4-flash-vision-exp` 是**推理模型**。复杂任务（17 条清单 + JSON 指令 + 整页图）会把全部 `max_tokens` 耗在 `reasoning_content`（思维链）上，实测 **6000/6000、12000/12000 全被吃光**，`finish_reason=length`，正式 `content` 恒空。
- 结果：一页 audit 要分块多调，**约 10 分钟/页**，41 页约 7 小时。
- 且 prompt 里写"不要推理"**无效**（机制是思考模式，不是指令）。

### P2｜通用 VLM 的整页转写并不准（用户人工复核实锤）
用户逐条人工复核 `probe_vision_report.html` 后确认，整页通用 VLM 转写有系统性误差。**这意味着"B 组转写质量 ≥ baberu"的乐观结论不成立**。实测 9 条失败 case：

| region | canon（baberu 产物，参考） | 整页 VLM 转写 | 错在哪 |
|---|---|---|---|
| page_12_u09 | キョコ | ギロッ | VLM 误读 |
| page_14_u07 | ひょこ（框外拟声词） | いまこ | VLM 误读 |
| page_13_u00 | じゃ、そういうことで、 | じゃあ、こっちに | 框内小字检索错（还"编造"了こっちに）|
| page_13_u11 | サグメ | サグさ | VLM 截断 |
| page_13_u09 | エーマン | こ、こ、こ、こ、こ | **detector 框没对准**（canon 和全页都错，非 VLM 转写错）|
| page_13_u13 | 1 | だ、だ、だ | 同上，detector 框错 |
| page_13_u16 | ハ意様（框外小字） | い、意味 | VLM 看错 + 编造 |
| page_14_u00 | えっ！？八意様のこど… | えっ！？ | **VLM 漏检大部分**（只转出开头，严重）|
| page_14_u05 | もう一人だとーーー！！ | もう一人をと…… | 标点（ー/！）与假名（た→を）都错 |

**结论：全页通用 VLM 也有自己的不准之处**——误读、编造、截断长句、丢标点、漏检整句。漫画竖排小字尤其弱。

### P3｜VLM 救不了上游 detector 的错
page_13_u09 / page_13_u13 是更根本的问题：**detector 的框本身就没对准**（框落错位置），于是 canon（逐框 OCR）和整页 VLM 都看错。**这是上游检测问题，任何转写/校验模型都救不了**，只能靠"漏检枚举 + 重新检测框"处理。

### P4｜JSON 输出有官方承认的空 content 风险
官方文档明确：JSON Output 下 API **有概率返回空 content**。若任务强依赖 JSON 结构，解析会崩。

### P5｜整页降采样导致"真小字被误判成幻觉"
整页图 VLM 对窄竖排小字不可读，会**把真实文字判成幻觉**（高置信度也是错的），因此"VLM 说空"不能直接当删除依据。

---

## ③ 采取的具体方案措施

### 第一步：DeepSeek 官方视觉能力调研（先吃透 API 事实）
抓官方文档 + GitHub + 社区，锁定关键事实（详见第④节配置表）：
- 唯一视觉模型 id：`deepseek-v4-flash-vision-exp`；其他模型传图返回 400。
- **关闭思考的官方参数**是 `thinking: {"type": "disabled"}`（OpenAI 格式），不是 prompt 指令。
- `detail:"low"` 推理前缩到 512×512，省 token 且对"判空"任务足够。
- 单请求上限 600 图、请求体 48 MiB、每图 ≤384 token、上下文 1M —— **限制不在 API，在模型质量本身**。
- 判空/转写类任务**改输出纯文本行**（每图一行：文字/空），绕开 JSON 空 content 风险。

### 第二步：微探针 A/B/C（实测三组参数，定位最优配置）
同一批 crops，对比三组（pages 10–14）：

| 组 | batch | thinking | detail | max_tokens | 实测 |
|---|---|---|---|---|---|
| **A**（旧基线）| 3 图/次 | 默认思考 | 默认 | 2000 | 33–65s/页，4/5 页螺旋（finish=length）|
| **B**（整页全量）| 整页一次 | **disabled** | **low** | 8000 | **2.0–2.7s/页，1 次调用，finish 全 stop，reasoning_len=0**，转写行全覆盖，平均重合度 0.56–0.83 |
| C（折中）| 6 图/次 | disabled | low | 4000 | 2.7–4.0s，全 stop |

**B 组把单页从 33–65s 压到 2–3s，螺旋根除**（约 12–24× 提速）。但注意：**B 组"快且不螺旋"≠"转写准"**——P2 的 9 条错误正是在 B 组全量转写上发现的。提速解决的是工程可用性，不是质量。

### 第三步：两趟式 audit 设计（ADR-022 定稿）
| 趟 | 针对 | 做法 |
|---|---|---|
| **Pass1 存在性确认** | 幻觉 / 误读 | crop 小图多图批量 → VLM 转写/判空。机械判定：空→幻觉候选；转写与 canon 有差异→误读候选（VLM 顺带给修正文本）。crop 全分辨率 → 窄竖排小字可读，根除整页降采样的假阳性。**批量上限 3 图**（6 图在密页 50% 螺旋）。|
| **Pass2 漏检枚举** | 漏检 | 整页图 + **无清单**枚举 prompt（只列文字+方位）→ 与 canon 机械 diff → 候选进工单 + 方位框 re-OCR 确认。无清单 → 无对比推理 → 不触发螺旋。|

**安全阀（关键，防止 VLM 误判造成误删/误改）：**
1. 幻觉**不自动删**：必须 "For-Manga 重 OCR 为空 **且** 墨量 <1%" 双条件才允许，否则进工单。
2. 误读：重 OCR 替换；但 **edit distance ≤2 的差异（助词级）降级为低优先级提示**，不触发重 OCR。
3. 漏检：方位框 re-OCR → 附 `reocr_text` 进工单，人工确认，不自动合入。
4. region_id 匹配做**后缀归一**（VLM 常返回 `u00` 短形式）。

### 第四步：探针准确率验证 → 决定 repair 闭环力度
注入 3 类已知错误对照 VLM 命中率：**严格命中率 12/15 = 80%**（达标完整闭环阈值）→ 按带安全阀的完整 repair 闭环实施。计时：密页（17 crops）Pass1 ~40–60s + Pass2 ~25s ≈ **1.5–2.5h/41 页**（原单趟设计 ~7h）。

### 第五步（用户复核后的关键修正）：VLM 只当"差异提示器"，不当真值源
用户人工复核 HTML 暴露 P2 后，修正结论：
- **VLM 不能当独立真值源**——它自己会误读/编造/漏检/丢标点（9 条里 7 条 VLM 错）。
- VLM 的角色收敛为 **"canon 与图疑似不符"的差异信号**，判定一律走确定性机制（本地 For-Manga 重 OCR + 机械规则）。
- 连"VLM 说漏了"都不能盲信（page_14_u00 只转出"えっ！？"）→ 漏检兜底必须靠 Pass2 整页枚举 + 机械 diff，不能依赖单次转写完整性。
- ②类 case（detector 框错）是上游检测问题，VLM 救不了，需重新检测框。

---

## ④ 相关配置、代码、模型

### 模型与连接
| 项 | 值 |
|---|---|
| 视觉模型 id | `deepseek-v4-flash-vision-exp` |
| 端点 | `https://api.deepseek.com`（OpenAI 兼容 `/chat/completions` 通道不变）|
| 认证 | `.env`：`CHAT_BASE_URL` / `CHAT_API_KEY`（翻译与视觉共用）|
| 其他模型传图 | 返回 400 "This model does not support image" |

### 官方能力上限（决定 batch 策略）
| 项 | 官方值 |
|---|---|
| 单请求图片上限 | 600 张 |
| 单图尺寸上限 | 单边最长 8192px（≥15 图时 4096px）|
| 请求体 / 图片总量 | 请求体 48 MiB；不含 file_id ≤64 MiB |
| 每图 token 上限 | ≤384 token（图自动缩至约 800×800 当量）|
| 上下文 / 输出 | 1M / 384K |
| 传图方式 | base64 data URI（本项目采用）/ http(s) URL / Files API |
| 图片位置 | 仅 `user` 消息；`system`/`assistant` 带图 400 |

### 关键参数与写法
| 参数 | 写法 | 作用 |
|---|---|---|
| 关闭思考 | `payload["thinking"] = {"type": "disabled"}` | 杜绝推理螺旋；thinking 模式下 temperature 等**被忽略** |
| 低清 | `img["image_url"]["detail"] = "low"` | 推理前缩 512×512，省 token，判空足够 |
| 输出规避 JSON 空 content | 转写用纯文本行（每图一行 `图N: 文字/空`），**不用 JSON** | 官方承认 JSON 有概率空 content |
| 空 content 兜底 | 自动重试（已有 `retries=2`）| 防 finish=length / 空响应 |
| batch 上限 | **3 图/次**（密页 6 图 50% 螺旋）| 质量优先 |

### 代码 / 产物清单（都在 feat/audit-v2 worktree 的 workspace 下，一次性未入库）
| 文件 | 内容 |
|---|---|
| `probe_vision_batch.py` | 微探针 A/B/C：三组参数批量转写、测 finish/duration/reasoning_len/重合度。`--pages 10-14 --out ...` |
| `probe_vision_batch_result.json` | B 组整页 2–2.7s、全 stop、reasoning_len=0；A 组螺旋 |
| `gen_probe_html.py` / `probe_vision_report.html` | 5 页 54 region 的 canon vs B 组 VLM 转写 + 重合度颜色对照（**用户人工复核的就是它**）|
| `recheck_cases.py` | 一次性诊断：dump 用户指出的 9 条 region 的 canon / VLM / overlap |
| `raw/`、`crops_report/` | 5 张 jpg + 54 张 crop png 证据图 |
| `touhou-single-wing/artifacts/` | canon JSON（`page_10..14_canon.json`）+ crops |
| 正式决策 | `docs/decisions/022-audit-probe-conclusion.md`（ADR-022，两趟式 audit 定稿 + 安全阀）|
| 调研依据 | `research/05-DeepSeek官方视觉能力调研-详报.md` |
| 计划出处 | `docs/superpowers/plans/2026-08-27-front3-stages-v2.md`（Task 0 探针）|

### 关键提示
- 微探针脚本/HTML 在 worktree workspace，**gitignore 未入库**，属一次性证据，未进正式代码库；正式落地以 ADR-022 参数为准。
- 坑已入 `docs/lessons.md`：L32（推理模型 token 螺旋 + 分块对策）、L23（空 content 重试）、L22（模型真实 id）。
- 用户复核后最重要的工程修正：**VLM 是差异提示器，不是真值源**；最终判定走本地 For-Manga 重 OCR + 机械规则。
