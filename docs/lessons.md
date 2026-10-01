# Lessons（可复用经验库 = 坑的唯一归属）

> 回答："我们从问题中学到了什么？"
> **本文件是「坑/经验」的唯一事实来源**。CLAUDE.md 只保留最精简的关键规则与指针，**不重复贴坑**。
> 不是流水账。每条 = Problem / Root cause / Durable lesson / Prevention / Regression。
> 只有当一条经验**稳定可复用**时才写进来；一次性实现细节不写。
> 晋升路径：Lesson（本文件）→ 稳定 Rule（CLAUDE.md）→ Invariant → 测试/hook。被自动化覆盖的条目标注 `[已自动化]`。

---

## 目录（书脊速查）

- L2 — 假数据落盘（最致命）
- L3 — wait_operation 卡死：completed_with_errors 未被识别
- L4 — workers>1 在 CPU/集显下崩溃
- L7 — ctd_seg 只细化已有文字框（DAG 依赖）
- L10 — 通用 VLM 竖排日语系统性差：必须用漫画微调模型
- L11 — DSH 技能根 ≠ CC 约定：`.claude/skills` 是死配置 + #1401 frontmatter bug
- L12 — 并集框去重 IoU>0.5 漏合并竖排碎片框：同文本多 crop 多统计
- L13 — VLM per-crop 独立标注的 GT 不可靠：正式 GT 必须用整页枚举
- L14 — 数据文件缓存派生指标：norm 口径漂移后不重算 → 假 bug（GT=OCR 却 EM=0）
- L15 — 报告叠加框必须标注真实来源：detector 检出框 ≠ GT bbox
- L16 — OCR 评测坐标源必须用 detector 对齐框，勿用 GT 缩略 bbox 或误用单引擎框
- L18 — 本地 OCR 性能：BF16 未量化 + 缺省参数 = 30s/张；Q8_0 + 参数优化 + baberu 快路径
- L22 — DeepSeek 模型 id 必须实测 models 端点：带日期后缀的 id 是雷
- L23 — DeepSeek v4-pro 是推理模型、vision-exp 偶发空响应：调用要防"content 为空"
- L25 — 声称"全量验证"必须有可复现基线：未提交旧版上跑的数不算
- L26 — fastcheck/pre-commit 需要 Python 3.13 全局解释器：AutoClaw 的 python 无 pytest/ruff
- L27 — OpenClaw 工具输出对 api_key= 赋值脱敏：写代码后必须校验实际内容
- L28 — PowerShell 管道缓冲会让后台任务输出"消失"：Tee-Object 经 2>&1 可能整体延迟
- L29 — 中文/多行字符串 JSON 勿用 PowerShell ConvertFrom-Json（PS5.1 解析失败）
- L30 — CRLF 行尾文件 edit 工具精确匹配失败：用 Python 脚本替换并保持行尾
- L34 — 记忆检索要 hook push（UserPromptSubmit 注入），别只靠 MCP pull（工具自觉）
- L35 — CLAUDE_CONFIG_DIR 改配置位置：查 MCP 授权先看 env 再动 ~/.claude.json
- L36 — 发行名与 import 名只差分隔符（hayai_ocr vs hayai-ocr）：比较前做 PEP 503 归一化
- L37 — 本地模块归档进 archive/ 后，残留 importer 被 depguard 误报"第三方未声明"：归档时须连带清 importer
- L41 — depguard 补声明已传递安装的依赖时，版本读 uv.lock 的公共版本，别抄 `__version__` 的本地构建标签（+cpu）
- L43 — Windows 下 claude CLI 是 claude.cmd/.ps1：Python subprocess 不能直接执行，必须经 cmd /c 走 PATHEXT
- L45 — Claude Code ≥2.1.210 收紧 PreToolUse hook 输出 schema：legacy {"decision":...} 被拒 + guard 静默假死
- L46 — VLM 逐框字体风格分类：contact sheet 可行但不精准，整页带框因分辨率不够全错
- L48 — residue 正则把片假名中点「・」/长音符「ー」误判为日文残留
- L47 — 行为变更必同步测试断言；烂 venv 的门是纸糊的（6 红静默溜进 main 实证）；方向选择由几何推断决定，不由 1px 字号噪声决定
- L49 — 假阳性治理：translate纯标点条款 + inpaint契约理顺（省略号类假阳性闭环）
- L50 — 散文铁律无断言 = 一周被违反 4 次：HTML 报告规则只有牙齿才叫规则
- L51 — 判"没人用就删"必须横跨全部 harness：只统计一两份轨迹 = 不成立的证据
- L52 — VLM 做视觉决策，本地代码做机械执行：别让通用模型数手指
- L53 — probe 正式化进 station：load_canon 会剥掉顶层 ocr_engine，模式判断必须读原始信封
- L54 — 度量层和渲染层必须共享同一套"字符占多宽"的认知
- L55 — 宽泛负面提示造成漏译时，收窄边界而非增长正面类别清单
- L56 — 擦除气泡文字：文字矩形 ≠ 气泡区域，别用几何近似代替视觉理解
- L57 — 页号有两个体系：GUI 上传会重编号，`--src-dir` 才对应原图文件名
- L58 — 守卫必须自证"我扫了什么"：静默失效的检查比没有检查更危险

---


## L2 — 假数据落盘（最致命）

