# AMTA 项目进度（外部持久化记忆 / 交接文档）

> 本文件是**项目状态的唯一事实来源**，任何 AI（Claude Code / Cursor / DSH / 未来 agent）接手第一件事先读它。
> 与 hindsight（DSH 会话内记忆）互补：hindsight 是会话内快速召回，本文件是工具无关的交接文档。
> 每次完成任务后更新本节「当前状态」与「下一步」。

## 一句话

会话驱动漫画翻译自动化：**DSH 会话=导演，amta Python=确定性执行器，koharu v0.59.1 headless(:4000)=引擎**。第一里程碑：Benchmark A/B/C 定量钉死能力边界。

- **自动修复层落地（Patrick 裁决，commit 待填）**：scripts/repair_failed.py——FAILED 带评审意见喂回 DeepSeek 自修复（可带工具），机械护栏 + --only 重评审，max_rounds 上限，修不掉进 needs_review（导演只碰这里，日常修复全自动）：
  - 验收：判例库 5 条 fail 样本 → **4/5 直接自动修复**（2 条与手动修订一字不差，1 条更优），重评审全过
  - needs_review 真实触发 1 条（page_2_u08）：评审推翻 confirmed 术语「咔恰」→ 导演更新 work_state 术语表为「咔嗒」→ 自动修复 1 轮通过
  - **分工修正**：导演角色归位——机制设计/needs_review 终审/误报驳回/术语表校准，不再手动写译文（此前 ADR-016 把导演当修订工属错位，已纠正）
  - 测试 +6（134 全绿）

## 当前状态（2026-08-27，仓库卫生整改 + C4 架构文档 + audit 机器化）

- **仓库卫生整改（commit 8fb5364/0ab552e，feat/contract-hygiene）**：
  - **调研单一事实源**：research/ 归位（01-07 详报 + AGENTS.md + README 索引 + koharu-upstream/ 素材归档 52 文件）；docs/ 移除重复的 01-04（CLAUDE.md 渐进式加载表改指 research/）
  - **reference/ 整理**：第三方源码 clone → `_vendor/`；设计文档 → `design-docs/`；散落 misc/ 归档
  - **workspace/ 清理**：删 595 个 ws-* 空壳（work_dir() 每次调用残留）+ 27 个临时调试脚本；根因=init_workspace 随机 id
  - **v2 计划归位**：`docs/superpowers/plans/2026-08-27-front3-stages-v2.md`
- **audit 机器化卫生检查（scripts/audit.py + tests/test_audit_hygiene.py）**：workspace 空壳 ws-* 计数 / 跨目录重复文件检测 / 顶层散落检测，3 函数 6 测试
- **c4-codebase-architecture skill 钉版**：`.dsh/skills/c4-codebase-architecture/`（npx skills 安装 → 项目钉版）
- **AMTA C4 架构文档**：`docs/architecture/README.md`（Context/Container/Component 三视图 + Mermaid，c4 skill 生成）
- **vision 微探针（worktree 产物，未入库）**：`thinking:disabled` 被 vision-exp 接受且生效——B 组整页全量 1 次调用 2-3s（原 3 图/次 33-65s），零螺旋，转写质量 ≥ baberu；对照 HTML `probe_vision_report.html`
- **fastcheck 198 全绿**（+6 卫生检查测试）
- **深接口重构（codebase-design，commit 7ab8bc1/1fd92ef，feat/contract-hygiene）**：按深模块（小接口+大实现）拆解——
  - `chat_client.py` 新深模块：合并 `translate.text_chat`/`chat_with_tools` + `ocr_engines.send_chat` 的 OpenAI 兼容 HTTP/解析接缝，translate/ocr_engines 退化为薄适配器
  - `translate.py`（461→~254 行）拆出 `translate_tools.py`（工具机：TOOLS_SCHEMA/预算/execute/loop，repair_failed 独立复用）+ `guardrails.py`（机械护栏）；`_JAPANESE` 私有正则收敛为 `metrics.contains_japanese`（修 glossary→translate 泄漏耦合）
  - `koharu_client.py` 拆出 `koharu_blocks.py`（scene 节点→blocks 纯整形），KoharuClient 退化为纯 REST 适配器
  - 行为零变化：ruff/pyright/depguard 全绿，全套 204 passed
- **OCR VLM 审计（ADR-022 + 探针证据）**：ADR-022 两趟式 audit 定稿（Pass1 crop 批量存在性确认 + Pass2 整页枚举）从 feat/audit-v2 cherry-pick 进主树（commit f8a44d4/eb48456）；探针脚本/结果/HTML 证据归档 `research/08-ocr-vlm-audit-probe/`（原 worktree workspace，gitignore 产物已捞回）；**用户复核结论——全页通用 VLM 转写不可当真值源，仅作差异提示器，判定以本地 For-Manga 重 OCR + 机械规则为准**（详见 handoff-OCR-vlm-audit-顾问简报）

## 下一步

