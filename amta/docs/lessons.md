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
- **Regression**：内容级匹配逻辑已在 `scripts/recall_score.py`（复用 `src/amta/metrics.py`）；纯函数单测在 `tests/test_shared_lib.py` 锁定。

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
- **Regression**：`output/data/benchmark_b_paddle_manga.json`（全量 CER/EM）；对比证据见 `docs/decisions/008-local-manga-ocr.md`。[已自动化：否]

---

## L11 — DSH 技能根 ≠ CC 约定：`.claude/skills` 是死配置 + #1401 frontmatter bug

- **Problem**：harness 沿用 Claude Code 约定把技能放 `.claude/skills/`，但 DSH 技能发现根是项目 `.dsh/skills` 与 `.agents/skills`（源码 `packages/skill/skill-filesystem/src/index.ts`）——技能从未进入 DSH skill catalog；且 cycle-close / background-monitoring 的 description 含未引号 `": "` 会被 DSH **静默丢弃整个技能**（issue #1401）。
- **Root cause**：DSH ≠ Claude Code——`.claude/skills`、`.claude/rules`、`.claude/agents`、`.claude/settings.json` 均不被 DSH 解释；YAML frontmatter 中 ASCII 冒号+空格必须引号包裹。
- **Durable lesson**：DSH 下技能唯一事实源 = `.dsh/skills/<name>/SKILL.md`（git 正常跟踪）；CLAUDE.md / AGENTS.md 原生自动注入；hook 只走 git hooks（CC 生命周期 hook 桥是进程级 configPath + PreToolUse deny-only，会跨项目泄漏，不装）；CC 专有 frontmatter（如 `disable-model-invocation`）被 DSH 丢弃。
- **Prevention**：新技能建在 `.dsh/skills/`；description 一律单引号包裹；CC→DSH 迁移用 `npx dsh-movein`（dry-run → --apply → doctor；Windows 无 symlink 权限时回退 **copy**，须手动消除双份）。
- **Regression**：`npx dsh-movein doctor` 校验技能 frontmatter；audit skill 检查 `.dsh/skills/` 过时/重复。[已自动化：否]

---

## L12 — 并集框去重 IoU>0.5 漏合并竖排碎片框：同文本多 crop 多统计

- **Problem**：benchmark_b_paddle_manga 126 行中 48 行 = 24 组「同内容」重复（同页 uXX/uXX+~8 成对，唯一跨页 カチャ 是真实 SFX），ALL 指标被同文本重复计数污染。
- **Root cause**：`geometry.union_boxes` 去重只按 `IoU > 0.5`；竖排文本块被 detector 切成上下相邻/包含的碎片框时 IoU≈0，合并失败 → 同一文本被多次 crop、多次统计。
- **Durable lesson**：多 detector 并集去重不能只靠 IoU 阈值——碎片框（相邻/包含）必须合并；统计阶段再做「同页同内容」去重。
- **Prevention**：union 去重增加包含/重叠合并（IoU>0.5 或一框含另一框或同 x 区间相邻 y）；计数时对同页 norm(gt) 相同行去重。
- **Regression**：待 union_boxes 修复后，`tests/test_shared_lib.py` 新增竖排碎片框合并用例（当前不加，避免红测试）。[已自动化：否]

## L13 — VLM per-crop 独立标注的 GT 不可靠：正式 GT 必须用整页枚举

- **Problem**：benchmark_b_paddle_manga 的 GT 是探针阶段「per-crop describe_image 独立标注」，非正式 `recall_gt.json`（整页枚举）——126 行中 25 行 GT 不可靠（3 空 + 1 纯符号 + 21 与正式 GT 不一致：う〜ん→うくん、穢れ 缺字、確かだ→たしかだ、把装饰/数字 150/nnn/0/一二/！ 当文本）；page_8_u06/u14 还丢 ～ 导致匹配失败误判。
- **Root cause**：per-crop 标注只看单张裁剪、缺整页上下文，VLM 丢字符、误读装饰、把数字当文本；「OCR 真值 = describe_image 逐 crop」的方法论被误用于正式 GT。
- **Durable lesson**：内容型 GT（OCR 真值文本）必须用**整页枚举清单**（recall_gt.json 方式）；per-crop VLM 标注只适合真假/类别判定，不能直接当正式 GT 入库。
- **Prevention**：benchmark skill 明确「正式评测 GT 来源 = recall_gt.json」；per-crop 标注与正式 GT 冲突时以正式 GT 为准并人工抽查。
- **Regression**：暂无自动化（标注质量属 VLM 流程）；规则见本条与 benchmark skill。[已自动化：否]

