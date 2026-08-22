# Lessons（可复用经验库 = 坑的唯一归属）

> 回答："我们从问题中学到了什么？"
> **本文件是「坑/经验」的唯一事实来源**。CLAUDE.md 只保留最精简的关键规则与指针，**不重复贴坑**。
> 不是流水账。每条 = Problem / Root cause / Durable lesson / Prevention / Regression。
> 只有当一条经验**稳定可复用**时才写进来；一次性实现细节不写。
> 晋升路径：Lesson（本文件）→ 稳定 Rule（CLAUDE.md）→ Invariant → 测试/hook。被自动化覆盖的条目标注 `[已自动化]`。

---

## L1 — describe_image 整页坐标不可靠

- **Problem**：Benchmark A 用 describe_image 看整页大图返回的 bbox 坐标是错的（裁剪验证为空白/位置漂移），无法做像素级 IoU 对齐。
- **Root cause**：VLM 对整页大图的空间定位不稳定，坐标不是其可靠输出。
- **Durable lesson**：任何需要像素级对齐的判定，VLM 只适合"识别内容/判类别"，不适合"报坐标"。
- **Prevention**：recall 改用**内容级匹配**（GT 内容清单 vs detector 并集框识别内容，字符重合度≥0.6 判定检出）；需要位置时用确定性 detector 的 bbox，不用 VLM 坐标。
- **Regression**：内容级匹配逻辑已在 `src/recall_score.py`；补一个纯函数单测（tests/test_recall_score.py）锁定重合度判定阈值。

## L2 — 假数据落盘（最致命）