- **11-20 全量重跑完成（新 detector + ADR-019 契约 + deepseek-v4-flash）**：10 页零失败（run 043db62d2c5c），canon **108 条**（手工真值 97，宁多勿漏 +11），**category 覆盖 108/108（100%）**，sub_tier 41 条；语义评审 8/10 页 pass_rate 1.0（页 14 0.889 自动修复、页 13 有 2 inconclusive 待导演复核）；对比旧跑检出翻倍（页 11 3→9、页 14 3→17）。旧产物备份 `output/backup/2026-08-27-pre-rerun-11-20/`。
- **Stage 4 inpaint 完成（ADR-020 + 探针定案）**：`inpaint_strategy`（category→fill_white/inpaint/skip）+ `04_inpaint` 工位 + `KoharuClient.run_inpaint/fetch_inpainted`；探针结论——lama-manga 需 **segment+bubble 双 mask（PNG 编码）**，~20s（400×600 CPU），结果经 scene 节点 blob 取回为 **WEBP**（export 走不通）。
- **Stage 5 typeset 完成（ADR-021）**：自研 Pillow 引擎（`fonts` 4 级映射 / `typeset_engine` 方向+折行+避头尾+字号二分 / `typeset_render` 横排居中+竖排单列+白描边）+ `05_typeset` 工位（coverage/overflow 机械检查）；**overlay_text 强制竖排漏洞修复落地**；bbox 经 `node_id` 关联 detection（零契约改动）。
- **页 11 端到端冒烟通过**：04 fill_white 9 + 05 rendered 9/9 coverage_complete，竖排 2 条（u06 52px/u07 27px）、感叹号→粗体映射、字号 20-52 自适应全生效；`final/page_10_final.png` 已出。
- **fastcheck 192 全绿**（+28 测试）；lessons L28-L31 新增。
- ⚠️ **渲染质量待修**（Patrick 初审）：字号跨框不一致、部分框内译文绘制/擦除观感问题——下一轮先修 renderer 再全量渲染。

## 下一步

0. **渲染质量修复**（字号一致性、译文绘制观感、overlay 竖排锚点）——Patrick 已指出的问题
1. **11-20 全量 `--with-inpaint --with-typeset`**（lama 整页 1-3min/页，~30-50min），验证 sfx/overlay 真实擦除路径 + 产出全彩成品
2. **Stage 6 QA 工位**（coverage 反压闭环 + VLM 终审，蓝图 Phase 4）
3. **合并 main + push**（feat/contract-hygiene 14 commits；push 前 fetch→rebase 铁律）
4. **工单微信通知**（handoff 遗留）
5. 翻译结果对照报告已发邮箱：`output/reports/translation_check_11_20.zip`

## 当前状态（2026-08-26，/simplify 化简重构：分支 refactor/simplify 未合并未推送）

- **/simplify 式化简重构（独立 worktree，分支 refactor/simplify，commit f819cd8，17 文件 +102/-151，fastcheck ALL PASS / 121 passed，零依赖不变，未 push）**：
  - 去重：translate/glossary 的 norm/levenshtein 收敛到 `amta.metrics`；工具循环提取 `translate.run_tool_loop()` 供 repair_failed 共用；`_page_key` 提升为 `runner.page_key` 默认值；base64 data-URI / stdio 样板 / read_json 收敛到 `amta.paths`/`amta.*`
  - 死代码删除：`geometry.fit_block`、`pipeline.OCR_STEPS`（全仓零引用）
  - CLI 接口与行为语义全部保持；评估过但跳过（PLAUSIBLE，理由见 ADR-012 修订注）：02_ocr crop 合并、`_judge_vision` 与 `build_payload` 合并；`_NN_xxx.py` 桥按 L20 保留
  - ⚠️ 未合并回 main、未 push——合并前需重跑 fastcheck；交接 correctness 线索两条（见「下一步」9/10）

## 当前状态（2026-08-26 三笔：工单机制落地 + /finish 收尾，feat/translate-tools-fc 合并 master）

- **工单机制（ADR-017，借鉴 CMMS）**：src/amta/tickets.py TicketStore——状态机 open→in_progress→resolved/rejected，JSON 文件即状态（state_dir/tickets.json）；repair_failed 达上限自动开单（classify_kind 关键词分类 term_conflict/false_positive/hard_case）；**归档闭环**：resolve/reject 时处理结论自动回写判例库（维修手册逻辑，导演处置即沉淀判例）。测试 +5。
- **/finish 收尾（cycle-close + finisher subagent）**：CLAUDE.md 翻译通道/工具面/坑速查更新（预取→真 FC、导演不手写译文、tickets.py）；ADR-014/016 加修订标注（导演角色归位、Tools 预取→真 FC）；ADR-017 新建 + README 索引补 016/017；lessons L24-L27（prompt 花括号 format 坑/可复现基线/Python313 环境/OpenClaw 脱敏坑）；pre-commit 优先 Python3.13；package.json test 改 pytest（修 unittest discover 漏收集陷阱）；JUDGE_PROMPT format 冒烟测试。fastcheck 140 全绿。
- 本分支 5 commits（a44f7e4 工具 / a9bc36c 闭环 / d78ed74 自动修复 / +工单机制 / +收尾），合并回 main 并推送。