## L14 — 数据文件缓存派生指标：norm 口径漂移后不重算 → 假 bug（GT=OCR 却 EM=0）

- **Problem**：benchmark_b_paddle_manga 的 json 缓存每行 cer/em，但用「只去空白」旧 norm（保留全部标点）；`src/amta/metrics.py` 在 /simplify 重构后 norm 改为「去全部标点」，json 未重算 → 出现「GT=OCR 但 EM=0」的假异常。现行 norm 重算：EM 0.516→0.770、CER 0.316→0.121（32 行 0→1，无 1→0）。
- **Root cause**：派生指标（cer/em）落盘后与代码口径脱钩；口径变更未触发重算。
- **Durable lesson**：评测数据文件**不要缓存派生指标**（或缓存必须带口径版本号）；改 norm 后必须全量重算已入库指标，并用一致性测试兜底。
- **Prevention**：json 只存原始 gt/pred 文本，cer/em 现算；重生成后加「重算 vs 存储」一致性测试（待 json 重生成后加，避免红测试）。
- **Regression**：待重生成后，`tests/test_output.py` 对 benchmark_b_paddle_manga.json 每行用 metrics 重算 cer/em 并与存储值比对。[已自动化：否]

## L15 — 报告叠加框必须标注真实来源：detector 检出框 ≠ GT bbox

- **Problem**：benchmark_b 报告「原图+检测框」叠加的是 detector 检出 union 框（126 个，含误检），标题却标 "GT bbox"；与 recall_report（真 GT bbox，101 条，VLM 整页枚举）对比出现「空白框」困惑。126−101=25 个多余框 = 误检 + 重复计数。
- **Root cause**：报告生成时把「叠加的框」想当然标成 GT，未核对框的数据来源。
- **Durable lesson**：可视化叠加框必须写明来源（detector 检出框 / GT bbox）——两者数量与语义都不同，误标会误导 QA 结论。
- **Prevention**：报告图例/标题直接写数据源（如 "detector union boxes (n=126)"）；benchmark skill 报告段列明框来源约定。
- **Regression**：暂无自动化（HTML 报告为生成物）；规则见本条与 benchmark skill。[已自动化：否]

## L16 — OCR 评测坐标源必须用 detector 对齐框，勿用 GT 缩略 bbox 或误用单引擎框

- **Problem**：OCR 评测「裁框→OCR→比 GT」时，若直接用 recall_gt.json 的 bbox 裁图（VLM 缩略坐标，x 上限约图宽 40%）会裁出空白→OCR 幻觉→假 CER 27；若误用 ocr_result.json 的 manga-ocr 引擎框（每页 5~9 个，共 55 个）当坐标源，又出现「page_5 全 fallback、55/101、指标假高」假象。
- **Root cause**：评测坐标源选错。GT bbox 是缩略坐标不可靠；manga-ocr 引擎框只是单一引擎输出，非 detector 并集；正确源是 detector 4 并集 crop 图（recall_crops，全尺寸可靠坐标，134 张全有效）。
- **Durable lesson**：评测 OCR 必须用 **detector 对齐框**（detector 并集 crop 图 + GT 语义内容，字符重合度≥0.6 内容对齐）做输入；GT 内容做比对基准；**GT 的 bbox 坐标与单引擎框都不是评测坐标源**。detector 未检出的 GT 框单独归为「检测覆盖缺口」，不混入 OCR 指标。
- **Prevention**：评测脚本从 recall_ocr.json（detector 内容）+ recall_crops（图）+ recall_gt.json（GT 内容）构造评测清单；页码注意偏移（ocr_result/recall_ocr 的 page_N 是 0 基 ↔ recall_gt 的 page_N 是 1 基）。
- **Regression**：`tests/test_ocr_run.py` 已锁「评测坐标来自 det_boxes 而非 GT bbox」；OCR 评测跑批前需人工核对 crop dark% 非 0。[已自动化：部分]

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
