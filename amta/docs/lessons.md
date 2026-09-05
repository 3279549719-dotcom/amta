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
- **Regression**：内容级匹配逻辑见已归档 `scripts/archive/recall_score.py`（复用 `src/amta/metrics.py`）；纯函数单测在 `tests/test_shared_lib.py` 锁定。

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
- **Durable lesson**：DSH 下技能唯一事实源 = `.dsh/skills/<name>/SKILL.md`（git 正常跟踪）；CLAUDE.md / AGENTS.md 原生自动注入；hook 只走 git hooks（CC 生命周期 hook 桥是进程级 configPath + PreToolUse deny-only，会跨项目泄漏，不装）；CC 专有 frontmatter（如 `disable-model-invocation`）被 DSH 丢弃。→ 故包技能里标「仅用户触发」的（ask-matt/grill-me/to-spec/to-tickets 等 14 个）在 DSH 下 AI 仍可自动调，真限制只能靠 catalog 排除（不放 `.dsh/skills`），不能依赖该标记。
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

## L17 — llama-server prompt cache 误命中不同图像，本地 OCR 必须 cache_prompt:false

- **Problem**：连续请求两张不同 crop 时，后一张 0.1s "秒回"，但内容是前一张图的识别结果（错图复用）——实测 gt05 开缓存 0.1s 返回 'と'，关缓存 39s 返回真实推理 'しかし、'。
- **Root cause**：llama.cpp 的 prompt cache 按 token 序列匹配；PaddleOCR-VL mmproj 把所有图统一缩放处理，不同图可能产生相同 patch 网格 → token 序列相同 → 缓存误命中。
- **Durable lesson**：多模态 OCR 逐张请求必须带 `cache_prompt:false`，禁止依赖默认缓存；"秒回"在 OCR 评测里是错误信号（教训 L2 的变体：快不一定是真）。
- **Prevention**：`src/amta/ocr_engines.py` 的 send_chat 对本地引擎默认传 cache_prompt=False。
- **Regression**：tests/test_refactor_shared.py 校验本地引擎 payload 含 `cache_prompt:false`。

## L18 — 本地 OCR 性能：BF16 未量化 + 缺省参数 = 30s/张；Q8_0 + 参数优化 + baberu 快路径

- **Problem**：PaddleOCR-VL-For-Manga（BF16 未量化）每张 crop 20-40s，101 张约 1 小时，用户感知"非常慢"。
- **Root cause**：① 主模型 BF16 全精度（16BPW），CPU prompt eval 仅 6-8 tok/s；② llama-server 用默认参数（线程 4、无 batch/fa/KV 量化）；③ 逐张 HTTP 请求无法复用；④ 图像被统一缩放成 ~210-230 视觉 token，与输入尺寸无关（缩放输入图无效）。
- **Durable lesson**：CPU 推理先量化 Q8_0（实测 -30% prompt eval 耗时）；llama-server 加 `-t 8 -c 8192 -b 256 -ub 512 -fa on -ctk q8_0 -ctv q8_0 --mlock`；`--cache-reuse` 对多模态无效别加；换 baberu-OCR（ONNX）可 28 倍提速（1s/张，常规对白 CER 相当）。
- **Prevention**：start_llama_ocr.ps1 默认 Q8_0 + 优化参数；mmproj 保持 BF16（列 4304 非 32 倍数，Q8_0 量化会失败）。
- **Regression**：实测基线 BF16 31.3s/张 → Q8_0+参数 27.1s/张（真实推理）；baberu 1.05s/张。

## L19 — pytest Windows 尾部 PermissionError: pytest-current 是 teardown 噪音：exit 1 ≠ 失败；fastcheck 必须用 pytest 收集