## 当前状态（2026-08-26 二笔：真 function calling + 导演闭环端到端验证，fastcheck 全绿）

- **Tools 真实现（Patrick 裁决，feat/translate-tools-fc 分支，commit a44f7e4）**：预取注入 → 真 function calling：
  - chat_with_tools（OpenAI 兼容 tools + tool_calls 解析）+ TOOLS_SCHEMA（lookup_term / get_context）+ execute_tool（本地 JSON 读）
  - 工具循环：模型请求 → 执行 → 回传 → 继续，直到纯文本；预算真拦截（TERM_BUDGET=10 / GET_CONTEXT_BUDGET=3 超限拒绝服务，MAX_TOOL_ROUNDS=6 防死循环）
  - Context 最小披露：角色/术语/前页不再预塞（_prompt_parts 精简），模型按需调工具；open_questions 保留
  - vision 工具第一版未接线（VISION_BUDGET=2 预留），看图职责归评审③
- **86 条真实数据重跑（function calling 版）**：	ranslation_ocr_paddle_fc.json 86/86 全译出、机械护栏零错；semantic_check_fc.json 首轮 79/86（94.0%）
- **修复隐藏 bug**：	ranslate_semantic_check.py JUDGE_PROMPT 里 {1-5} 花括号被 .format() 当占位符 → 全量评审必崩（此前 83/86 是在旧 prompt 版本上跑的）；已修复并重跑
- **导演闭环端到端验证通过（round 1）**：5 FAILED（page_0_u11 生硬 / page_2_u08 拟声词 / page_5_u02 漏语气 / page_6_u00 か误译 / page_9_u01 主语）→ 导演修订 
evisions_fc_round1.json → pply_revisions --only 重评审 **5/5 全过** → 合并后 **86/86 全清（pass_rate 1.0）**；page_7_u05 评审误报（语境补全当编造）导演驳回维持原译；page_4_u08 重试通过
- **术语演进闭环**：merge_suggestions 19 条候选 → work_state（カチャ 跨页一致自动升 confirmed，其余 candidate）
- **判例库 4 → 10 条**：沉淀 round1 五条修订样本 + 两条误报/自动修复样本
- 环境注意：fastcheck 必须用 Python313 全局解释器（PATH 默认 python 是 AutoClaw 的，无 pytest/ruff；pre-commit hook 同样受影响，提交时需把 Python313 放 PATH 前）

## 当前状态（2026-08-26，最后一笔：Translate Harness 对齐 GPT 设计落地，fastcheck 全绿）

- **Translate Harness 对齐 GPT 设计（2026-08-26，ADR-016，commit 见 feat/translate-harness）**：以 GPT 设计为基准补齐 translate 层，不再"以现有实现放行"：
  - **Guardrails 补全**：新增 pre-translate **Input schema gate**（`src/amta/canon_schema.py` `validate_canon`，03 前置校验）+ **Glossary Validator**（`src/amta/glossary.py` `check_glossary`，Knowledge guardrail：confirmed 术语残留日文/非 canon 中文写法→违例）。
  - **Eval 四维**：③ 升级**四维评分**（accuracy/fluency/consistency/readability 1~5，合并同次 VLM 调用，`parse_verdict_with_scores` + `avg_scores`，**不当闸门**=导演排序/监控）；**判例库** `testsets/case_law.json`（4 实测样本，替代参考译文 GT）。
  - **Tools 恢复**：`build_tools_context`（lookup/get_context 预取）+ Contract（`TERM_BUDGET=10`、`VISION_BUDGET=2`），03 注入 system 层。
  - **State 四层**：work_state 加 **observed** 层（observed/confirmed/inferred/candidate，ADR-016）；`scripts/merge_suggestions.py` 跨页一致→confirmed 自动升、导演可降级。
  - **导演语义 loop**：`scripts/apply_revisions.py`（修订落盘 + `--only` 重评审闭环，budget=1 轮→needs_review）+ on-failure 结构化记录（`record_failure`→failure_log.json）。
  - **验收阈值**：③ ≥90% + 导演清 FAILED。fastcheck 全绿（含新增 test_canon_schema/glossary/merge_suggestions/apply_revisions）。
  - **注意**：本分支尚未合并回 main；`.env` 误粘贴 GitHub token 待轮换（交接事项，未处理）。

