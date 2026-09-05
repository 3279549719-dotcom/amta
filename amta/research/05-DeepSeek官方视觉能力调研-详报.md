# DeepSeek 官方视觉（多模态）能力调研 — 详报

> 调研日期：2026-08-27
> 调研方式：官方文档逐页抓取（api-docs.deepseek.com 中文版 5 页）+ GitHub 仓库/论文原文核验 + 社区检索
> 适用项目：AMTA（漫画翻译自动化）— 已在用 `deepseek-v4-pro`（翻译）+ `deepseek-v4-flash-vision-exp`（视觉评审/OCR 审核）

---

## 1. 官方视觉能力事实表

> 除标注外，均引自 [图像理解（中文）](https://api-docs.deepseek.com/zh-cn/guides/vision)、[模型 & 价格](https://api-docs.deepseek.com/zh-cn/quick_start/pricing)、[思考模式](https://api-docs.deepseek.com/zh-cn/guides/thinking_mode)、[JSON Output](https://api-docs.deepseek.com/zh-cn/guides/json_mode)、[Token 用量计算](https://api-docs.deepseek.com/zh-cn/quick_start/token_usage)。英文站点存在对应页面（[Vision Guide](https://api-docs.deepseek.com/guides/vision)、[Pricing](https://api-docs.deepseek.com/quick_start/pricing)），本次以中文版为准，未逐字核验英文版差异。

| 项目 | 官方结论 | 出处 |
|---|---|---|
| 视觉模型 id（精确拼写） | **`deepseek-v4-flash-vision-exp`**（版本 `DeepSeek-V4-Flash-Vision-Exp`）。API 全部模型仅 3 个：`deepseek-v4-flash` / `deepseek-v4-pro` / `deepseek-v4-flash-vision-exp` | 价格页 |
| 其他模型能否传图 | 不能。**仅视觉模型接受图片，其他模型返回 `400` "This model does not support image"** | vision 指南"使用限制" |
| deepseek-vl / vl2 走 API？ | **不走**。VL 系列是开源本地权重（见第 2 节），与 API 视觉模型是两回事；`deepseek-chat`/`deepseek-reasoner` 旧 id 亦无视觉 | 价格页（仅 3 模型） |
| 图片格式 | JPEG、PNG、GIF、WebP（按文件实际内容判断，非 MIME/文件名） | vision 指南 |
| 传图方式 | ① base64 data URI 内联（计 48 MiB 请求体）② 外部 http(s) URL（≤8192 字符、单图 ≤32 MiB、60s 内下载）③ Files API `file_id`（单图 ≤64 MiB） | vision 指南 |
| 单请求图片数上限 | **600 张** | vision 指南"限制"表 |
| 单图尺寸/大小上限 | 单边最长 **8192px**；≥15 张图时降为单边 4096px；base64/URL 单图 ≤32 MiB，`file_id` ≤64 MiB | vision 指南"限制"表 |
| 请求体/图片总量 | 请求体 48 MiB；不含 `file_id` 图片总 ≤64 MiB、含 `file_id` 最高 200 MiB | vision 指南"限制"表 |
| detail 字段 | `low`＝推理前缩放 512×512（更快省 token）；`high`/`original`＝保留原图；`auto`＝当前等价 original | vision 指南 |
| 图片 token 计费 | 每图自动缩放：小图（<约 384×384）放大、大图等比缩至约 **800×800 当量**；**每图 token 上限 384**，多图各自独立计 | vision 指南"Token 用量" |
| 单价 | 与 `deepseek-v4-flash` 同价：输入（缓存未命中）1.5 元/百万（空闲）/3.0（高峰），输出 4.5/9.0 元/百万；并发限制 2500 | 价格页 |
| 上下文/输出长度 | 上下文 **1M**，输出最大 **384K**（三模型共用行） | 价格页 |
| 思考模式 | 默认开启，effort 默认 `high`；可关闭/调档（见下）；**思考模式下 temperature/top_p/presence_penalty/frequency_penalty 不生效（不报错但忽略）** | 思考模式指南"输入输出参数" |
| 关闭思考的官方参数 | OpenAI 格式 `extra_body={"thinking":{"type":"disabled"}}`；Anthropic 格式 `reasoning: {"effort": "none"}`；effort 映射：low→low，medium/high/xhigh→high，max→max | 思考模式指南 |
| 空 content / JSON | **官方明确承认：JSON Output 下"API 有概率会返回空的 content"，官方建议改 prompt 缓解 + 合理设置 max_tokens 防截断** | JSON Output 指南"注意事项"第 4 条 |
| reasoning_content | 思维链经 `reasoning_content` 字段返回（与 `content` 同级）；无 tools 的多轮中后续拼接会被忽略；**带 tools 的请求后续轮必须完整回传**，否则 400 | 思考模式指南 |
| 图片位置限制 | 图片仅可出现在 `user` 消息；`system`/`assistant` 带图返回 400；用户文本含保留图片占位 token 拒绝（400） | vision 指南"使用限制" |
| FIM 补全 | vision-exp **不支持**（flash/pro 仅非思考模式支持） | 价格页 |
| 图片 Token 精确计算 | 官方提供在线"图片 Token 计算器"（token_usage 页），离线 tokenizer 压缩包亦可 | token_usage 页 |

**未找到官方说明**：① vision-exp 是否支持关闭思考模式的具体声明（价格页将"支持非思考与思考模式"列为三模型共用行，但示例代码均用 `deepseek-v4-pro`，未单独验证 vision-exp 关闭思考的行为）；② 官方对"推理螺旋/密页多图质量下降"的任何建议；③ 官方对图片预处理的建议（缩放/JPEG 质量无官方要求——官方在模型入口自动缩放，见上表）。

---

## 2. GitHub / 社区发现

- **[deepseek-ai/DeepSeek-VL2](https://github.com/deepseek-ai/DeepSeek-VL2)**（[论文 arxiv 2412.10302](https://arxiv.org/abs/2412.10302)）：MoE 视觉语言模型，三档 tiny/small/base（激活参数 1.0/2.8/4.5B，总量 3.37/16.1/27.5B），主打 OCR、文档/表格/图表理解、visual grounding、多图输入；序列长度 4096；README 明示 **vl2-small 需约 80GB GPU**（增量预填充可降至 40GB）→ 本项目 CPU-only 本地部署不可行；代码 MIT、模型许可允许商用。
- **[DeepSeek-VL v1](https://arxiv.org/abs/2403.05525)**：技术报告含"文档级 OCR 数据"专项；VL2 论文 SFT 数据含 PubTabNet/FinTabNet/Docmatix 等文档数据及 anime 等文化数据（原文 "anime, memes, cuisine and art"）。**全文检索 0 处 "manga/comic/vertical"** —— 未找到官方声明训练数据包含漫画/竖排文字（OCR/文档是官方主打，但漫画竖排是未见明确覆盖的领域，需实测）。
- 上线时间线：[cnblogs/JavaPub（2026-08-21）](https://www.cnblogs.com/JavaPub/p/22623657) 报道 `deepseek-v4-flash-vision-exp` 为实验性模型、单图最高约 384 token，与官方文档一致。
- 传图硬性约束的社区实证：[vercel/ai issue #9179](https://github.com/vercel/ai/issues/9179) 与 [deepseek-ai/DeepSeek-V3 issue #337](https://github.com/deepseek-ai/DeepSeek-V3/issues/337) 均展示：**把 `image_url` 块发给不接收图片的模型/旧端点 → 400 "unknown variant `image_url`" / 反序列化失败**，即 image_url 必须搭配视觉模型 id（本项目做法正确）。
- 结构化输出讨论：[linux.do《视觉模型怎么稳定输出特定结构》](https://linux.do/t/topic/889268/8)（403 需登录，未能核验正文，仅确认该议题存在）；[cocoloop《DeepSeekV4 视觉报告灰度体验》](https://www.cocoloop.cn/t/topic/5149/8)（JS 渲染未能全文抓取）。—— 这两个帖子的实际内容**未能核实**，不引用其结论。
- 第三方 API 指南（[aireiter](https://aireiter.com/es/blog/deepseek-v4-flash-vision-exp-api-guide)）：确认模型 id、三种传图方式、`detail:"low"`→512×512，建议实验性模型先小规模试点再上生产（与官方 "exp" 后缀一致）。
- 漫画/OCR 应用案例：未检索到把 DeepSeek 视觉用于漫画审核的公开案例；一般性 OCR 教程（如 [DataCamp DeepSeek OCR](https://www.datacamp.com/ko/tutorial/deepseek-ocr-hands-on-guide)）存在但非漫画场景。**结论：漫画场景无先例，属自研路线。**

---

## 3. 与现有用法的差异对比

| 现有用法 | 官方/社区事实 | 判定 |
|---|---|---|
| data URI 内联传图 | 官方推荐本地图方式，48 MiB 请求体内合法 | ✅ 正确 |
| vision-exp 分块 ≤6 条、max_tokens 8000 | 官方无分块建议（社区经验）；输出上限 384K，8000 合理 | ✅ 合理 |
| "不要推理"指令抑制推理 | **无效是必然**：官方关闭思考的机制是 `extra_body={"thinking":{"type":"disabled"}}`（或 Anthropic `effort:none`），不是 prompt 指令 | ❌ 需修正 |
| 空 content（finish_reason=length） | 官方承认 JSON 输出下空 content 是已知问题，且思考模式默认开 + effort=high 会把输出 token 耗在 `reasoning_content` | ⚠️ 关闭思考 + 调 prompt 可缓解 |
| 传 temperature 想抑制发散 | 思考模式下 temperature 等参数**被忽略**（官方原文） | ❌ 无效，应改用 thinking/effort |
| 6 图/次密页螺旋、3 图/次更稳 | 官方上限 600 图/请求，但 ≥15 图时单边限 4096px；螺旋无官方解法，分块是社区通用姿势 | ✅ 维持 3 图/次 |
| crop 图未经 detail 参数 | 官方 `detail:"low"` 先缩 512×512，省 token 且对判空任务足够 | ➕ 可优化 |

---

## 4. 可执行建议（模型 id 精确拼写 + 参数）

统一模型 id：**`deepseek-v4-flash-vision-exp`**，base_url `https://api.deepseek.com`（OpenAI 兼容 chat/completions 通道不变）。

- **a) crop 批量存在性审核（转写/判空）**：`deepseek-v4-flash-vision-exp` + `image_url.detail="low"`（判空只需粗粒度）+ `extra_body={"thinking":{"type":"disabled"}}`（判别任务无需推理，直接省 token、杜绝 reasoning_content 挤占输出）+ `max_tokens≈2000` + 每请求 3–6 图。**输出用"每图一行：空/文本"的纯文本行而非 JSON**（避开官方已承认的空 content 风险）。
- **b) 整页漏检枚举**：`deepseek-v4-flash-vision-exp` + 每请求 **1 页**（密页尤其如此，维持现状单页）+ 清单 ≤6 条（维持现状）+ `max_tokens=8000`。若保留思考，把 effort 从默认 high 降为 `reasoning_effort="low"`；若实测关闭思考后漏检率不升，则直接 `thinking:disabled`。JSON 输出仅在 prompt 给足样例时使用，并加"解析失败重试 1 次 + 降级文本行"兜底。
- **c) 逐 region 四维评分**：单图/请求 + 评分维度压成一行 CSV 或 4 个字段的 JSON；同上优先 `thinking:disabled` + 足够 max_tokens（评分表长，给 4000–8000）；如需 JSON，接受官方"有概率空 content"，实现侧做空 content 重试。
- **多图批量与螺旋**：官方上限 600 图/请求、总量 ≤64 MiB（无 file_id）——**大批量完全合法，无需因"官方不支持"而分块**；分块纯粹是质量/螺旋考虑，密页维持 3 图/次即可。请求体 >48 MiB 或复用图时改用 Files API（`file_id`，单图 64 MiB、总量 200 MiB）。
- **计费预期**：每图 ≤384 token（>800×800 的图不更贵），按 flash 价（输入 1.5 元/M 空闲）计 → crop 批量判空成本极低；预处理上官方会在入口自动缩放，**无需自行缩到很小**，JPEG 质量保持 ≥85 保证竖排小字可读（社区通用实践，非官方要求）。
- **立即实测项**（官方文档未明确、但值得验证）：① vision-exp 是否接受 `thinking:disabled`（大概率接受，因价格表将思考模式支持列为三模型共用）；② 关闭思考后 JSON 输出与漏检率变化；③ `detail:"low"` 对 crop 判空精度的影响。

**一句话结论**：现有用法（data URI 内联 + vision-exp + 分块 + 8000 tokens）与官方能力基本吻合，最大修正点是**用 `thinking:disabled` 取代无效的"不要推理"指令**、**判空/评分任务放弃 JSON 走纯文本行**、**crop 加 `detail:"low"`**；官方上限（600 图/请求、48 MiB 请求体、384 token/图）远高于现状，限制不在 API 而在模型质量本身。