- **Problem**：Windows 上跑 pytest，测试全部 PASS 但进程 exit 1（stderr 尾行 `PermissionError: pytest-current`）；曾有两个 subagent 据 exit code 误判实现失败，实际全绿。
- **Root cause**：pytest 的 tmp_path 清理（`cleanup_dead_symlinks`，含 symlink `pytest-current`）在 Windows 上抛 PermissionError，发生在所有测试结束后的 teardown 阶段，不影响测试结果但污染退出码并中断 stdout 缓冲（汇总行打不出）。另一层：本项目 `scripts/fastcheck.py` 原本用 `unittest discover` 只收集 `TestCase` 类，**静默跳过全部模块级 pytest 函数**（translate/workstate/ocr_run 的测试），报 "55 passed" 假信号。
- **Durable lesson**：① Windows 判断 pytest 结果看**汇总行**（`N passed`）不看 exit code；委派 subagent 跑验证前必须预教此噪音，否则绿测试被当红。② **`tests/` 一律 pytest 风格，fastcheck 必须用 pytest 收集**——unittest discover 只收 TestCase 会漏掉模块级测试却报 PASS（唯一真强制层失效）。③ Windows 无 tail，取输出尾部用 PowerShell `Select-Object -Last N`。
- **Prevention**：`scripts/fastcheck.py` `_test()` 改跑 `python -m pytest tests -q --basetemp <output/logs/.pytest-basetemp>`——`--basetemp` 指定显式目录后 pytest 不建 `pytest-current` symlink，正常输出汇总并退出 0；判定用正则 `(\d+) passed` 且无 `failed`。新测试一律 pytest 风格。
- **Regression**：`python scripts/fastcheck.py` 输出 `== [fastcheck] pytest: 82 passed ==`（含全部 pytest 测试，非 55）。[已自动化：fastcheck 已修]

## L20 — 数字前缀脚本无法按名 import：测试需 `_NN_name.py` 桥

- **Problem**：`scripts/03_translate.py` 不能 `from 03_translate import run`（标识符不能以数字开头），tests 复用 CLI 的 run() 报 ImportError。
- **Root cause**：数字前缀合法做文件名（可运行）但不合法做模块名（不可 import），Python 语法限制。
- **Durable lesson**：`scripts/` 数字前缀工位脚本凡需被测试 import，必须另建 `_NN_name.py` 桥（importlib.util 按文件路径加载真实脚本并转导出 run/main）；脚本本体保持可 `python scripts/NN_name.py` 直跑。
- **Prevention**：新建 00_run_all/01_detect/02_ocr/04_inpaint/05_typeset 时，凡测试需 import 的一律配桥。
- **Regression**：`tests/test_translate.py::test_cli_translate_uses_llm_and_writes_translation` 经 `_03_translate` 桥覆盖 CLI。[已自动化：测试锁桥用法，fastcheck 改跑 pytest 后强制执行]

## L21 — 日文残留检测判据只用假名范围：汉字 CJK 共用不可作残留依据

- **Problem**：残留检测若用汉字范围（U+4E00-9FFF）会把中文译文误判为"日文残留"（中日汉字共用码位，如"完全译文"会被命中汉字）。
- **Root cause**：CJK 统一汉字 U+4E00-U+9FFF 中日共用，无法区分中/日汉字；假名 U+3040-30FF 是日文独有特征。
- **Durable lesson**：`_JAPANESE` 只匹配假名 `[\u3040-\u30ff]`；代价是"纯汉字无假名的日文残留"（如 完全）检测不到，属可接受漏报——换汉字范围则中文译文全灭，代价不可接受。
- **Prevention**：任何"检测某语言残留"的正则用该语言**独有字符集**而非共享字符集；改 `src/amta/translate.py` 的 `_JAPANESE` 前先读本条。
- **Regression**：`test_japanese_residue_detects_kanji` 锁定「纯中文不误报 + 含假名日文报出」。[已自动化：测试已锁，fastcheck 改跑 pytest 后强制执行]

---

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

## L24 — prompt 模板含字面花括号会被 .format() 当占位符