- **翻译工位首次真实运行 + 语义护栏③ 落地（2026-08-26）**：
  - **首次真实调用 DeepSeek**：修 `.env` `CHAT_MODEL=deepseek-v4-pro-0813`（无效，L22）→ 实测 `deepseek-v4-pro`；探针"月の都→月之都"通。
  - **端到端真跑**：源文本不信任 VLM GT，改用 **PaddleOCR-VL-For-Manga 真实 OCR 输出**（`preds86_for_manga.json`，86 框/10 页）造 canon → `03_translate.py` 真实跑 → **86/86 全译出，机械护栏全过**（结构/残留零错），角色名（探女/永琳/依姬/丰姬/辉夜）一致。产物 `output/data/canon_text_ocr_paddle.json` / `translation_ocr_paddle.json`。
  - **语义护栏③ 实现并全量运行**：`scripts/translate_semantic_check.py`（VLM 逐 region 粗筛评审，默认 `deepseek-v4-flash-vision-exp`，空响应重试，L23）+ `tests/test_semantic_check.py`（5 测试）。86 评审 **83 过 / 3 需修订 / 通过率 96.5%**（`page_9_u01` 主语错真抓对；`page_0_u07` 漏"只有一点"可辩；`page_2_u05` 加"但"疑似误报）。产物 `output/data/semantic_check_final.json`。
  - **③ 能力边界实测**：粗筛+随机——抓粗错、漏语境润色（"污秽即是心"两模型判通过，导演才抓出）、误报风格；通过率=粗筛层指标，FAILED=导演过目队列。
  - **待办**：导演审 3 FAILED + "污秽即是心"；术语演进（角色名→work_state，本次空 work_state 未锻炼）；定通过率验收阈值。

- **Matt Pocock 技能包已钉入（2026-08-25，commit 702e452）**：ask-matt 路由器 + 25 技能从 `~/.agents/skills` 逐字节复制进 `.dsh/skills` git 钉版（ADR-009）；`~/.agents/skills` 当只读上游，`npx skills update` 后需重复制同步。CLAUDE.md 渐进式加载已加 ask-matt 行。无阻塞；用户 WIP（audit/dependency-guard）未动。

- **03_translate 工位已实现（2026-08-25，ADR-014 落地）**：
  - `src/amta/translate.py`（264 行纯库）：`text_chat` + `get_chat_config`（.env CHAT_*）+ 三借鉴机制（`extract_relevant_terms` / `translate_with_retry` 分层拆分 / `TranslationCache` 源文 hash）+ `build_translation_prompt`（Context 分层）+ 机械护栏（region_id 一一对应 + 假名残留）+ `SuggestionsExtractor`
  - `scripts/03_translate.py`（薄 CLI：canon_text.json → translation.json + suggestions.json）+ `scripts/_03_translate.py`（测试桥，数字前缀无法 import，L20）+ `tests/test_translate.py`（11 测试）
  - ✅ **接线完成（2026-08-25）**：`build_translation_prompt` 拆分出 `_prompt_parts`/`_current_block` 复用；`translate_with_retry` 新增 `work_state`/`prev_pages`/`open_questions` 参数并接入——Knowledge（work_state 术语/角色）、History（前 3 页译文）、Uncertainty（open_questions）现真进 LLM 消息；分批拆分时 System/前缀只算一次、每批只换当前块。`03_translate.py` 传入 work_state + open_questions。回归测试 2 条（context-wiring + split 复用）。
  - ⚠️ **验证口径修复**：fastcheck 原用 unittest discover 只收 TestCase（55），漏跑全部 pytest 测试；已改跑 `pytest --basetemp` 全量 82 测试（L19/L20）。
- **翻译工位架构定稿（2026-08-24，ADR-014）**：grill 定案 7 条，产物结构 ADR-013 的落地形态：
  - **翻译层 = 脚本直调 DeepSeek API**（`.env` CHAT_BASE_URL/CHAT_MODEL/CHAT_API_KEY 现成，`https://api.deepseek.com`）→ **修订锁定决策 #5**（弃 koharu 内 llm 引擎，not-ready 悬空）
  - **Harness**：Context+Guardrails+Loop 做，Tools 砍（脚本直读文件，不搞 function calling）
  - **护栏双层**：机械层（结构错/残留错/region_id 一一对应，纯代码，类比 fastcheck/hook）+ 语义层（手搓 VLM 脚本验证译文质量，DASHSCOPE 通道）
  - **工位边界**：translate 只管文本质量；detect/inpaint/typeset 错误归各自工位未来 mechanical check
  - **Loop 分层**：脚本机械 loop（schema 错自动重译 1 次）+ 导演语义 loop（VLM 拦出 → FAILED 附证据 → DSH 会话修订）
  - **术语演进**：suggestions.json 中间层 + 导演自动合并（零人工卡点，可追溯）
  - **工位清单**：00_run_all（文件存在=跳过）→ 01_detect → 02_ocr(For-Manga) → 03_translate(DeepSeek) → 04_inpaint → 05_typeset
  - state/ 四文件：touhou_knowledge / work_state / open_questions（ADR-013）+ suggestions.json（新增）
