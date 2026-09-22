# 交接：VLM 直读横排大片文字页（2026-09-21）

## 这轮在干什么

验证一条新路径：对横排大片文字页（封面、后记、版权页、人物介绍页等），**跳过 hayai OCR，直接用 VLM 按 detect 框转写日文**，然后走正常的 translate → inpaint → typeset。

背景：hayai 对横排小字读崩，且读太烂的框会被 OCR 置信度阈值整段删掉（字根本进不了 canon，后续 VLM 校对也救不回）。上一轮（见 `amta-vlm-handoff.md`）已确认 qwen3.5-omni-plus（走阿里 dashscope）可用，但只做了"OCR 之后校对"。这轮把 VLM 前移到直接替代 OCR。

## 结论

**VLM 直读对横排大片文字页有效。** 5 页测试全部翻译成功：

| 作品 | 页码 | 页面类型 | 结果 |
|---|---|---|---|
| 月天新地 | 1 | 封面 + 横排后记 | 翻译 ✅，后续 ❌（见下） |
| 月天新地 | 39 | 横排后记（此前被 OCR 阈值删掉的那页） | 全链路 ✅ |
| 月天新地 | 55 | 活动告知横排页 | 全链路 ✅ |
| 单翼停留之地 | 5 | 人物介绍横排页 | 全链路 ✅ |
| 单翼停留之地 | 40 | 版权页 + 横排后记 | 全链路 ✅ |

特别值得记一笔：39 页是上一轮交接文档里标记的"层 B 病"——detect 检到但 hayai 读太烂被置信度阈值整段删除，VLM 校对看不到。走 VLM 直读这条路后，这页完整读回来了。

## 关键改动（已改代码）

### 翻译输入：裸换行拼接 → JSON 数组

**文件**：`src/amta/translation/translate.py`，函数 `translate_plain._build_content`

**改了什么**：待翻译条目从 `"\n".join(blocks)` 改成 `json.dumps(blocks, ensure_ascii=False)`。

**为什么**：VLM 转写出来的文本块内部自带换行（一段后记有好几行），而翻译 prompt 用裸 `\n` 拼接各块——模型分不清哪个换行是"块内换行"哪个是"块间分隔"，会把一段长文拆成多条译文，导致输出数组长度和输入对不上，整批作废。改成 JSON 数组后，块内换行在字符串里是转义的 `\n`，边界由数据结构定死，模型没东西可猜。

**顺带解决的问题**：单翼停留之地第 5 页那段长说明（讲"污秽/旧世代/新世代"），改之前模型稳定把它拆成 3 条译文，重试 6 次全挂；改之后单次就过。**不需要加任何 prompt 约束，不需要重试，改输入格式就够了。**

**这个改动是通用的**，不依赖 VLM——hayai 时代每块单行所以没暴露，但契约漏洞一直存在。建议进主线。

## 实验脚本（未接进正式管线）

- `scripts/probes/probe_vlm_direct_ocr.py`：主脚本。读 detection artifact → 把整页图+框坐标喂给 qwen3.5-omni-plus → 按框转写 → 组装 canon（schema 2.1）落盘。块内换行已压平为空格。
  - 跑法：`$env:PYTHONPATH="src;."; uv run python scripts/probes/probe_vlm_direct_ocr.py --work-id <id> --src-dir <dir> --pages 1,39,55`
- `scripts/probes/_probe_translate_debug.py` / `_probe_translate_retry.py` / `_probe_translate_split.py`：调试用的临时脚本，可删。
- 旧 hayai canon 已备份到 `workspace/<work-id>/artifacts/_hayai_canon_bak/`。

## 未解决的问题（交给下一个 AI）

### inpaint 和 typeset 对纯横排页处理不了

**现象**：月天新地第 1 页（封面 + 整页横排后记）走完全链路后成品翻车：
1. 日文原文根本没擦掉（inpaint 没生效或擦不干净）
2. 中文译文被当成竖排对话气泡排了——散落在页面两侧，竖排小字，和原文重叠，字号位置全错

**对比**：单翼停留之地第 5 页（人物介绍页，文字在明确的框里）全链路成功，成品正常。区别在于第 5 页虽然文字横排，但结构上还是"一个个框"，现有管线误打误撞能处理；第 1 页是纯横排整页文字，没有气泡框概念，就露馅了。

**需要下一个 AI 解决的方向**：
1. **inpaint**：横排大段文字/封面标题的擦除策略和对话气泡不一样。气泡是小区域 mask，横排页可能需要整行/整区域 mask。查 `src/amta/inpaint/inpaint_station.py` 和 `inpaint_strategy.py`，看 mask 怎么生成的，为什么第 1 页没擦掉。
2. **typeset**：得知道这页/这个框是横排还是竖排，横排就该横排排回去，不能默认竖排对话气泡。查 `src/amta/typeset/typeset_engine.py` 和 `typeset_station.py`，看方向判断逻辑在哪。detect 的 `det_label` 字段可能已经区分了文字类型，可以利用。
3. **可能需要一个"横排页模式"**：detect 出来后判断这页是不是横排为主，如果是，inpaint 和 typeset 走不同路径。

## 分支与状态

- 分支：`exp/vlm-direct-ocr`（从 main 切出，未 commit，未 merge）
- 已改文件：`src/amta/translation/translate.py`（数组契约，建议进主线）
- 未跟踪文件：上述探针脚本、`docs/decisions/2026-09-21-pipeline-shape-and-roadmap.md`（上一轮遗留）
- 工作区产物：`workspace/touhou-getten-shinchi/` 和 `workspace/touhou-single-wing/` 里 5 页的 canon/translation/inpaint/typeset 都已生成
- 报告 HTML：`output/vlm-direct-getten.html`、`output/vlm-direct-single-wing.html`（已上传飞书公开链接，见对话记录）

## 配置

- `.env` 里已有：`VISION_MODEL=qwen3.5-omni-plus`、`DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`、`DASHSCOPE_KEY=...`
- 翻译用 DeepSeek：`CHAT_BASE_URL=https://api.deepseek.com`、`CHAT_MODEL=deepseek-v4-flash`
- VLM 调用走 `amta.backends.chat_client.chat()`，和 `vlm_filter.py` 同一个通道