- **Problem**：评审 prompt 模板里写 `accuracy:{1-5}` 等字面花括号，`.format(text=…, translation=…)` 直接抛 `KeyError('1-5')`——全量评审必崩。
- **Root cause**：str.format() 把 `{}` 当占位符；模板里想表达"评分范围/JSON 示例"的字面花括号未转义。
- **Durable lesson**：prompt 模板含字面花括号时禁止直接 .format()——双写 `{{ }}` 或改用 .replace()/命名占位符；任何"模板+format"组合，format 调用本身必须可测。
- **Prevention**：新增含 `{` 的 prompt 后先跑一次 format 冒烟（test_judge_prompt_format_safe 已锁定）。
- **Regression**：`tests/test_semantic_check.py::test_judge_prompt_format_safe`。[已自动化：是]

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

## L31 — koharu mask/inpaint 契约（探针 2026-08-27 定案，详见 ADR-020）

- **Problem**：put_mask 400（裸像素非 PNG）；lama-manga completed_with_errors（缺 BubbleMask）；export 422（无 renderer 节点）。
- **Root cause**：koharu REST 契约未文档化：mask 需 PNG 编码字节；lama-manga 需 segment+bubble 双 mask；inpainted 结果在 scene 节点 blob（WEBP）。
- **Durable lesson**：koharu inpaint 链路 = put_mask(PNG) ×2 → run_pipeline([lama-manga]) → fetch_inpainted(blob WEBP)；勿用 export_page 取 inpaint 结果。
- **Prevention**：客户端封装 run_inpaint/fetch_inpainted（已测）；ADR-020 固化。
- **Regression**：tests/test_koharu_inpaint.py 4 测。

## L32 — Windows subprocess text=True 用 locale 解码，中文输出必炸

- **Problem**：memory_recent 真仓库冒烟崩溃：git log 中文提交 → UnicodeDecodeError（reader thread）→ stdout=None → AttributeError。
- **Root cause**：subprocess.run(capture_output=True, text=True) 在 Windows 按 locale（gbk）解码子进程输出，而 git/Python 子进程输出是 utf-8。
- **Durable lesson**：Windows 下捕获含中文的子进程输出必须显式 `encoding="utf-8", errors="replace"`，并对 stdout 做 None 防护；CLI 面向 agent 管道消费时 stdout reconfigure(utf-8)（与 L27 同族）。
- **Prevention**：tools.do_recent 已修；新脚本照此模板（scripts/memory_*.py 四个均带 reconfigure）。
- **Regression**：tests/test_memory_inject.py 4 测（真子进程链路，含坏 JSON/空输入）。

## L33 — pytest 跨文件复用 fixture 勿 import，放 tests/conftest.py

- **Problem**：按计划在 test_memory_tools.py 里 `from tests.test_memory_estate import estate` 复用 fixture，ruff 报 F401/F811 共 9 错，pre-commit lint 门禁拦截提交。
- **Root cause**：ruff 把测试函数的同名参数视为对 import 名的 redefinition；跨文件 import fixture 本就是非常规用法。
- **Durable lesson**：跨测试文件共享 fixture 一律放 tests/conftest.py（pytest 自动发现，无需 import）；项目已配 pytest pythonpath=["src","."]。
- **Prevention**：estate fixture 已入 tests/conftest.py；新增 memory 测试直接声明 `estate: Path` 参数。
- **Regression**：fastcheck lint 步全绿（357 测试 + ruff）。

## L34 — 记忆检索要 hook push（UserPromptSubmit 注入），别只靠 MCP pull（工具自觉）