- **产物结构 rebaseline（2026-08-24，ADR-013）**：按 reference（touhou_doujin_first_principles_dikw.html）第一性原理/DIKW，把产物从"逐页 benchmark 报表"重定为**每本同人志一个工作区**（Touhou 同人志缩域）：
  - `workspace/<work_id>/{raw, artifacts, state}`；state/ 三文件：`touhou_knowledge.json`（共享 canon prior）+ `work_state.json`（当前本子逐页生长）+ `open_questions.json`（未决问题）
  - 三层上下文分离：canon prior ≠ 本子真相（同人志可改关系/语气，当前页证据 ＞ work_state ＞ canon ＞ 猜测）；work_state 逐页生长，首版不做 DB/Vector/Event Graph/Memory Service
  - Evidence tracking：条目带 `status ∈ {confirmed,inferred,candidate}` + source 页码；新证据可修正旧状态；单页可运行
  - 代码：`src/amta/workstate.py`（workspace 布局 + 空 schema + init/update/validate）+ `tests/test_workstate.py`（8 测试）；fastcheck ALL PASS（53）
  - **OCR 评测底座不变**：For-Manga 定案（ADR-011）、指标口径（ADR-010）仍是事实，output/ 旧评测数据保留供迁移
  - 翻译层归属已定（ADR-014）：脚本直调 DeepSeek API，修订决策 #5
- **OCR 引擎三选一对比完成（2026-08-24，86 个 detector 对齐 GT 框）**：锚点=detector 并集 crop 图（全尺寸可靠坐标）+ GT 语义内容（字符重合度≥0.6 对齐，86/101；15 个未检出=page_5 设定页检测不足，单独计数不混入 OCR 指标，ADR-011）：
  - **For-Manga（现役·漫画微调）ALL CER 0.062 / EM 0.779**：dialogue_in 0.001/0.974、sfx 0.161/0.643、bg_text 0.0/1.0 → **保持现役，无需换 1.6**
  - **PaddleOCR-VL-1.6（官方原版）ALL CER 0.113 / EM 0.721**：对白类与 For-Manga 持平，但 **sfx 0.458 明显落后**
  - **qwen-vl-ocr（云端通用）ALL CER 0.266 / EM 0.465**：垫底，且与 GT 同源（Qwen）有虚高风险，仅外部参考
  - 报告：`output/reports/ocr_engine_compare.html`；决策：ADR-011
- **评测坐标源修正（L16）**：OCR 评测必须用 detector 对齐框，勿用 GT 缩略 bbox（VLM 缩略坐标裁图全空白）或单引擎框（manga-ocr 每页仅 5-9 框，55/101）；页码注意 0/1 基偏移。

- **Harness 迁移完成（2026-08-23）**：9 技能从 `.claude/skills/` 迁到 `.dsh/skills/`（DSH 原生技能根，`npx dsh-movein` 迁移 + `git mv` 定唯一事实源）；新增 **finisher**（收尾知识归类委派 subagent）与 **researcher**（外部调研委派 subagent）技能；判断链改**五路分流**（lesson → CLAUDE.md / skill / ADR / progress / test·hook，test/lint/hook 为唯一真强制层）；修复 **#1401 frontmatter bug**（cycle-close / background-monitoring description 未引号 `": "` 被 DSH 静默丢弃）；hook 层维持 git hooks（CC 生命周期 hook 桥 = 进程级 configPath + PreToolUse deny-only，会跨项目泄漏，不装）。机制决策见 **ADR-009**。
- **第二轮 OCR 测评完成（本会话）**：框外对白 OCR 换引擎——**PaddleOCR-VL-For-Manga**（本地 GGUF + 独立 llama-server b10582，端口 8118）全量 126 crops 实测：
  - **QA 修正后（现行 norm 去标点口径 + unmatched 归因）：ALL CER 0.316→0.121 / EM 0.516→0.770；99 行（排除 27 unmatched）CER 0.035 / EM 0.869**（For-Manga 真实水平；dialogue_out EM 0.857）；48 行重复计数（union 去重漏碎片框，L12）与 25 行不可靠 GT（per-crop 标注，L13）已定案，json 待重生成（L14）
  - dialogue_in：CER 0.16 → 0.103；sfx：1.0 → 0.15；bg_text：0.727 → 0.038；ALL：0.462 → 0.316
  - 证据：`output/data/benchmark_b_paddle_manga.json`（126 rows 全量）+ `output/reports/benchmark_b_paddle_manga_report.html`（报表）
- **koharu paddle 引擎坏因定案**：内置 llama.cpp b8935 太旧，mmproj/MTMD 投影初始化失败（`completed_with_errors`，ocr 全空）；同 GGUF 用 b10582 秒加载、OCR 正常 → koharu 的 paddle/mit48px OCR 引擎**不可用，弃用**（ADR-008）。
- **通用 VLM 竖排日语系统性差**（arXiv 2511.15059 + qwen-vl-ocr 实测词序错乱）→ 远程 API 基座 OCR 路线放弃（无需注入 SiliconFlow key）；GLM-OCR-Manga-LoRA 出局（无 API、需 GPU≥4GB）。
- **context7 接入**：`scripts/context7.py`（`npm run ctx7:search` / `ctx7:ctx`），读 `.env` 的 `CONTEXT7_API_KEY`，已实测通过（dogfood 查了 SiliconFlow docs）。
- 快速检查 `npm run fastcheck`（ruff+pyright+16 tests）通过。