- **Problem**：skill 测试时 subagent 曾把虚构的 "PaddleOCR-VL CER 0.11" 当真结果落盘并推送，需回滚纠正。
- **Root cause**：落盘前未校验"数据是否本会话实测、有无证据文件"；把规划/假设当结论。
- **Durable lesson**：任何要写进 progress.md / CLAUDE.md / benchmark 报告的数字，必须有可查的证据文件（output/*.json 或脚本输出）；拿不出证据只写"待验证/规划"。
- **Prevention**：cycle-close（/finish）第 2 步强制"数据真实性校验"；`npm run audit` 复查 progress.md 中的数字是否都有对应文件。
- **Regression**：`tests/test_output.py` 校验 output 下每个被入库的 benchmark JSON 都能解析且含必要字段。

## L3 — wait_operation 卡死：completed_with_errors 未被识别

- **Problem**：pipeline 已终态（completed_with_errors）但 wait_operation 一直轮询到超时。
- **Root cause**：终态集合漏了 `completed_with_errors`。
- **Durable lesson**：轮询终态必须覆盖引擎返回的全部终态集合（completed/failed/cancelled/completed_with_errors）。
- **Prevention**：wait_operation 终态集合显式枚举；后续改引擎/状态机时先查该集合。
- **Regression**：`tests/test_client_helpers.py` 校验 `TERMINAL_STATUSES` 常量包含全部已知终态。

## L4 — workers>1 在 CPU/集显下崩溃

- **Problem**：并发流水线（workers>1）在 i5-1135G7 / Iris Xe 上 Vulkan 断连。
- **Root cause**：算力受限，集显并发不可靠。
- **Durable lesson**：本项目并发 workers 必须 =1；这是硬约束不是可调参数。
- **Prevention**：任何并发相关代码/参数必须默认 workers=1。
- **Regression**：暂无自动化（运行时约束）；规则见本条。[已自动化：否]

## L5 — .ps1 含中文路径必须 UTF-8 带 BOM

- **Problem**：PS5.1 把无 BOM 的 UTF-8 中文 .ps1 按 GBK 解析报错。
- **Root cause**：Windows PowerShell 5.1 默认编码推断。
- **Durable lesson**：含中文的 .ps1 必须 UTF-8 **带 BOM**。
- **Prevention**：新建/编辑 .ps1 时用带 BOM 的 UTF-8 保存。
- **Regression**：暂无自动化；规则见本条。[已自动化：否]

## L6 — NO_PROXY：Clash 破坏 localhost

- **Problem**：Clash/V2Ray 代理劫持 localhost，koharu API 连不上。
- **Root cause**：代理软件把 127.0.0.1 也走代理。
- **Durable lesson**：必须 `NO_PROXY=127.0.0.1,localhost`。
- **Prevention**：`koharu_client.ensure_no_proxy()` 自动处理；`start_koharu.ps1` 已设。
- **Regression**：`tests/test_client_helpers.py` 校验 ensure_no_proxy 设置。

## L7 — ctd_seg 只细化已有文字框（DAG 依赖）

- **Problem**：`comic-text-detector-seg` 只细化「已有文字框」——前置 detector 漏检则 OCR/mask/inpaint 全漏；`pp-doclayout-v3` 是文档模型，框外字漏检嫌疑元凶。
- **Root cause**：seg 阶段依赖前置 detector 的 TextBoxes，无法凭空找回漏检。
- **Durable lesson**：检测召回是流水线上游硬约束，前置漏检不可被后续阶段补救。
- **Prevention**：Benchmark A 四 detector 同页对比验证召回；检测评估优先 recall。
- **Regression**：`tests/test_pipeline.py` 校验 inpaint 引擎依赖 Segment+Bubble mask（结构不变量）。

## L8 — patch 译文后必须重跑 koharu-renderer

- **Problem**：改了译文但没重渲染，导出仍用缓存旧图。
- **Root cause**：渲染器以渲染时输入为准，译文改动不自动触发重渲染。
- **Durable lesson**：任何译文/mask 改动后必须重跑 koharu-renderer 再导出。
- **Prevention**：koharu-drive skill 修复循环第 5 步强制。
- **Regression**：暂无自动化（运行时序）；规则见本条。[已自动化：否]

## L9 — koharu 内置 llama.cpp 太旧：paddle/mit48px OCR 引擎全不可用

- **Problem**：koharu 的 paddle-ocr-vl-1.5 引擎每次跑都 `completed_with_errors`（detector 有 confidence 但 ocr 全空），日志：`unable to initialize multimodal projector: MTMD context initialization returned null`。
- **Root cause**：koharu v0.59.1 内置 llama.cpp b8935（2026-05-18），初始化 PaddleOCR-VL 的视觉投影（mmproj）失败；同模型文件用现代 llama.cpp **b10582 秒加载、OCR 正常**。是运行时版本太旧，不是模型/调用问题。
- **Durable lesson**：koharu 的 paddle/mit48px OCR 引擎在 v0.59.1 上不可用（只 manga-ocr 可用）；需要 VLM OCR 时绕开 koharu 引擎，用独立 llama-server（`models/llama-cpp/llama-server.exe`，版本 ≥b10582）+ GGUF 模型，OpenAI 兼容接口、prompt `OCR:`。
- **Prevention**：漫画 OCR 统一走独立 llama-server:8118；koharu 引擎目录的 OCR 项当"坏的"处理，不尝试修复。
- **Regression**：暂无自动化（外部二进制版本约束）；规则见本条。[已自动化：否]

## L10 — 通用 VLM 竖排日语系统性差：必须用漫画微调模型

- **Problem**：qwen-vl-ocr 实测竖排漫画 crop 词序错乱（GT `穢れを嫌った神々が住む都` → 输出 `住む都を嫌った神々が穢れ`）。
- **Root cause**：arXiv 2511.15059 证实所有通用 MLLM 竖排日语显著差于横排（通病）；PaddleOCR-VL 基座也是（openvino-book：EM 9%/CER 55.41% vs 微调后 64.4%/10.88%）。
- **Durable lesson**：竖排日语漫画 OCR 的远程 API 基座模型（qwen-vl-ocr / PaddleOCR-VL 基座 / DeepSeek-OCR）都不可靠；必须用漫画微调模型（PaddleOCR-VL-For-Manga / GLM-OCR-Manga-LoRA 等）。
- **Prevention**：OCR 选型先查"是否漫画/竖排微调"，再看 CER；远程 API 只当对照组。
- **Regression**：`output/_paddle_manga_probe.json`（对比证据）；`output/benchmark_b_paddle_manga.json`（全量）[已自动化：否]

---

## 模板（新增时复制）

```
## Lx — <一句话标题>

- **Problem**：
- **Root cause**：
- **Durable lesson**：
- **Prevention**：
- **Regression**：<测试/文件，或"暂无自动化，规则见本条">
```