- **Problem**：用户问"detect 模型演进"，记忆字典查不到且我全程没用 MCP——MCP 工具未授权加载是表层，深因是 **pull 层靠执行纪律**：工具在列表里也要模型"记得去调"，不调就等于没有。CLAUDE.local.md 也只写 600 字摘要（loop_state+字典规则），lessons/ADR 全文没进上下文。
- **Root cause**：① MCP 是 pull 模型，触发权在模型行为，无法强制；② 项目记忆包预算 1.5KB 只装接续状态+字典规则（ADR-027 内容契约），坑库全文从不注入；③ 无任何 hook 在提问时按关键词检索记忆。
- **Durable lesson**：真强制层 = **UserPromptSubmit hook 按 prompt 关键词检索地产并 stdout 注入**（Claude Code 四个 stdout 注入例外事件之一，见 hooks 文档）；"遇错/决策前先查"这种 prompt 级纪律没 hook 就是空话。MCP/CLI 降级为按需打捞（pull），hook 管每轮推送（push）。
- **Prevention**：scripts/memory_autoinject.py（extract_tokens→do_grep→≤3KB stdout，恒 exit 0，无命中零输出）+ .claude/settings.json UserPromptSubmit 挂载；注入预算 ≤3KB（CC 实测 ~10K 落盘替换为 2KB 预览）。
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

## L38 — 移植模型推理：预处理/后处理必须与参考实现完全对齐（归一化范围 + 输出激活）

- **Problem**：本地 lama-manga 推理出现严重黑/白噪点，模型原始输出范围 [-307, 8755]（正常应在 [0,1]），clamp 后大部分像素被裁到极值形成噪点。
- **Root cause**：① 输入归一化用了 `[-1,1]`（`/127.5 - 1`），而 Koharu 参考实现用 `[0,1]`（`/255.0`）；② 模型输出缺少 sigmoid 激活函数——Koharu 的 FFCResNetGenerator 在 final_conv 后显式调用 `.sigmoid()`，而我们复制的模型定义用了 `add_out_act=False`，想当然认为不需要输出激活。
- **Durable lesson**：移植第三方模型推理时，**预处理（归一化范围、颜色空间、mask 二值化阈值）和后处理（输出激活函数、clamp 范围、颜色空间转换）必须与参考实现逐行对齐**；模型结构参数（如 `add_out_act`）不能想当然，必须核对参考实现的 forward 代码。模型输出范围异常（远超合理范围）是预处理/后处理不匹配的强信号。
- **Prevention**：移植模型前先读参考实现的完整 forward 流程（含预处理和后处理）；推理后立即检查输出范围是否在合理区间（如 sigmoid 输出应在 [0,1]，tanh 应在 [-1,1]）；异常范围必须先排查预处理/后处理，不要怀疑模型权重。
- **Regression**：`tests/test_local_lama_inpainter_manga.py` 4/4 通过（模型加载、输出形状、非正方形、默认类型）；5 页对比验证（page11-15）噪点完全消除。

## L39 — Inpainting 对上下文敏感：裁剪推理在复杂背景易产生方框，整页推理质量更稳定

- **Problem**：裁剪推理（padding=64，对每个文字框单独裁剪送模型）时，修复区域明显偏白，形成可见的白色方框（尤其在头发阴影、渐变背景区域）。
- **Root cause**：裁剪后模型只有局部上下文（裁剪区域内的像素），在背景复杂区域（渐变、网点、阴影）会把背景"猜"成纯白；整页推理时模型能看到全局上下文，背景修复更准确，与周围自然融合。Koharu 默认用 Crop 策略但 margin=128，且其 mask 生成方式不同，方框感不明显。
- **Durable lesson**：Inpainting 模型对上下文范围敏感；**裁剪推理在背景复杂区域（渐变、网点、阴影、非纯白背景）容易产生方框感**；整页推理（可适当缩小尺寸以控制速度）质量更稳定。如果必须用裁剪推理，padding/margin 要足够大（≥128），且验收时必须放大检查修复区域边缘。
- **Prevention**：背景复杂的漫画优先整页推理（缩小到 1024 宽平衡速度与质量）；裁剪推理仅用于背景简单的区域（纯白对话框内）；验收标准必须包含"放大检查修复区域无方框/噪点"，不能只看整页缩略图。
- **Regression**：5 页对比验证（page11-15），整页推理（19.7s/页）无方框，裁剪推理（7.3s/页）有方框；整页推理比 Baseline（152.5s/页）快 87%。