- 工程脚手架已就位并推送（commit `854e170`、`119df6e`、`95ab73c`，origin/main 已同步）。
- CLAUDE.md v2 = 渐进式加载模型（核心事实+坑，~2k tokens）；AGENTS.md = 薄指针（避免双份漂移）。两者 DSH 均自动注入。
- 3 个 skill 已建：`benchmark` / `koharu-drive` / `verify`（.dsh/skills/，DSH 原生技能根，进 skill catalog 按需加载）。
- `src/koharu_client.py`（16 方法）+ `src/pipeline.py`（引擎 DAG 常量）+ smoke_test **PASS**。
- koharu headless 当前在 :4000 运行（--headless --cpu）。
- **Benchmark A 已实现**（`scripts/benchmark.py` 两阶段：emit crops+manifest → ingest 标注算指标；synthetic 自测 + 链路实测通过）。
- **预筛完成**：16 页原文 × 4 detector 全跑通 → **160 crops + `output/data/label_manifest.json`**（无缺失，16 页全覆盖，每页 2-19 框）。
- **Benchmark A 完成**（VLM oracle 标注 160 框 + ingest）：
  - **detection_precision = 0.963**（160 候选，6 个非文字假框）
  - 四类分布：dialogue_in 61 / dialogue_out 53 / sfx 23 / bg_text 17
  - 置信度：127 high + 33 medium，无 low
  - 6 个 FP 均为真实非文字（`!?` 反应符号、纯画面）——detector 假框少，框外字真问题在 recall（detector 均漏区域），需后续抽查
  - 产出 `output/data/benchmark_a.json`、`output/data/labels_a.json`（可复现）
- **Benchmark A recall 完成**（内容级，单翼 1-10 页 101 GT 区域）：
  - **总体 recall = 0.98**（101 检出 99）
  - 分维度：dialogue_in 1.0 / dialogue_out 1.0 / sfx 0.941 / bg_text 0.909
  - 漏检 2 处：英文服装字 "Welcome Hall!"(bg_text) + 1 个 SFX（拟声字）
  - **方法修正**：describe_image 整页坐标不可靠（裁剪验证空白）→ 改用**内容级匹配**（VLM 识别 detector 并集框内容 vs GT 内容清单，字符重合度≥0.6）
  - 产出 `output/data/recall_gt.json`、`recall_detections.json`、`recall_ocr.json`、`recall_result.json`
- **Benchmark B OCR 完成**（manga-ocr，单翼 1-10 页，路2 detector+OCR）：
  - 总体 CER 0.462 / EM 0.426（101 区域）
  - **框内对白最优**：CER 0.16 / EM 0.795；框外对白中：CER 0.45 / EM 0.27
  - **SFX 拟声词全盲**：CER 1.0 / EM 0——manga-ocr 对 SFX 输出为空（竖排/艺术字/特效字认不出）
  - **环境限制**：paddle-ocr-vl-1.5 失败（completed_with_errors，text=null）、mit48px-ocr 输出乱码/空——CPU-only 上仅 manga-ocr 可用
  - 产出 `output/data/benchmark_b.json`、`ocr_result.json`、`scripts/ocr_detect.py`、`ocr_score.py`
  - 修复 koharu_client.wait_operation 卡死 bug（未识别 completed_with_errors 状态）
- git 凭据已修：host 级 `credential.github.com.helper="!gh auth git-credential"` 绕开 GCM 弹窗（否则每次 git 操作弹账户选择框）。

## 里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| 0 | 脚手架 / CLAUDE.md / skills / smoke | ✅ 完成并推送 |
| 1 | Benchmark A/B/C（检测 recall / OCR CER / inpaint 评分） | 🔄 C 待做（B 已出数） |
| 1a | 预筛 16 页测试集（四 detector → 160 crops + manifest） | ✅ 完成 |
| 1b | Benchmark A precision（VLM oracle 标注 160 框） | ✅ 完成（precision 0.963） |
| 1c | Benchmark A recall（单翼 1-10 页，内容级匹配） | ✅ 完成（recall 0.98） |
| 1d | Benchmark B OCR（manga-ocr CER 0.462；Baberu SFX CER 0.181） | ✅ 完成 |
| 2 | Repair Loop / Vision QA 嵌入 pipeline | ⏳ |
| 2b | Story Memory + prompt.py + vqa() + scene 翻译 | ⏳ |
| 3 | GitHub Actions 自动触发验证循环 | ⏳ 待验证循环稳定后 |

## 已锁定决策（grill 定案，勿改）