- **Problem**：skill 测试时 subagent 曾把虚构的 "PaddleOCR-VL CER 0.11" 当真结果落盘并推送，需回滚纠正。
- **Root cause**：落盘前未校验"数据是否本会话实测、有无证据文件"；把规划/假设当结论。
- **Durable lesson**：任何要写进 CLAUDE.md / benchmark 报告的数字，必须有可查的证据文件（output/*.json 或脚本输出）；拿不出证据只写"待验证/规划"。
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


## L7 — ctd_seg 只细化已有文字框（DAG 依赖）

- **Problem**：`comic-text-detector-seg` 只细化「已有文字框」——前置 detector 漏检则 OCR/mask/inpaint 全漏；`pp-doclayout-v3` 是文档模型，框外字漏检嫌疑元凶。
- **Root cause**：seg 阶段依赖前置 detector 的 TextBoxes，无法凭空找回漏检。
- **Durable lesson**：检测召回是流水线上游硬约束，前置漏检不可被后续阶段补救。
- **Prevention**：Benchmark A 四 detector 同页对比验证召回；检测评估优先 recall。
- **Regression**：`tests/test_pipeline.py` 校验 inpaint 引擎依赖 Segment+Bubble mask（结构不变量）。


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
- **Durable lesson**：DSH 下技能唯一事实源 = `.dsh/skills/<name>/SKILL.md`（git 正常跟踪）；CLAUDE.md / AGENTS.md 原生自动注入；hook 只走 git hooks（CC 生命周期 hook 桥是进程级 configPath + PreToolUse deny-only，会跨项目泄漏，不装）。
  ⚠️ **2026-09-12 更正（本条此前的一个论断是错的）**：原文写「CC 专有 frontmatter（如 `disable-model-invocation`）被 DSH 丢弃」——**已过期，现在是反的**。当前 DSH 明确实现该字段：`packages/skill/skill-filesystem/src/index.ts:993-999` 读取 `disable-model-invocation` 并写入 `modelInvocable: disableModelInvocation !== true`，据此把技能**从面向模型的目录与 loader 中排除**（README.zh.md:55-57 亦载明：该字段被拒绝或非布尔时会**连同整个技能一起丢弃**并告警，是 fail-closed）。实证：`handoff` / `teach` 两个技能确实**不在**本会话的 skill catalog 里，而它们正是标了 `disable-model-invocation: true` 的。故**该标记今天就可用**，不必再靠"不放 `.dsh/skills/`"来限制。
  推论（这才是本条真正可复用的部分）：**DSH 会演进，写在 lesson 里的"DSH 不支持 X"必须标日期并配探针**——否则它会像这条一样，从经验变成谣言。
- **Prevention**：新技能建在 `.dsh/skills/`；description 一律单引号包裹；CC→DSH 迁移用 `npx dsh-movein`（dry-run → --apply → doctor；Windows 无 symlink 权限时回退 **copy**，须手动消除双份）；**改完任何 SKILL.md 立即用 skill()/斜杠验证一次**（2026-08-24 复发：grill-me 被用户改写时弄丢引号，整个技能静默消失，`description:` 后必须引号+空格）。
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


## L18 — 本地 OCR 性能：BF16 未量化 + 缺省参数 = 30s/张；Q8_0 + 参数优化 + baberu 快路径

- **Problem**：PaddleOCR-VL-For-Manga（BF16 未量化）每张 crop 20-40s，101 张约 1 小时，用户感知"非常慢"。
- **Root cause**：① 主模型 BF16 全精度（16BPW），CPU prompt eval 仅 6-8 tok/s；② llama-server 用默认参数（线程 4、无 batch/fa/KV 量化）；③ 逐张 HTTP 请求无法复用；④ 图像被统一缩放成 ~210-230 视觉 token，与输入尺寸无关（缩放输入图无效）。
- **Durable lesson**：CPU 推理先量化 Q8_0（实测 -30% prompt eval 耗时）；llama-server 加 `-t 8 -c 8192 -b 256 -ub 512 -fa on -ctk q8_0 -ctv q8_0 --mlock`；`--cache-reuse` 对多模态无效别加；换 baberu-OCR（ONNX）可 28 倍提速（1s/张，常规对白 CER 相当）。
- **Prevention**：start_llama_ocr.ps1 默认 Q8_0 + 优化参数；mmproj 保持 BF16（列 4304 非 32 倍数，Q8_0 量化会失败）。
- **Regression**：实测基线 BF16 31.3s/张 → Q8_0+参数 27.1s/张（真实推理）；baberu 1.05s/张。


## L22 — DeepSeek 模型 id 必须实测 models 端点：带日期后缀的 id 是雷

- **Problem**：`.env` 的 `CHAT_MODEL=deepseek-v4-pro-0813` 无效——首次真实调用即报错。DeepSeek 公开服务实测真实 id 是 `deepseek-v4-pro` / `deepseek-v4-flash` / `deepseek-v4-flash-vision-exp`。
- **Root cause**：模型 id 是从文档/猜测抄来的自造值（带 `-0813` 日期后缀），未对实际 API 验证；ADR-014 里记录的也是这个错 id。
- **Durable lesson**：调 DeepSeek 前先用 `GET {base_url}/models`（Bearer key）实测可用 id；`.env` 的 `CHAT_MODEL` 只写实测值，不写带日期后缀的猜测值。
- **Prevention**：新增/改动 CHAT_MODEL 必须跑一次 models 端点核对；本会话已把 `.env` 修正为 `deepseek-v4-pro`。
- **Regression**：暂无自动化（需真实 API）；以探针"月の都→月之都"证明修正后通路通。

## L23 — DeepSeek v4-pro 是推理模型、vision-exp 偶发空响应：调用要防"content 为空"

- **Problem**：`deepseek-v4-pro` 的 `reasoning_content` 吃光 max_tokens 后 `content` 为空（finish_reason=length，答案没出来）；`deepseek-v4-flash-vision-exp` 约 14% 概率返回空 content。
- **Root cause**：推理模型先输出 CoT（reasoning_content）再输出正式答案，max_tokens 给不足则答案出不来；vision-exp 偶发无输出。
- **Durable lesson**：调这两个模型都要：(a) max_tokens 给足（评审类 ≥1200）；(b) 空 content 自动重试（评审脚本空 content 自动重试（retries=2））。
- **Prevention**：写任何调 CHAT_* 的脚本先看本条；解析响应前检查 content 非空，空响应按"无输出/重试"处理，勿当"评审不通过"。
- **Regression**：`tests/test_semantic_check.py::test_parse_verdict_inconclusive_on_empty` 锁定空响应归类 inconclusive（不误计 fail）。

---


## L25 — 声称"全量验证"必须有可复现基线：未提交旧版上跑的数不算

- **Problem**：修复 JUDGE_PROMPT 后重跑，通过率 83/86（96.5%）→ 79/86（94.0%）——83/86 是在未提交的旧 prompt 版本上跑的，不可复现。
- **Root cause**：验证结果在代码未提交/未钉版本时记录，HEAD 变化后旧数无法复现。
- **Durable lesson**：报告任何"全量验证"数字前：`git status` 必须干净（或明确记录 commit）；改代码后旧基线作废必须重跑，新旧数不可混用。
- **Prevention**：跑全量验证前确认工作区干净并记 commit；结果文件/进度条目标注 HEAD。
- **Regression**：暂无自动化（流程约束）。[已自动化：否]

## L26 — fastcheck/pre-commit 需要 Python 3.13 全局解释器：AutoClaw 的 python 无 pytest/ruff

- **Problem**：PATH 默认 `python` 是 AutoClaw 自带环境（无 pytest/ruff/pyright），跑 fastcheck 报缺依赖，pre-commit hook 直接拦截 commit。
- **Root cause**：本机 PATH 被 AutoClaw 等工具抢占；hook 用 `command -v python` 取到错的解释器（.githooks/pre-commit）。
- **Durable lesson**：本项目所有验证命令（fastcheck/hooks/npm scripts）必须用 Python 3.13 全局解释器；验证/提交前把 Python313 放 PATH 最前。
- **Prevention**：pre-commit 显式优先 python3.13（已改 .githooks/pre-commit）。
- **Regression**：暂无自动化（环境约束）。[已自动化：否]

## L27 — OpenClaw 工具输出对 api_key= 赋值脱敏：写代码后必须校验实际内容

- **Problem**：本环境 read/exec/write 对 api_key= 相关赋值片段会显示/写入 `api_key=***`（含 API key 引用的代码曾被写入 `api_key=***` 导致 SyntaxError）。
- **Root cause**：OpenClaw 主机对 api_key= 模式做脱敏（防密钥泄漏）；脱敏可能发生在显示层，也可能真实写入文件。
- **Durable lesson**：在本环境写含 API key 引用的代码后，必须用 compile/import/git diff 校验文件实际内容，不能以工具显示为准。
- **Prevention**：落盘后立即 compile 校验 + git diff 核对。
- **Regression**：暂无自动化。[已自动化：否]

## L28 — PowerShell 管道缓冲会让后台任务输出"消失"：Tee-Object 经 2>&1 可能整体延迟

- **Problem**：后台 00_run_all 经 `2>&1 | Tee-Object` 跑，轮询时看不到中间输出，误判"没跑"。
- **Root cause**：PowerShell 对原生命令 stdout 的管道批处理/缓冲，Tee 落盘与显示都可能滞后到进程结束。
- **Durable lesson**：后台长任务的进度验证以**产物文件为准**（artifacts/*.json 是否生成/更新），不要依赖管道日志。
- **Prevention**：长任务重定向到独立日志文件（`*> file`）而非 Tee；核对产物 mtime/内容。
- **Regression**：暂无自动化，规则见本条目。

## L29 — 中文/多行字符串 JSON 勿用 PowerShell ConvertFrom-Json（PS5.1 解析失败）

- **Problem**：canon.json 含多行 OCR 文本，`ConvertFrom-Json` 报"应为 ':' 或 '}'"，统计条数全 0。
- **Root cause**：Windows PowerShell 5.1 ConvertFrom-Json 对字符串内换行的处理缺陷。
- **Durable lesson**：JSON 统计/解析一律用 Python（`json.loads`），PowerShell 只做文件存在性检查。
- **Prevention**：写临时 python 脚本或 `python -c`；勿信 PS 解析结果。
- **Regression**：暂无自动化。

## L30 — CRLF 行尾文件 edit 工具精确匹配失败：用 Python 脚本替换并保持行尾

- **Problem**：scripts/02_ocr.py（CRLF）用 edit 工具改不动（oldText 匹配不上），报"exact text not found"。
- **Root cause**：edit 工具按 LF 语义匹配，CRLF 文件含 \r\n。
- **Durable lesson**：改 CRLF 文件用 Python（read→replace→write，读出来的 \r\n 原样写回），断言 anchor count==1 防误替换。
- **Prevention**：先 `Get-Content -Raw` 检查含 "\r\n"；替换后 `compile()` 验证语法。
- **Regression**：暂无自动化。


## L34 — 记忆检索要 hook push（UserPromptSubmit 注入），别只靠 MCP pull（工具自觉）

- **Problem**：用户问"detect 模型演进"，记忆字典查不到且我全程没用 MCP——MCP 工具未授权加载是表层，深因是 **pull 层靠执行纪律**：工具在列表里也要模型"记得去调"，不调就等于没有。CLAUDE.local.md 也只写 600 字摘要（loop_state+字典规则），lessons/ADR 全文没进上下文。
- **Root cause**：① MCP 是 pull 模型，触发权在模型行为，无法强制；② 项目记忆包预算 1.5KB 只装接续状态+字典规则（ADR-027 内容契约），坑库全文从不注入；③ 无任何 hook 在提问时按关键词检索记忆。
- **Durable lesson**：真强制层 = **UserPromptSubmit hook 按 prompt 关键词检索地产并 stdout 注入**（Claude Code 四个 stdout 注入例外事件之一，见 hooks 文档）；"遇错/决策前先查"这种 prompt 级纪律没 hook 就是空话。MCP/CLI 降级为按需打捞（pull），hook 管每轮推送（push）。
- **Prevention**：scripts/memory_autoinject.py（extract_tokens→do_grep→≤3KB stdout，恒 exit 0，无命中零输出）+ .claude/settings.json UserPromptSubmit 挂载；注入预算 ≤3KB（CC 实测 ~10K 落盘替换为 2KB 预览）。
- **⚠️ 2026-09-10 更正（DSH 环境）**：上面这条 Prevention **在 DSH 上不成立**——`.claude/settings.json` 的 hook 不被 DSH 解释（见 L11），所以 UserPromptSubmit push 通道**从未存在过**。本条"别只靠 MCP pull"的结论仍然成立，但可用的 push 通道是另一个：
  - DSH 上每轮必达的是 **agent-instructions 对 `CLAUDE.md` / `AGENTS.md` / `CLAUDE.local.md` 的注入**（不靠模型自觉）；
  - 所以 push 的正确做法是**喂饱那个注入面**（即 `memory.py inject` 的产出内容与预算），而不是挂 CC hook；
  - 2026-09-10 实测：MCP 已在 DSH 接通（cordis 插件行 + `scripts/install_dsh_mcp.ps1`，工具名 `mcp__amta-memory__memory_search`），但 **pull 层依旧靠自觉**——该轮改造中我一次都没主动调 `memory_search`，本条描述的失效模式原样复发。**结论：只把 MCP 接通 ≠ 记忆会被用到。**
  - **2026-09-16 收尾（MCP 路线正式作废）**：820def6（09-14 17:30）归档 `scripts/mcp_memory.py` 时，DSH 侧注册块没跟着改 → 连接此后必然失败，**死了两天无人察觉**；而存活窗口（09-12→09-14）的轨迹里调用数为 **0**。处置：删注册块 + `install_dsh_mcp.ps1` + `.mcp.json`，检索回退 CLI（详见 ADR-027 后记）。
  - **教训升级**：不只「接通 ≠ 会被用到」，而是**接通之后还会静默死掉，而你没有探针测得出**——harness 契约 H2 只覆盖 hook 加载，不覆盖 MCP 连接性。若再引入 MCP，**声明生效前必须先有连接性探针**。
  - **同批发现（尚未处置）**：本条的 Prevention `scripts/memory_autoinject.py` **从未被任何 settings.json 挂载**——项目 `.claude/` 于 09-12 清空，真配置 `E:\claude\.claude\settings.json`（`CLAUDE_CONFIG_DIR`，见 L35）也**没有 `hooks` 键**。它从写出来那天起就没上桌。注：本轮会话（Claude Code）实测 UserPromptSubmit / SessionStart 通道**是活的**——但那来自 `remember` 插件自带 hook，不是我们的。所以 L34「CC 上 push 通道可挂」这半句**在当前 harness 仍然成立**，只是从没接上过。
- **Regression**：暂无自动化（hook 效果肉眼验证）；规则见本条 + memory_autoinject.py 契约头注释。

## L35 — CLAUDE_CONFIG_DIR 改配置位置：查 MCP 授权先看 env 再动 ~/.claude.json

- **Problem**：排查 amta-memory MCP 不加载，先改了 `C:\Users\asus\.claude.json` 的 enabledMcpjsonServers，无效——Claude Code 真读的是 `E:\claude\.claude\.claude.json`。
- **Root cause**：本机 `CLAUDE_CONFIG_DIR=E:\claude\.claude`，所有 Claude Code 配置（含 projects/<path>/mcpServers 授权）落在那里；默认 `~/.claude.json` 是旧文件/另一套。
- **Durable lesson**：排查/配置 Claude Code MCP 前先 `echo $CLAUDE_CONFIG_DIR` 定位真配置文件；MCP 项目级授权记录在 `<config>/projects/<path>.mcpServers`（local scope，最高优先级、免审批、自动加载，supabase 同款），`.mcp.json` 只是项目级声明需授权，local scope 会整体遮蔽同名。
- **Prevention**：改配置前备份（.bak-时间戳）；server 命令用绝对路径（CWD 非契约）；`python` 必须在启动 claude 的环境 PATH。
- **Regression**：暂无自动化；规则见本条。

## L36 — 发行名与 import 名只差分隔符（hayai_ocr vs hayai-ocr）：比较前做 PEP 503 归一化

- **Problem**：depguard 报 `src/amta/ocr_engines.py: import hayai_ocr 未声明`，同时报 pyproject 的 `hayai-ocr 未使用`——未声明+未使用双杀假阳，实为同一个发行版。
- **Root cause**：pyproject `[project].dependencies` 用发行名（PEP 503 规范形，小写连字符 `hayai-ocr`）；代码 import 顶层名受模块名语法限制用下划线（`hayai_ocr`）。depguard 直接字符串比较两边，没归一化就永远对不上。
- **Durable lesson**：凡比较"pyproject 发行名"与"代码 import 名/CLI 参数名"，先按 PEP 503 归一化（lower + `_`/`.`→`-`）再比；只差 `-`/`_` 的属同一类（如 `hayai_ocr`），而 `PIL→pillow`、`cv2→opencv-python` 这类名字全异的是另一类，需显式 IMPORT_TO_PKG 映射。比较键用归一化形，界面文案保留原名。
- **Prevention**：`scripts/depguard.py` 新增 `_norm()`，declared 与 used 双方都过归一化再查集。以后写同类校验工具（依赖/glossary 审计）直接复用该函数，别二次裸比较。
- **Regression**：暂无自动化；规则见本条 + `scripts/depguard.py` `_norm()` docstring。

## L37 — 本地模块归档进 archive/ 后，残留 importer 被 depguard 误报"第三方未声明"：归档时须连带清 importer

- **Problem**：depguard 报 `scripts/probe_ctd_mask.py / probe_e2e_inpaint.py / probe_overlay_text.py: import ctd_detector 未在 [project].dependencies 声明`。ctd_detector 明明是本仓模块，为何当第三方报？
- **Root cause**：`scripts/ctd_detector.py` 已被 git mv 进 `scripts/archive/`。depguard `_is_local_module()` 只在 src/scripts/tests 活动目录查同名 `.py`；模块进 archive 后该检查失效，残留 importer 的 `from ctd_detector import ...` 被当第三方顶层名 → 误报未声明。此时这些 importer 实际已硬死（archive/ 不入 sys.path，import 即 ModuleNotFoundError），depguard 报"未声明"其实是"死代码"的侧写。
- **Durable lesson**：把 scripts/tests 下被互 import 的本地模块归档（git mv → archive/）时，必须顺带清扫仍 import 它的活动文件（删 or 一起归档 or EXCLUDE_FILES），否则 depguard 挂一条看似莫名的"第三方未声明"红债。archive/ 在 ruff/pyright/depguard 扫描全部豁免，是"已死代码"的仓库级标记。
- **Prevention**：归档本地模块后跑 `py -3.13 scripts/depguard.py` 复查，新报的"未声明"若指向刚归档的本地名 → 去 grep 清 importer。
- **Regression**：暂无自动化；规则见本条。当前红债（4 探针命运）见 loop_state escalation，待人类裁决。


## L41 — depguard 补声明已传递安装的依赖时，版本读 uv.lock 的公共版本，别抄 `__version__` 的本地构建标签（+cpu）

- **Problem**：lama 本地 inpainting 直 import torch/safetensors 但 pyproject 未声明 → depguard 7 项 [未声明]。补声明时若照 `import torch; torch.__version__`（实测 `2.14.0+cpu`）写 `torch==2.14.0+cpu`，uv 解析会失败——本地标签不在分发索引的公共版本上。
- **Root cause**：同一 wheel 有两个版本面：安装后元数据 `__version__` 带 PEP 440 本地构建标签（`+cpu`），而 uv.lock `[[package]] version = "2.14.0"` 只记公共版本、本地标签落在 wheel url 里。pyproject 的 `==` 约束按公共版本对分发解析，抄错一个面就锁不上。
- **Durable lesson**：给"已由他人传递安装、只为 depguard 显式化"的依赖补声明时，**精确版本一律从 `uv.lock` 的 `version =` 字段抄公共版本**（torch/safetensors 之类带 +cpu/+cu 标签的尤甚），别从 `pip freeze` / `__version__` 抄。直声明与传递解析出的版本一致，`uv lock` 才能无扰动通过。
- **Prevention**：改 pyproject 后必跑 `uv lock` 复核（退出 0 + `git diff uv.lock` 应只见 root 包 dependencies/requires-dist 增两行，无版本漂移），再跑 `py -3.13 scripts/depguard.py` 确认转绿。
- **Regression**：depguard 0 项 + `uv lock` clean（amta root 包新增 safetensors==0.8.0 / torch==2.14.0 两条直声明）。


## L43 — Windows 下 claude CLI 是 claude.cmd/.ps1：Python subprocess 不能直接执行，必须经 cmd /c 走 PATHEXT

- **Problem**：scripts/review.py（L6 独立审核门）用 `subprocess.run(["claude", "-p", ...])` 报 WinError 2 找不到文件；同一命令在 PowerShell 里 `claude -p` 一切正常。
- **Root cause**：Windows 上 npm 装的 `claude` 实际是 `claude.cmd`（+ `claude.ps1`）脚本，PATH 里没有可执行的 `claude` 裸文件。PowerShell 走自己的命令解析能跑 .ps1/.cmd；Python subprocess 的 CreateProcess 不做 PATHEXT 解析、也不执行 .cmd/.ps1，所以裸名 "claude" 解析失败 → WinError 2。`shutil.which("claude")` 能返回 .CMD 路径（做存在性判定可用），但照此路径直接 Popen 仍失败。
- **Durable lesson**：Windows 下从 Python spawn 任何 npm/全局 CLI，先确认其真实形态（.exe / .cmd / .ps1）；若是 .cmd，用 `["cmd", "/c", "<name>", ...]` 调用（cmd 会按 PATHEXT 解析并正确转发 stdin/stdout）；大 prompt 走 stdin 管道（`subprocess.run(input=...)`）以绕开 Windows 命令行 ~32k 长度限制。
- **Prevention**：review.py 已用 `os.name == "nt"` 分支切 `cmd /c claude`；新写 spawn 外部 CLI 的脚本沿用此模式。
- **Regression**：`claude -p` 经 stdin 管道回 "OK"（实测，见 review.py L6 门）。


## L45 — Claude Code ≥2.1.210 收紧 PreToolUse hook 输出 schema：legacy {"decision":...} 被拒 + guard 静默假死

- **Problem**：`.claude/settings.json` 的 PreToolUse hook（hook_pretooluse.py）用 legacy 输出 `{"decision":"allow/block",...}`。claude 2.1.220 对每次工具调用校验 hook 输出：Read/Grep 等非 git 工具报 "Hook JSON output validation failed — (root): Invalid input"（噪音），而 git commit/merge 的 fastcheck FAIL 分支**根本不拦**——AGENTS.md"fastcheck FAIL 阻止 commit"的 guard 从未真正生效。
- **Root cause**：Claude Code 升级到 `hookSpecificOutput` 包装 schema（决策在 `permissionDecision` 字段）；legacy 根级 `decision` 被 Ajv 严格校验整体拒绝，且**校验失败 = 非阻断 allow 兜底**（工具照跑，只记 hook 错误）。噪音显性于 Read/Grep（每工具必撞无效 allow 分支），git 类**静默**（deny 同样无效 → 拦不住）——bug 存在很久无人察觉。
- **Durable lesson**：hook 输出 schema 有版本断裂风险，症状是 "hook JSON output validation failed" + 工具仍能跑（allow 兜底）。凡"靠 hook 当 guard"：**allow 分支失效只产生噪音，deny/block 分支失效是静默的 guard 死亡**——schema 升级后必须复测 deny 真能拦。诊断：往 hook 喂 PreToolUse stdin 样例看输出形状，对照官方 schema。
- **Prevention**：hook_pretooluse.py 已改 `hookSpecificOutput` 包装（allow/deny + permissionDecisionReason），settings 加 `matcher: "Bash"` 收窄触发面（Read/Grep/Edit 不再触发）。新写 hook 一律用 hookSpecificOutput + matcher。
- **Regression**：`claude -p` 冒烟 Bash 命令无 hook error（allow 路径，2026-09-05）；deny 真拦 + ralph 无头下 deny 是否 end turn，待一次故意 fastcheck FAIL 的 commit 实测。

## L46 — VLM 逐框字体风格分类：contact sheet 可行但不精准，整页带框因分辨率不够全错

- **Problem**：实验"给不同文字配不同字体"时，让 VLM 判断每个 crop 的字形风格。v1（contact sheet + 6类语气标签）受文字内容干扰；v2（contact sheet + 4类物理标签）3页对2页（14✅ 18✅ 17全判手写❌）；v3（整页带框+自由描述）整页缩到2000px后字太小，三页全错。
- **Root cause**：(1) contact sheet 看得清笔画但 VLM 逐格孤立判断，失去全局上下文；(2) 整页带框有全局但缩图后小字糊；(3) prompt 混入语气类标签会让 VLM 去读文字内容而非看字形。
- **Durable lesson**：VLM 逐框视觉分类有 trade-off——contact sheet 看得清但孤立，整页有全局但字糊。两者结合成本翻倍不值得。v2（contact sheet + 纯物理标签）技术上可行（~66%），生产级需调 max_cell_h 和 prompt。不要让 VLM 从语气类标签选。
- **Prevention**：脚本在 scripts/probes/probe_vlm_font_style.py，分支 experiment/vlm-font-style。重启时先调 v2 参数，不要回 v3 整页方案。
- **Regression**：3页实验（touhou-p17-20-e2e p14/17/18），对比图 workspace/touhou-p17-20-e2e/vlm_font_probe/comparison_v2.png。

## L47 — 行为变更必同步测试断言；烂 venv 的门是纸糊的

- **Problem**：main 侧 6 测试红 + 3 静态错静默存活多日。ce08bb8 删方向阈值改了 `infer_direction_from_bbox` 行为但测试断言未跟；且 main-inpaint worktree 的 venv 是化石（比 lockfile 多 26 旧包、缺 onnxruntime），在那边做的历次 merge/finish 的"全量质检"从未真正跑过 pytest——门是纸糊的，红就这么溜进 main。
- **Root cause**：①行为变更与测试断言脱节（commit 改了语义，测试还断言旧世界）；②环境腐坏是静默的：venv 过期不报错，pytest 收集即炸才暴露，而 finish 门在烂环境里跑出的"通过"是假绿。
- **Durable lesson**：①任何改行为的 commit 必须同 commit 更新受影响断言，`--skip-check` 留痕的债必须在下个会话首要还清，且当时已知 1 红实则 6 红——债务规模会静默膨胀；②worktree 的 venv 是目录级快照，不随 lockfile 更新，长命 worktree 必须用前 `uv sync` 或直接弃用；③窄长框纯字号选优实测横排 43 vs 竖排 42——1px 噪声级差距就翻转排版方向，方向选择必须由几何推断（bbox 长宽比）锚定，不能交给字号噪声。
- **Prevention**：行为变更的 PR 模板含"受影响测试清单"；worktree 长期不用即删（2026-09-16 main-inpaint 已删）。
- **Regression**：tests/test_typeset_engine.py::test_narrow_tall_box_prefers_vertical_with_large_font（改走真实管线契约：推断→传入）；fastcheck 457 passed / 0 failed。


## L48 — residue 正则把片假名中点「・」/长音符「ー」误判为日文残留

- **Problem**：跑红榜时 page_1 报「残留原文 1 条」，但译文其实干净——是扉页那行「…合同祭事参**・**月之宴8」里的间隔号「・」触发的。用户误以为是感叹号被检查。
- **Root cause**：`contains_japanese` 的正则是 `[\u3040-\u30ff]`，本意只抓平/片假名残留；但片假名区里还混着**中点 U+30FB「・」**和**长音符 U+30FC「ー」**——这两个在中文译文里是正常标点（间隔号、破折号），却被一起兜进残留判据。全角「！」(U+FF01)/「？」(U+FF1F) 在 FFF0 段，**不**误判，别冤枉感叹号。
- **Durable lesson**：见红榜「残留原文 N 条」先别慌——把那条 residue 字符串拉出来逐字符看码位，多半是「・」/「ー」假阳性。真残留是假名（の、な、ン…），不是标点。
- **Prevention**：未修。真要修就把 `_JAPANESE_RE` 改成在片假名段里挖掉 U+30FB，或在 residue 判定前 strip 掉「・」「ー」；修时补一个含「・」的中文译文不报警的单测。
- **Regression**：page_1 残留字符串实测 `'2015.2.21 东方合同祭事参・月之宴8'`；实测 `contains_japanese('合同祭事参・月')==True`、`contains_japanese('太可爱了！')==False`。



## L49 — 假阳性治理：translate纯标点条款 + inpaint契约理顺（省略号类假阳性闭环）

- **Problem**：省略号类框被走全流程——detect 框了纯标点省略号，OCR 读出来，LLM 原样吐回，inpaint 擦掉原文，typeset 重画一遍；更严重的是，OCR 因 conf 太低过滤掉的框，inpaint 照样擦。
- **Root cause**：两个契约断裂。
  1. translate 没有"判断要不要翻"的意识——它默认"给什么翻什么"，纯标点也照样处理。
  2. inpaint 直接读 detection.json 擦所有框——上游 OCR 过滤了什么、translate 决定翻不翻，它完全不知道。
- **Durable lesson**：
  - 纯标点/无实义内容的假阳性，用 LLM 原生语言能力就能治——不用硬编码正则阈值。改 prompt 加一句"完全是标点的内容输出空"就行，LLM 自己能区分"纯省略号"和"带省略号的正常台词"。
  - 流水线契约必须理顺：下游步骤只处理上游明确说"要"的东西。inpaint 应该依赖 translate，只擦有非空译文的框——而不是依赖 detect 擦所有框。
  - 背景门牌类假阳性（如"蓬莱"）纯文本 LLM 治不了——它看不到图，不知道是台词还是背景装饰。这类问题要么加 VLM，要么重训 detect，不是靠 prompt 能解决的。
- **Prevention**：
  - translate system prompt 已加"纯标点输出空"条款（2026-09-17）。
  - inpaint consumes 从 ["detect"] 改成 ["detect", "translate"]，只擦有译文的框。
- **Regression**：月天新地单页版 p5/p10 实测：r13/r02 纯省略号框输出空译文，inpaint 不擦，typeset 不写。

## L50 — 散文铁律无断言 = 一周被违反 4 次：HTML 报告规则只有牙齿才叫规则

- **Problem**：CLAUDE.md 第 53 行写着「HTML 报告铁律：必须用 `src/amta/report/` 深接口，禁止 scripts/ 下新建独立 HTML 生成脚本」。2026-09-20 单日 commit `5f99f10` 在 `scripts/probes/` 新写 4 个手写 HTML 生成器（~170 行 base64 拼 `<figure>`），同日另归档 3 个；`grep -rl "DOCTYPE\|<html" scripts/` 命中 14 个文件、共 1516 行。**全程没有任何测试或 hook 会失败。**
- **Root cause**：这条铁律写在「工作协议」里，属于**声明层**，但没有配探针——违反 `tests/test_harness_covenant.py` 的「新增声明 = 新增条款 + 新增探针」。声明没有探针 = 只靠散文存活，而散文拦不住任何人，正是 friction.md 说的"坏了 N 天没人发现"。
- **Durable lesson**：
  - 铁律级的「必须/禁止」，只要判据能写成一次 grep，就必须落成断言。只写在 CLAUDE.md 里的"禁止"，真实约束力等于 0——它约束的是**记得它的人**，而人恰恰是靠不住的变量。
  - 判据的**扫描范围必须是活文件**（`src/` `scripts/` `tests/`），不能 rglob 全仓：`reference/`（第三方克隆）与 `research/`（历史记录）里的 HTML 是当时的事实，对它们报错等于伪造历史、并让守卫永久变红 → 被人关掉。同 `test_reference_integrity` 的「只扫活文件」原则。
  - 草稿区要**显式声明**，不能靠默认放过：`scripts/probes/` 与 `scripts/archive/` 是草稿区，允许手写 HTML；生产路径（`src/` 除 `report/`、`scripts/*.py` 顶层、`tests/`）一律不许。
- **Prevention**：`tests/test_lessons_guard.py::test_L50_no_ad_hoc_html_report` —— 活文件出现 `<!DOCTYPE`/`<html` 即 fail；允许区仅 `src/amta/report/`（深接口本体）+ `scripts/probes/`、`scripts/archive/`（草稿区）。
- **Regression**：test_L50 本身；干跑基线 = 0 违规（生的就绿，不靠白名单回填）。

## L51 — 判"没人用就删"必须横跨全部 harness：只统计一两份轨迹 = 不成立的证据

- **Problem**：2026-09-15 按 DSH + Claude Code 两份轨迹统计，得出「`find_code.py` 关键词搜索 0 次调用」，据此删除。用户一句「你不是能查到对话记录吗」逼出第三份轨迹——豆包实际用了 4+ 次（后复核为 81 次调用）。删除判定作废。
- **Root cause**：把"我手上有的两份证据"当成了"用户行为的全集"。用户在同一个项目上**同时跑三个 harness**，各自把轨迹写在不同的地方，任何单份都不构成完整样本。
- **Durable lesson**：
  - 三份轨迹的位置：DSH `~/.dsh/sessions/<proj>/session-*.jsonl.zstd`（zstd 压缩）；Claude Code `E:\claude\.claude\projects\<proj>\*.jsonl`；豆包 `...\Doubao\User Data\Default\.doubao\agent_mode\workspace\.sessions\<id>\agents\<id>\system\trajectory.jsonl`。
  - "没人用"是**全称否定**，全称否定需要穷尽枚举。只查了一部分就下的结论，证据不成立。
  - 反面同样适用：判"某机制已生效"也不能只看一个 harness。
- **Prevention**：`docs/friction.md` 顶部判据已补一行（删/生判定必须横跨全部 harness）。**不建计数脚本**——三种轨迹格式各不相同且会漂移，写死的解析器会静默误计，比不查更糟。
- **Regression**：暂无自动化，规则见本条与 `friction.md` 头部判据。



## L52 — VLM 做视觉决策，本地代码做机械执行：别让通用模型数手指

- **Problem**：Paratext 管线第一版让 VLM 输出精确的 reak_after 字符索引来指定换行位置，配 3 次重试 + 本地启发式修正（_prefer_structural_breaks、_source_ink_ratio、_source_horizontal_alignment）。结果测试挂（换行索引在 Latin 标识符边界处冲突），代码臃肿（渲染子系统 ~464 行），VLM 还经常输出不合法的索引。
- **Root cause**：用通用模型（VLM）做它最不擅长的事——精确的机械索引计数。VLM 擅长看和理解（视觉风格、语义边界），不擅长数手指（第几个字符后换行）。而本地代码做机械任务（测量字宽、贪婪换行）又快又准，却被用来做"纠正 VLM"的启发式补丁。
- **Durable lesson**：
  - **分工铁律**：VLM/LLM 只做需要视觉理解或语义判断的决策（转写、字体风格、字号比例、颜色、对齐方向）；本地代码只做可测量的机械任务（换行、字号适配、画字）。两边各干各擅长的，不要交叉。
  - **重试是臭味**：如果需要重试才能拿到合法输出，说明契约或 prompt 设计有问题。修根因（收紧契约、改 prompt），不要加重试补丁。
  - **本地启发式"纠正"VLM 是技术债**：如果不信 VLM 的决策，要么给它更好的输入/上下文，要么这个决策本来就该本地做。_source_ink_ratio 这种比原图和干净图像像素差来估字号的代码，70 行，条件不满足就静默返回 None——等于白写。
  - **独立评审步骤不改变输出**：VLM 评审（review）只打分不修改，还会幻觉误报（把正确的"上海爱丽丝幻乐团"标为错误）。质量问题靠人眼看成品或自动化测试，不靠另一个 VLM 打分。
- **Prevention**：渲染子系统从 ~464 行（plan + render）降到 ~130 行（render alone），减了 72%。19 个测试全过。9 页实验页验证质量合格。
- **Regression**：	ests/test_paratext_experiment.py（19 个测试，含 wrap_horizontal kinsoku、贪婪换行、VLM 风格渲染）；scripts/probes/paratext_render.py（贪婪换行 + 按风格画字）。

## L53 — probe 正式化进 station 时：load_canon 会剥掉顶层 ocr_engine，模式判断必须读原始信封

- **Problem**：VLM 渲染分支接进正式 typeset_station.run 时，想按 `canon["ocr_engine"] == "vlm-paratext"` 决定走哪条渲染路径。但 station 一贯用 `load_canon(canon_path)` 读 canon，而 `load_canon` 只回白名单字段（work_id/page/schema_version/items/n_regions/vlm_status），顶层的 `ocr_engine` 和 `layout_observation` 被静默丢弃——判断永远是 False，VLM 页悄悄掉进普通 MITS 渲染。另外既有单测传的是旧裸 list 信封，`read_json` 直接 `.get(...)` 会 `AttributeError: 'list' object has no attribute 'get'`。
- **Root cause**：schema 信封加载器（load_canon）的职责是「规范化+校验+只暴露契约字段」，它和「按非契约元数据做分支路由」是两件事。拿规范化后的对象去读它刻意不暴露的字段，等于读空气。
- **Durable lesson**：
  - **路由判断读原始信封，规范化读 load_canon**：需要 `ocr_engine`/`layout_observation` 这类引擎自描述元数据做分支时，先用 `read_json` 读原始 dict 判断；确认命中后再决定是否需要 `load_canon`。VLM 分支里 items 自带全部排版字段（direction/align/font/font_size_ratio/color/stroke），直接用 raw items 即可，不必再过 load_canon。
  - **信封兼容要 isinstance**：`read_json` 可能返回旧裸 list（1.x 产物）。任何 `raw.get(...)` 前先 `isinstance(raw, dict)`，否则老产物直接 AttributeError。
  - **probe → 正式模块的迁移 = 复制 + 改 docstring，不改逻辑**：`scripts/probes/paratext_render.py` → `src/amta/typeset/vlm_render.py`，FONTS/换行/kinsoku/画字全部原样保留；probe 脚本保留并标 DEPRECATED，不删（历史实验还引用它）。
- **Prevention**：VLM 分支作为早期 return 放在 `load_canon` 之前；lazy import `render_text`/`validate_regions`，普通 hayai 路径不拉入 VLM 依赖。typeset StageSpec 的 code_files 加 `vlm_render.py`，改了渲染逻辑能触发 fingerprint 重跑。
- **Regression**：tests/typeset/test_vlm_render.py（layout/render 像素断言 + `test_station_vlm_branch_renders` 锁 VLM 早期 return 路径）。

## L54 — 度量层和渲染层必须共享同一套"字符占多宽"的认知

- **Problem**：2026-09-24 p59 译文中 "cosplay" 在竖排气泡里被逐字母竖排（c-o-s-p-l-a-y），不好读。第一反应是加硬编码 `[A-Za-z]{3,}` 强制横排，被否（打地鼠式，下次冒出 dragon 怎么办）。第二版做了縦中横渲染但度量层仍按"每字母占一字宽"算列宽，导致 fit_font_size 选了竖排但渲染时英文溢出/居中偏移。
- **Root cause**：度量层（`_fits` 算能不能放下、`fit_font_size` 选方向和字号）和渲染层（`_render_vertical` 实际画字）对"一个字符占多宽"的认知不一致。渲染层把连续拉丁字母横向排列（縦中横），度量层却还以为每个字母各占一个字宽、各占一行。结果度量层说"放得下"，渲染层实际溢出；度量层按字符数算行数，渲染层实际行数少一半，垂直居中偏移。
- **Durable lesson**：
  - **度量先行，渲染跟随**：先让度量层知道英文横向排列的实际宽度（`_vertical_col_width`），`fit_font_size` 基于真实度量自动选方向——短英文竖排放得下就保持竖排+縦中横，长英文竖排放不下就自动切横排。不需要硬编码"有英文就横排"。
  - **渲染层只做纯渲染**：縦中横是渲染机制，不做方向决策。方向决策全在度量层。
  - **行数计算也要用实际渲染行数**：縦中横把 n 个字母合并成 1 行，`_count_vertical_lines` 按实际渲染单元算行数，不能按 `len(text)` 字符数算。
  - **断行层要保护拉丁 token**：`break_lines` 不在英文单词/数字内部断行，避免 cosplay 被拆成 c/osplay。
- **Prevention**：`typeset_engine.py` 的 `_vertical_col_width` + `_is_latin_token_char` + `_inside_latin_token`；`typeset_render.py` 的 `_is_horizontal_char` + `_count_vertical_lines` + 縦中横渲染分支。
- **Regression**：全量 pytest 466 passed（含 typeset 渲染测试）；p59 实测 cosplay 縦中横正常、垂直居中正确。

## L55 — 宽泛负面提示造成漏译时，收窄边界而非增长正面类别清单

- **Problem**：把“拟声词、或没有实际语义”一概排除，使可识别的短促人声也可能输出空译文。
- **Root cause**：提示词的宽泛负面先验混淆了无法翻译的噪声与需要语境判断的表达。
- **Durable lesson**：先删除或收窄错误先验，再说明最小通用边界；不要用不断增长的正面类别清单补偿。已知样本全绿只证明这些样本通过，不证明泛化。
- **Prevention**：保留纯标点与真实乱码可为空的边界，让其他可识别内容由模型结合上下文翻译；见 ADR-036。
- **Regression**：`tests/test_stage3_minimal.py::test_prompt_translates_narrative_vocalizations_but_allows_noise_to_stay_empty` 锁提示词边界；实页证据与验证范围见 ADR-036。

## L56 — 擦除气泡文字：文字矩形 ≠ 气泡区域，别用几何近似代替视觉理解

- **Problem**：气泡内文字擦除反复横跳多轮——矩形涂白→全 LaMa→text-ink mask→std 分流→撤回涂白。根因是一直拿"文字检测矩形"当"气泡填充区域"：矩形形状和椭圆泡不匹配（shrink=8 在弧线收窄处对不齐），颜色写死 (255,255,255) 而气泡原生色是 (245,251,249) 冷灰白，差 10 个灰阶形成硬边，白矩形还盖到气泡外的黑头发。
- **Root cause**：这是 bitter lesson 的反面——一直在手写几何近似（shrink 魔法数字、写死白色、假设气泡是椭圆），而不是让模型直接看图像。文字检测框告诉你"这里有字"，但不告诉你"字周围是什么形状、什么颜色"。用矩形当 mask 等于让模型在一个错误的、过大的区域里重建，必然在边界处出条纹或硬边。
- **Durable lesson**：
  - **像素级 mask > 矩形 mask**：擦除文字时，mask 应该紧贴笔画像素（CTD DBNet seg 输出），而不是检测框膨胀出来的矩形。LaMa 只补笔画周围几像素，不需要"重建一大块空白"。
  - **别写死颜色**：气泡底不是纯白。让 LaMa 按周围像素采样，而不是 PIL 填 (255,255,255)。
  - **CTD 在白泡上和在复杂背景上是两个问题**：ADR-035 在 p62（文字压人物画）试 CTD 失败，不代表 CTD 在白泡上失败——白泡是白底黑字无歧义场景，CTD 精度完全够用。不要把一个场景的实验结论外推到另一个场景。
- **Prevention**：气泡走 `src/amta/inpaint/ctd_text_mask.py`（CTD seg → 阈值化 → 膨胀 → 按气泡 bbox 裁剪），再和框外 mask 合并送 LaMa。不写 shrink 魔法数字，不写死白色。
- **Regression**：page 7（姬兔合同本）实测椭圆泡内干净无矩形硬边、酒杯网点保留、作者名不被白块盖住；全量 562 passed。见 ADR-037。

## L57 — 页号有两个体系：GUI 上传会重编号，`--src-dir` 才对应原图文件名

- **Problem**：核对"原图 3 的决定有没有被原图 8 复用"时，拿 `workspace/gui-1790591328680/artifacts/translation/page_4.json` 当"原图 8"。实际上该 work-id 的 `page_1` 才是原图 3、`page_4` 是原图 8——编号整体错位。同期写的验证命令用了 `--start-page 0 --end-page 15`，而源目录根本没有 `0.jpg`。
- **Root cause**：存在两套页号，同名不同物。
  - **GUI 上传路径**：`src/amta/gui/server.py:254-271` 把用户上传的页按顺序**重命名**为 `1.jpg..n.jpg` 丢进 `workspace/<id>/input/`，原图名只记在 `input_manifest.json` 的 `stem`/`source_name` 里。所以 work-id 内的 `page_N` 是**上传序号**，与硬盘上的原图编号无关。
  - **`--src-dir` 路径**：`src/amta/orchestrator/pipeline.py:50-56` 用 `{n}.jpg` 直接拼文件名，`--start-page/--end-page` 是 1 基、**直接对应原图文件名**（`artifacts.page_key(N) = page_N`，`stores/artifacts.py:217`）。此时 `page_N` 就是原图 N。
  - 两套都产出名为 `page_N.json` 的产物，且都没有把"我是哪套编号"写进产物信封——`detection.json` 的 `source` 与 `image_meta` 实测为空，`canon.items[].page` 只是页号本身，无法反查原图。
- **Durable lesson**：
  - 用 work-id 里的 `page_N` 谈"原图第几页"之前，**先读该 work-id 的 `input_manifest.json`** 拿到 `{n: stem}` 映射；有 manifest = GUI 上传路径（编号被重写），无 manifest = `--src-dir` 路径（编号 == 原图名）。
  - 跨 work-id 比较产物前先对齐口径，否则"验证通过"是假的——`page_4` 在两个体系里可以是两张完全不同的图。
  - 源目录里没有的页号（如 `0.jpg`）只会打印一条 skip 警告然后静默少跑，不会报错。页号范围要按真实文件名来定。
- **Prevention**：验证脚本一律显式打印 `input_manifest.json` 的映射再断言；`--src-dir` 指向真实原图目录时用 `--start-page 1` 起。
- **Regression**：暂无自动化（属于操作口径，非代码行为）。本条的实测证据见 `docs/superpowers/specs/2026-09-30-book-translation-memory-design.md` §1 与 `output/notes/2026-09-30-red-tests.md`。

## L58 — 守卫必须自证"我扫了什么"：静默失效的检查比没有检查更危险

- **Problem**：`state.py finish` 全量门禁被 depguard 拦下，报同一条依赖**两个罪**——
  `deepseek-harness-sdk` 既「未声明」又「已声明但未使用」。而这条依赖完全合法、
  已声明、也确实被 import。两个罪同时成立在逻辑上不可能，说明是工具坏了，不是代码坏了。
- **Root cause**：depguard 用 `importlib.metadata.packages_distributions()` 把 import 名
  解析成分布名。该 API 在 `scripts/` 包语境下**静默返回空 dict**（同一进程里内联调用却
  返回 80 条，逐字相同的语句、结果不同），于是 `deepseek_harness → deepseek-harness-sdk`
  解析不出来，`-sdk` 后缀导致名字对不上，一条依赖被双杀。
  真正的病根不是这个 API，而是**代码里没有任何东西能证明"我确实查了"**：
  空结果与"干净的仓库"在输出上完全一样。
- **Durable lesson**：
  - **算出来的检查必须报告它扫了什么**。`0 命中` 与 `根本没扫` 在输出上不可区分时，
    这个守卫就是装饰品。扫描计数、样本文件数、解析出的条目数——至少要吐一个。
  - **优先"问权威源"而不是维护名单**。给 depguard 加一条 `deepseek_harness → ...`
    的映射就是硬编码，下一个名字对不上的依赖会复现同一个 bug。分布名与 import 名
    的对应关系就写在 site-packages 的 `.dist-info/RECORD` 里，去读它。
  - **同一类假阴性会连续出现**：本次 `git grep` 也犯了同一族错误——它默认**看不见
    未跟踪的新文件**，于是"刚写出来还没 add 的违规"隐形，rc=1 静默通过。加 `--untracked`。
  - **BOM 会制造假阳性**：PowerShell `Set-Content -Encoding UTF8` 写 BOM，
    一个"空"模式文件因此解析出 `\ufeff` 模式，而它匹配**每个文件的第一行**，
    报出 3 处假命中。读模式文件用 `utf-8-sig` 并 `lstrip("\ufeff")`。
- **Prevention**：
  - depguard 改成直接扫 site-packages 的 `*.dist-info`（`top_level.txt` + `RECORD`），
    路径可见、结果可断言；
  - 回归测试断言 `_installed_import_names()` **非空**——让"静默失效"立刻变红，
    而不是安静地什么都查不到；另有两条"守卫的守卫"：一条断言合法依赖不被双杀，
    一条断言真正未声明的 import 仍被报出（防止把守卫改成永远放行）。
  - 需求 6 的检查落成 `scripts/probes/probe_hardcoded_terms.py`：模式走文件不走 argv
    （PowerShell 传 CJK 会静默损坏）、`--untracked`、强制 UTF-8 剥 BOM、
    **打印待查文件数**、空模式/扫不到文件一律 exit 2。
- **Regression**：`tests/test_depguard.py::test_installed_import_names_resolves_real_distributions`
  /`::test_no_dependency_is_reported_both_undeclared_and_unused`/`::test_undeclared_import_still_reported`；
  `tests/test_probe_hardcoded_terms.py`（5 条，含植入违规必须被抓到、BOM-only 判空）。

## 模板（新增时复制）

```
## Lx — <一句话标题>

- **Problem**：
- **Root cause**：
- **Durable lesson**：
- **Prevention**：
- **Regression**：<测试/文件，或"暂无自动化，规则见本条">
```