## L40 — Pillow ≥10 移除顶层 Resampling 常量（Image.NEAREST 等）：用 Image.Resampling.* 枚举

- **Problem**：`local_lama_inpainter.py` 调 `mask.resize(image.size, Image.NEAREST)` 在 Pillow 12 报 `AttributeError: module 'PIL.Image' has no attribute 'NEAREST'`（pyright: reportAttributeAccessIssue），Pillow 9.1 起顶层常量已弃用、10.0 移除。
- **Root cause**：Pillow 把插值常量从 `Image` 模块顶层迁到 `Image.Resampling` 枚举；旧顶层 `Image.NEAREST/BILINEAR/BICUBIC/LANCZOS/BOX/HAMMING` 全部移除。类型桩只认 `Image.Resampling.*`。
- **Durable lesson**：本项目 Pillow 版本无上限（venv 装最新），**插值参数一律写 `Image.Resampling.NEAREST` 等枚举，勿用顶层旧常量**；Pillow-heavy 代码（typeset/image 处理）新增 resize/thumbnail/transform 时直接照此写。
- **Prevention**：pyright 会拦（reportAttributeAccessIssue），但仅覆盖已声明的 image 处理路径——写新 Pillow 代码时默认用 `Image.Resampling.*`；遇到旧代码报此类错直接改名常量即可，行为等价。
- **Regression**：pyright src 0 errors；`tests/test_local_lama_inpainter_manga.py` 通过（resize 路径含在 local_lama_inpainter 单测中）。

## L41 — depguard 补声明已传递安装的依赖时，版本读 uv.lock 的公共版本，别抄 `__version__` 的本地构建标签（+cpu）

- **Problem**：lama 本地 inpainting 直 import torch/safetensors 但 pyproject 未声明 → depguard 7 项 [未声明]。补声明时若照 `import torch; torch.__version__`（实测 `2.14.0+cpu`）写 `torch==2.14.0+cpu`，uv 解析会失败——本地标签不在分发索引的公共版本上。
- **Root cause**：同一 wheel 有两个版本面：安装后元数据 `__version__` 带 PEP 440 本地构建标签（`+cpu`），而 uv.lock `[[package]] version = "2.14.0"` 只记公共版本、本地标签落在 wheel url 里。pyproject 的 `==` 约束按公共版本对分发解析，抄错一个面就锁不上。
- **Durable lesson**：给"已由他人传递安装、只为 depguard 显式化"的依赖补声明时，**精确版本一律从 `uv.lock` 的 `version =` 字段抄公共版本**（torch/safetensors 之类带 +cpu/+cu 标签的尤甚），别从 `pip freeze` / `__version__` 抄。直声明与传递解析出的版本一致，`uv lock` 才能无扰动通过。
- **Prevention**：改 pyproject 后必跑 `uv lock` 复核（退出 0 + `git diff uv.lock` 应只见 root 包 dependencies/requires-dist 增两行，无版本漂移），再跑 `py -3.13 scripts/depguard.py` 确认转绿。
- **Regression**：depguard 0 项 + `uv lock` clean（amta root 包新增 safetensors==0.8.0 / torch==2.14.0 两条直声明）。

## L42 — 仓库根上移（filter-repo 到父目录）后 core.hooksPath 相对值失效：pre-commit/pre-push 静默不跑