1. 基线 = 钉 **koharu v0.59.1** headless（REST+MCP+像素 mask）；上游 0.77.5 起删 headless/HTTP/MCP，升级即失去自动化面。
2. Agent 形态 = **会话驱动**（DSH 会话=单 LLM Agent 导演；Python=确定性工具层；describe_image=Vision QA 眼睛）。
3. 第一里程碑 = **Benchmark A/B/C**（VLM 当 oracle，**零人工全量标注**——用户明确拒绝人工标注）。
4. Vision QA 通道 = **describe_image**（用户禁了 ModLens，注入 .env）。
5. 翻译通道 = **脚本直调 DeepSeek API**（`.env` CHAT_*，ADR-014；**修订原 #5**：弃 koharu 内 `llm` 引擎——not-ready 悬空）。
6. 场景级翻译**不在 MVP**（Story Memory + 前页上下文优先；Benchmark D 再定）。
7. 成功标准 = **benchmark 数据 + 失败可定位到具体模块**。
8. skills = 3 个（benchmark/koharu-drive/verify）。
9. 接口全表下沉到 koharu-drive skill；CLAUDE.md 只留一行。
10. package.json 不包 git/gh（原子操作用原生；发布流程在 verify skill）。

## 验证循环设计（新锁定，来自 Claude Code 官方博客）

- 模式 = **分层**：Benchmark A/B/C=独立（我自调度，非手动跑）+ Repair Loop=嵌入 pipeline + verify=链式发布。
- 前端/playwright：**本项目永远不需要**（判卷是 describe_image 看静态图，无浏览器自动化）。
- **调度权在我**：改了 detector/OCR/prompt 后我自记 todo 跑 benchmark，用户不碰终端。
- 稳定后才上 GitHub Actions（每次 push/PR 自动跑同一验证 skill）。
- **Superpowers 分工（2026-08-24 定案）**：流程模板用 Superpowers（brainstorming → writing-plans → subagent-driven-development/executing-plans → verification，计划落 `docs/superpowers/plans/`）；任务收尾仍走我们的 /finish（cycle-close，五路分流知识晋升 Superpowers 没有）。两套互补，不互相替代。

## 关键坑速查（完整经验见 docs/lessons.md）

- 坑/经验的唯一归属 = `docs/lessons.md`；CLAUDE.md 只留一行指针。
- NO_PROXY=127.0.0.1,localhost（Clash 破坏 localhost）· .ps1 含中文必须 UTF-8 带 BOM · ctd_seg 只细化已有框 · patch 后必须重跑 koharu-renderer · workers>1 崩。

## 测试集现状

- 真实源图（**未翻译原文**）已在机器上：`D:\我的汉化\output\灵梦和妹红\process\NN\page.jpg`（NN=11..26，共 16 页，2243×3465）。
- 单翼停留之地 process/ 无 page.jpg（只有 rendered.png=已翻译），**不可做 benchmark 源图**。
- 原图不入库（testsets/pages/ 已 gitignore）；ground_truth/、results/ JSON 入库。

## 下一步

0. ~~重生成 benchmark_b json（GT 对齐 + 去重 + norm 重算）~~ → **已由 86 框 OCR 评测替代完成**（ADR-011）
1. ~~实现 03_translate.py + 接线 Context 分层~~ → **已完成（2026-08-25）**：`translate_with_retry` 接入 `build_translation_prompt`（Knowledge/History/Uncertainty/Current 真进 LLM 消息），`03_translate.py` 传 work_state + open_questions。
2. ~~00_run_all.py 编排器 + 01_detect/02_ocr 接入 per-work 契约~~ → **已完成（2026-08-26，ADR-018）**：00_run_all + 01_detect + 02_ocr + pipeline_log + 03 --trace，1 页冒烟通过（断点续跑/step tracing/LLM 观测全部验证）。
3. **04_inpaint / 05_typeset 工位**（koharu lama-manga + renderer 验证）+ 各自 mechanical check（mask 区域像素变化/译文区渲染）。
4. ~~VLM 语义护栏脚本~~ + ~~导演语义 loop~~ + ~~术语演进~~ + ~~验收阈值~~ → **已完成（2026-08-26，ADR-016）**：③ 四维评分 + 判例库 `testsets/case_law.json`；`scripts/apply_revisions.py`（导演修订+重评审闭环）+ `scripts/merge_suggestions.py`（suggestions→work_state 合并，跨页一致自动升）；验收阈值 = ③ ≥90% + 导演清 FAILED。**导演终审闭环已端到端验证（2026-08-26）**：5 FAILED 修订→5/5 过→86/86 清；自动修复层 + 工单机制（ADR-017）落地。
5. **最终验收**：final.png 整体 VLM/导演检查（日文残留/溢出/可读性）。
6. Benchmark C（mask + inpainting 评分）与 Benchmark A 框外漏检抽查（15 个未检出 GT 框，检测覆盖缺口）随工位推进穿插。
7. 结果回填本节「当前状态」并推送。
8. **handoff 2026-08-26（下一 AI 接手）**：① 1-10 页评测产物转正为流水线布局（artifacts/translation.json + state 配套），从 11 页起 00_run_all 续翻——验证 state 跨页累积 + get_context 前页回溯（这是上一轮拍板的方案 B）；② 工单微信通知；③ 02 OCR 提速（单页 156s CPU，41 页约 2h+）；④ vision 工具接线（VISION_BUDGET 已留，千问 3.5 omni 备选）；⑤ 角色 lookup 返回 aliases 小修补；⑥ 04_inpaint/05_typeset 工位。
9. **修 tickets.py 判例回写字段错标**（`src/amta/tickets.py` `_append_case_law` L129 `"ticket_id": region_id`）：case-law 条目的 `ticket_id` 字段实际存 region_id，真实工单 id 从未传入（resolve/reject 只传 region_id，`_append_case_law` 签名也没有 ticket_id 参数）→ 要么签名加 ticket_id 传入真实值，要么删该字段（region_id 已冗余）；修后加测试锁「ticket_id 与真实工单一致」，防将来按 ticket_id 追溯判例时静默取到 region_id。
10. **修 recall_score.py 输出字段语义错标**（`scripts/recall_score.py` L52-53 `"best_det": best`）：字段名暗示"最佳检出文本"，实际存数值 match_score（同行另有 `match_score` 字段）→ 改名 `best_match_score` 或改存匹配到的 det 文本；改前核对 recall_result.json 下游消费方（报告生成）避免静默断链。