- **Problem**：把仓库根从 `amta/` 迁到父目录（filter-repo 给内容加 `amta/` 前缀）后，从 amta 提交时 pre-commit/pre-push 不再触发——fastcheck/ruff 提交门禁（L26）静默失效，无人察觉。
- **Root cause**：`.githooks` 物理位置仍在 `amta/.githooks`，没随根移动；而 `core.hooksPath=.githooks` 是相对值，git 按**运行 git 时的 cwd** 解析——实测 `git rev-parse --git-path hooks`：搬迁前 repo 根=amta、cwd=amta → `.githooks` 命中 `amta/.githooks`；搬迁后 repo 根=父目录、从 amta 跑 → 解析为 `../.githooks` = 父目录/.githooks（不存在）。hook 文件找不到时 git 不报错，直接跳过。
- **Durable lesson**：`core.hooksPath` 别用相对值——仓库根/内容前缀只要可能变，一律写**绝对路径**；hook 失效是静默的（缺文件不报错），唯一核对手段是 `git rev-parse --git-path hooks` 看解析结果是否落在真实存在的目录。同理，凡"仓库根在 cwd 之下"的假设（`.githooks`、`.venv`、`package.json` 向上查找）在根上移后都要复查。
- **Prevention**：已设 `git config core.hooksPath "E:/manga translator agent/amta/.githooks"`（绝对）；`scripts/install_hooks.ps1` 现在仍写相对 `.githooks`，应改成输出绝对路径；改完用 `git rev-parse --git-path hooks` 核对。Claude Code 启动目录仍是 `amta/`（根级无配置），勿从父目录启动。
- **Regression**：暂无自动化；规则见本条。

## L43 — Windows 下 claude CLI 是 claude.cmd/.ps1：Python subprocess 不能直接执行，必须经 cmd /c 走 PATHEXT

- **Problem**：scripts/review.py（L6 独立审核门）用 `subprocess.run(["claude", "-p", ...])` 报 WinError 2 找不到文件；同一命令在 PowerShell 里 `claude -p` 一切正常。
- **Root cause**：Windows 上 npm 装的 `claude` 实际是 `claude.cmd`（+ `claude.ps1`）脚本，PATH 里没有可执行的 `claude` 裸文件。PowerShell 走自己的命令解析能跑 .ps1/.cmd；Python subprocess 的 CreateProcess 不做 PATHEXT 解析、也不执行 .cmd/.ps1，所以裸名 "claude" 解析失败 → WinError 2。`shutil.which("claude")` 能返回 .CMD 路径（做存在性判定可用），但照此路径直接 Popen 仍失败。
- **Durable lesson**：Windows 下从 Python spawn 任何 npm/全局 CLI，先确认其真实形态（.exe / .cmd / .ps1）；若是 .cmd，用 `["cmd", "/c", "<name>", ...]` 调用（cmd 会按 PATHEXT 解析并正确转发 stdin/stdout）；大 prompt 走 stdin 管道（`subprocess.run(input=...)`）以绕开 Windows 命令行 ~32k 长度限制。
- **Prevention**：review.py 已用 `os.name == "nt"` 分支切 `cmd /c claude`；新写 spawn 外部 CLI 的脚本沿用此模式。
- **Regression**：`claude -p` 经 stdin 管道回 "OK"（实测，见 review.py L6 门）。

## L44 — 归档探针到 scripts/probes/（豁免但活着的目录）：ROOT 深度 + depguard 本地识别两处必改