## 2026-08-28 进展快照（front3 + 分支治理）

**Stage 3 五页验证（11-15，eval_stage3.py）**
- 69/69 框全部有译文，日文残留 0、术语违例 0；双引擎差异大 36 处由 LLM 一次性裁决；耗时 31-72s/页（14 页 292s，重试/拆分机制触发）。
- 核心 case 全命中：14 页「では豊ちゃん、輝夜様にこの羽根を見せに行ってきます」（VLM 误读サダメ，LLM 正确选 baberu）；15 页「弟子だからね＋落ち着きなさい」大小字合并自然；12 页 baberu 误读「落菜」被 VLM「蓬莱」纠正。报告：`artifacts/eval_stage3_report.html`（已发邮箱）。
- **Stage 3 链路缺口修复（0852d20）**：`validate_canon` 接受双引擎格式（baberu_text/vlm_text）、`check_glossary`/`SuggestionsExtractor` 回退 baberu_text；5 个 TDD 测试，52 项全绿。
- **暴露问题**：14 页 5 对重复检测框（两组 detector 各一组）未被合并——IoA<0.75 无嵌套标，LLM 逐框直译。「去重」是当前 Stage 3 最大短板。

**Stage 3 去重实验（方案A/B，当晚 Patrick 建）**
- `feat/stage3-dedup-tools`（0fba562）：方案A 纯文本规划去重——`stage3_planner.py`（plan 阶段 mark_invalid/mark_duplicate）+ 翻译过滤继承，测试 309 行。
- `feat/stage3-dedup-tools-vision`（27e29fb）：方案B VLM 整页图规划——`stage3_planner_vision.py`（deepseek-v4-flash-vision-exp 判重复/无效，非区域转写）。worktree 已切到此分支。
- 两分支均已推 origin。两方案对比验证待跑。

**整页 VLM 残骸清理（Patrick 确认死路）**
- ADR-022 探针遗留：主 checkout `scripts/probe_audit.py`（未跟踪一次性探针）已删；`.worktrees/feat-audit-v2/`（17MB 残留目录，非 git worktree）已核验无独有内容（调研报告在 git 历史 0ab552e 可恢复）后送回收站。
- 现行 Stage 2 的 VLM = contact sheet 逐格转写（每框裁剪图），与整页读取无关，验证有效（蓬莱纠正），保留。

**分支治理（Patrick 指令执行）**
- 方案B（含方案A commit）推 origin ✓；agent-loop-stage1 主 checkout WIP 全量 commit（06_page_judge 页级质检工具等）✓；删除已合并分支 translate-harness / translate-tools-fc / refactor-ocr-speed ✓。
- 遗留：`contained_in` 保留决策已定（保留）；但 Stage 3 prompt 实际未传 bbox（ADR-023 规格与实现不符，待补）；main 落后 50+ commit，front3 定稿后合并。


**Agent 记忆机制四层闭环（feature/agent-memory，2026-08-30，ADR-025）**
- 读取端机械化：CLAUDE.md 问题域启发式表 + SessionStart hook 注入（startup ≤1.5KB / compact ≤0.5KB，恒 exit 0）+ memory_grep/read/index/recent/status 五工具（条目级语义返回）+ memory_lint 五规则进 fastcheck；冷启动探针协议 docs/memory-probe.md（真实 CC 会话探针留 audit 期执行）。
- 结构：src/amta/memory/ 包 = estate（解析）/ tools（检索）/ lint（检查）+ project_memory（旧 memory.py 并入，re-export 兼容）；scripts/memory_*.py 六薄 CLI；tests 新增 23 测。
- 收尾：research 幽灵路径清零；decisions 索引补 022/023/025 并归一化 019-021/024；图解资产对齐五工具族；fastcheck 357 全绿（基线 334）。分支待整合。