- **Problem**：把 `scripts/exp_inpaint_speed.py` 等 6 个探针 `git mv` 到 `scripts/probes/` 后，脚本内部 `ROOT = Path(__file__).parent.parent` 全部少算一层（probes 比 scripts 深一级，仓库根需 `.parent.parent.parent`）；`tests/test_exp_p1_manga.py` 经 `sys.path.insert(..., "scripts")` import `exp_inpaint_speed` 也失效，需改指 `scripts/probes`。
- **Root cause**：① 探针用 `Path(__file__).resolve().parent` 锚定仓库根/兄弟脚本目录，目录下移一层后所有深度常量静默错位（不报错、只在真跑时找错路径）。② probes/ 与 archive/ 语义不同：archive/ 是"已死代码"（importer 硬死，depguard 报未声明 = 死代码侧写，L37），probes/ 是"豁免 lint 但活着的实验脚本"——测试仍合法 import 它，而 depguard `_is_local_module()` 只查 src/scripts/tests 活动目录，probes/ 下的模块名会被当第三方顶层名 → 报"未声明"假阳。
- **Durable lesson**：凡把 scripts 下脚本下移一层（scripts/X.py → scripts/probes/X.py）：① 全文搜 `Path(__file__)` 锚定的 ROOT/SCRIPT_DIR/SRC_DIR 深度常量与 `sys.path.insert`（深一层 = ROOT 多一个 `.parent`；要 import 的兄弟模块若留在 scripts/ 根，路径插 `SCRIPT_DIR.parent` 而非 `SCRIPT_DIR`）；② 若仍有测试/代码 import 它，去 `scripts/depguard.py::_is_local_module()` 加一条 `scripts/probes/` 检查（与 src/scripts/tests 并列），而不是清 importer——probes 模块不是死代码。
- **Prevention**：移动后跑 `py -3.13 scripts/fastcheck.py`（ruff/pyright 已豁免 probes，红债只在 depguard + 引用它的测试）；任何"归档进豁免目录"先分清是 archive/（清 importer）还是 probes/（depguard 补本地识别）。
- **Regression**：6 探针已在 scripts/probes/，depguard 已认 probes 为本地模块，fastcheck ALL PASS。[已自动化：fastcheck pytest 覆盖 test_exp_p1_manga import 通路]

## L45 — Claude Code ≥2.1.210 收紧 PreToolUse hook 输出 schema：legacy {"decision":...} 被拒 + guard 静默假死

- **Problem**：`.claude/settings.json` 的 PreToolUse hook（hook_pretooluse.py）用 legacy 输出 `{"decision":"allow/block",...}`。claude 2.1.220 对每次工具调用校验 hook 输出：Read/Grep 等非 git 工具报 "Hook JSON output validation failed — (root): Invalid input"（噪音），而 git commit/merge 的 fastcheck FAIL 分支**根本不拦**——AGENTS.md"fastcheck FAIL 阻止 commit"的 guard 从未真正生效。
- **Root cause**：Claude Code 升级到 `hookSpecificOutput` 包装 schema（决策在 `permissionDecision` 字段）；legacy 根级 `decision` 被 Ajv 严格校验整体拒绝，且**校验失败 = 非阻断 allow 兜底**（工具照跑，只记 hook 错误）。噪音显性于 Read/Grep（每工具必撞无效 allow 分支），git 类**静默**（deny 同样无效 → 拦不住）——bug 存在很久无人察觉。
- **Durable lesson**：hook 输出 schema 有版本断裂风险，症状是 "hook JSON output validation failed" + 工具仍能跑（allow 兜底）。凡"靠 hook 当 guard"：**allow 分支失效只产生噪音，deny/block 分支失效是静默的 guard 死亡**——schema 升级后必须复测 deny 真能拦。诊断：往 hook 喂 PreToolUse stdin 样例看输出形状，对照官方 schema。
- **Prevention**：hook_pretooluse.py 已改 `hookSpecificOutput` 包装（allow/deny + permissionDecisionReason），settings 加 `matcher: "Bash"` 收窄触发面（Read/Grep/Edit 不再触发）。新写 hook 一律用 hookSpecificOutput + matcher。
- **Regression**：`claude -p` 冒烟 Bash 命令无 hook error（allow 路径，2026-09-05）；deny 真拦 + ralph 无头下 deny 是否 end turn，待一次故意 fastcheck FAIL 的 commit 实测。

## 模板（新增时复制）

```
## Lx — <一句话标题>

- **Problem**：
- **Root cause**：
- **Durable lesson**：
- **Prevention**：
- **Regression**：<测试/文件，或"暂无自动化，规则见本条">
```
