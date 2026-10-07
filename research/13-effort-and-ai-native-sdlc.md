# Effort 分档 与 AI-native SDLC —— Stage 3 操作规范素材

> 抓取日期：2026-10-06
> 来源 1：[Using Claude Code: Spending your effort](https://claude.dev/blog/spending-your-effort/)（Thariq Shihipar，2026-09-25）— 一手全文抓取成功（`.md` 等价地址）
> 来源 2：[The AI-Native SDLC playbook](https://claude.com/blog/the-ai-native-sdlc-playbook)（Louis Claxton / Anthropic Applied AI，2026-08-21）— 站点直抓被导航截断；**正文全文来自镜像** [ai-wiki 原文存档](https://raw.githubusercontent.com/tim-kaa-py/ai-wiki/main/sources/articles/2026-08-21_anthropic_the-ai-native-sdlc-playbook.md)，并由 [同仓摘要](https://raw.githubusercontent.com/tim-kaa-py/ai-wiki/main/summaries/2026-08-21_anthropic_the-ai-native-sdlc-playbook.md) 补足被截断段落
> 用途：给 AMTA Stage 3（会话=导演，`src/amta`=确定性工具层）写操作规范。本文只做提取，不改生产代码。

---

## A. Spending your effort —— effort 是可调度的"验证+自主判断"预算

**核心机制**：effort 不改变模型是否认真做事，改变的是它**自己花多少算力去验证、去处理边界情况、去替你行使判断**。作者原话：effort 是"modulating how much verification and edgecase testing Claude did and how much of its own judgement it used"。

| 档 | 适用任务类型 | 作者原话锚点 |
|---|---|---|
| low | 你本人要在环里、要快速拿到可迭代雏形：头脑风暴、草图、容易的改动 | "quick responses that are in the loop" |
| medium | 常规软件工程主力档，如新功能实现 | "most of my regular software engineering work" |
| high | 验证重要或边界情况多：褐地代码库里的 bug 修复、代码审查、安全 | "verification is important or there are edge cases" |
| max | 要它全自主端到端解决难题并自我验证：从零建造+验证、审计关键软件的安全漏洞 | "operate fully autonomously" |

**换档的硬判据（作者给的，不是感觉）**：
- **隐藏边界条件多 ⇒ 该升档**。这是他读 Terminal-Bench 3.0 的"主要 takeaway"："higher effort is best for tasks with lots of hidden edge cases"。同理适用于"生产要求高的复杂任务：性能优化、安全审查"。
- **升档救不了方向错误**。"increasing effort tends to reduce failures due to missing edgecases, but does not fix when the model has the wrong approach"。低档失败要分因：方案错（升档无用，要人去改方向）vs 边界漏（升档有效）。
- **规格越细，档位差异越小**。"given this spec, the models behaved much more similarly"——细 spec 是**拉平档位差距的手段**，和升档可互相替代。
- **低档会让模型替你多做假设**，高档则花更多时间自我审查。作者对设计类任务"prefer using low effort to understand Claude's vision"：先低价看方向。

**作者本人的循环（这是 Stage 3 的模板）**：
1. 给它一个 spec，并**让它反过来 interview 我**，补齐我漏掉的细节；
2. **low effort 实现**；
3. **我 review**，确认它抓住了要点，需要时继续 low effort 迭代；
4. **high effort 验证与测试**。

**升档到底多做了什么（从失败→成功的同题对比看，可当"验证证据清单"）**：
- `html-js-filter`（XSS 清洗器）：low 只写一遍 + 一个手写页面测；xhigh 会**对抗性审查自己的初稿、去读已安装 parser 的源码查 bug、跑标准 XSS 测试套件、最后写随机文档 fuzzer**。
- `mvcc-lsm-compaction`：low 先改代码再构建/跑复现器；xhigh **先复现崩溃、写随机化测试对照参考实现、并确认自己的测试在半成品修复上会失败**。
- `cli-2ph-simplex`：high 会**用独立暴力求解器对拍、给大输入计时、撞上超时/崩溃后重做搜索**。
- `gsea-proteomics`：high 会**试两种数据预处理、发现显著结果清单变了、追查原因后才选**。

> **对 AMTA 意味着什么**：effort 是 Stage 3 会话可调的旋钮，不是全局默认值。把"隐藏边界条件多不多"当成选档的唯一判据：路由决策（VLM 段落 vs hayai+MITS 正路）、inpaint 残留、typeset 断行溢出、OCR 漏检这类**边界密集**环节用 high；一次新的页面级尝试、先要个能看的雏形用 low/medium。最省钱的组合是**细 spec + 低档实现**，而不是粗 spec + 高档硬刚——所以 Stage 3 开工前先让会话就问"这次 spec 够细到能拉平档位吗"。

> **对 AMTA 意味着什么**：换档判据写成产物判据，别写成"感觉不对就升档"。低档产出若被判定为**方案错**（如版面分析路线选错），升档无用，必须回到人改方向；只有在**证据齐全但漏了边界**时（如 inpaint 在小字号 SFX 上残留）才升档重跑。把每次失败**归因到"方案错/边界漏"两类**，这是换档的唯一依据。

---

## B. AI-native SDLC —— 六段产物链 + 人只看门口的检查点

**总前提（"Code is no longer the bottleneck"）**：agent 让 Build 塌缩到小时级，而 plan / review·test / deploy 仍是人的速度。于是瓶颈迁移到 Build 两侧；老控制（逐行人工 review）在 agent 写大部分 diff 后**不可行**；治理成本上升（例外还走周会）。

**每段一个产物，下一段读它**（作者称"committed artifact"，并明确"the chain of commits is also the audit trail"）：

| 段 | 输入 | 输出产物 | 人做什么 | agent 做什么 |
|---|---|---|---|---|
| 1 Plan | 想法 / 工单 / Stage 6 告警 | `intent.md`（问题·期望结果·影响面·约束·待决问题） | **产品负责人 review 并纠正**，accept/reject 记为 merge 或关闭 | 像分析师一样追问，起草 proto-spec |
| 2 Design | 已接受的 `intent.md` | `spec.md`（+ 标记出的 concern 区域） | **人 review 但不写**；concern 路由给 policy owner；**人决定是否进 Build** | 依 skills（品牌/安全/合规/UX）生成 spec 并 flag 冲突 |
| 3 Build | 已批准的 `spec.md` | `plan.md`（改哪些文件·顺序·风险·证明）→ diff + tests | **人审 plan，改到"没见过对话的人也能照着实现"**；实现偏离时同 commit 改 `plan.md` | plan mode 只读先给方案；受 hook 约束执行 |
| 4 Test | `plan.md` + 代码 | 测试/构建/截图证据；CI eval 结果 | **人只看 intent 与风险**（机器证据已附） | 全程自检；配置变更跑 eval |
| 5 Deploy | PR | PR + review findings（review 是审计记录） | **代码所有者批准**；hooks 的 ask 门由具名者放行 | 双向 review（收 + 给）、按 @ 提及推修复 |
| 6 Maintain | 控制带越界 / 工单 / 频道消息 | 新的 `intent.md`（诊断+证据） | **服务负责人分诊**：现在修 / 排期 / 驳回 | 无人触发即运行，诊断后只写回 intent.md |

**人的位置被明确切成两类**：①**看方向**的检查点——intent 接受（Plan）、spec 签核并决定是否进 Build（Design）、plan 接受（Build 的 plan mode 让 agent 在方案被接受前**根本无法改文件**）；②**批准/放行**的门——PR 的 code owner 批准、release authorization。**没有一处是人去逐行读 diff**；人的注意力"concentrates at the gates, reviewing what the agent flagged"。

**门禁设计（这是全文最硬的工程部分）**：
- **advisory vs deterministic 分层**：skill "is a control, though an advisory one… nothing forces a session to comply"；hook 是它后面的确定层——"The skill makes violations rare and the hook makes them close to impossible"。凡"必须永远成立"的策略，背后必须有 hook 或一轮 PR 复核。
- **hook 三态 allow / ask / block**；**ask（人工批准）型 hook 归 Deploy，不归 Build**——Build 阶段每步都弹窗会把一个人卡在**所有并行会话**的关键路径上。
- **review**：`REVIEW.md` 明文定义 pass（bugs / security / compliance 对 spec.md+plan.md）、什么算 Important 而非 Nit、nit 上限、豁免（生成文件与 CI 已覆盖的）。**finding 既不批准也不阻断**，分支保护仍要求人类批准。
- **eval 的门禁对象是"agent 的配置"，不是产品**：从近期真实工作抽 20~50 个任务（prompt + 可接受的判定：测试通过 / lint 干净 / 行为不变 / 策略遵守），在 CI 上**按计划跑 + 任何 `CLAUDE.md`、`skills`、`hooks` 变更都跑**，pass rate 掉了的配置改动要人复核才准合。每次生产事故、每个修掉的漏洞类都**永久加一条 eval**。
- **确定性检测 + 模型只在越界后被召唤**：控制带用滚动窗口均值/标准差 + Western Electric 规则，脚本版本化且**单测**、"detection stays entirely deterministic, with no model involved"；`bands.yaml` 分档 1σ 只记日志、2σ 只读诊断、3σ 才可**提议**（开 PR 进门禁 / 触发预先批准的 runbook）。
- **职责分离**："The agent that wrote the code has no way to approve it."
- **并行度上限是人**："The practical ceiling is how many streams one person can review properly."
- **采纳顺序 ≠ 阶段顺序**：无前置的 play（intent 捕获、CLAUDE.md、skills、feedback loop、hooks-as-gates）可先做；CI/CD 自动化**必须**在 PR review 门与生产 hook 之后——"the gates must exist before automation accelerates anything through them"。

> **对 AMTA 意味着什么**：把 Stage 3 的"产物链"落到本项目已有的物上——`plan`/`spec` 形态 = 会话里写明改动面与证明方式；`diff + tests` = `scripts/` 与 `tests/` 的真实改动；**证据 = `gen_report.py` 的前后对比图 + `artifact.py query` 的产物位置 + `fastcheck.py` 的输出**。换档与验收的判据应该是这些**产物读得出来**的事实，而不是"看起来好了"。人的检查点收敛为两处：**方向**（这次要动哪一层：引擎路由 / 渲染 / 报告）与**批准**（视觉验收），其余交给上面这套证据。

> **对 AMTA 意味着什么**：本项目已有一层真强制（pre-commit `fastcheck --quick` → `state.py finish` 全量含 pytest）。套用"advisory vs deterministic"：写在 `CLAUDE.md` / skill 里的规范是 advisory，**只有 test/lint/hook 是强制层**。所以 Stage 3 新增的每条操作规范都要问一句"它不触发时会怎样"，若答案不可接受，就必须同时给出一条确定性的探针或测试，否则它只是散文。

> **对 AMTA 意味着什么**：`REVIEW.md` 的形状可以直接借来当**报告/验收的 pass 清单**：AMTA 天然有三类 pass——① 翻译正确性（对白语义/语气/术语一致）② 版面保真（是否遮挡、断行、气泡溢出）③ 上游契约（detect 框、OCR 文本、inpaint 干净度）。把"什么算 Important、什么算 Nit、什么不报（如纯风格）"写死在规范里，避免每次验收标准漂移。**且 finding 只报告不批准**——审查者（含 subagent）不得顺手改产物。

---

## C. 两篇怎么对齐：同一条链条，两种叫法

| 环节 | spending effort 的叫法 | AI-native SDLC 的叫法 | 硬性建议 / 谁跑 |
|---|---|---|---|
| 讨论定 spec | 给它 spec 并**让它 interview 我**（loop 第 1 步） | Plan 让 Claude 像分析师一样追问 → `intent.md`；Design 出 `spec.md` | **人 review 但不写 spec**；接受 spec 是进 Build 的开关 |
| 低档实现 | **low effort 实现**（loop 第 2 步） | Build：plan mode 给 `plan.md`，接受后才实现 | agent 跑；**plan 被接受前 agent 不能改文件** |
| 人看方向 | **我 review** 它是否抓住了要点（loop 第 3 步） | Build 审 plan / PR review 看 intent 与风险 | **人来判断方向**，不逐行读 |
| 高档验证 | **high effort 验证与测试**（loop 第 4 步） | Test：给 agent 自检回路 + verifier subagent；Deploy 门 | **反馈回路跑在任务全程**；**verifier 用全新上下文、只报告不修**——"so the verdict is not colored by the assumptions that produced the code" |
| 换档/门禁判据 | 隐藏边界条件多 → 升档；方案错 → 升档无用 | 控制带 σ 分档；配置变更由 eval pass rate 门禁 | 两篇都同意：**判据要是可测量的**（边界数 / pass rate / σ） |

**两条对齐出的硬结论**：
1. **"验证必须由谁跑"有明确答案**：执行/验证由 agent 跑，但**判定"方向对不对"的人在门前**，且**验证要用独立上下文**（verifier subagent / code owner 复核），不能由写代码的那个上下文自证。两篇都反对"作者自批"。
2. **换档的判据是"边界条件密度"与"配置是否变了"，不是难度感**。SDLC 侧的等价物是：改 `CLAUDE.md`/skills/hooks 就**必须**跑 eval——**配置变了 = 必须验证**，这与 effort 侧"边界密集 = 必须升档"是同一逻辑。

> **对 AMTA 意味着什么**：Stage 3 的循环可以照抄四步：**会话先 interview 用户（补齐 VLM 页清单、术语表、字体/排版约束）→ low/medium 跑一版可看产物 → 用户看报告定方向 → 验证阶段用 high + 独立上下文复核边界**。两个可操作的落地物：① 把"验收 agent"做成只读的 verifier（只报告，不改 `src/amta`、不改 canon）；② 把"改了路由/规范/阈值"定义为**必须重跑相应视觉回归**的事件，对齐 eval 门禁的思路。

> **对 AMTA 意味着什么**：SDLC 的"artifact chain"给了一条本项目可用的**闭环留痕**要求——每次验收决定（接受/驳回、为什么）应当落在可追溯的位置（报告 + 记忆 `lessons.md`/ADR），使"谁要求了什么、产出了什么、谁批的"可回读。**事故/坏例 → 加一条回归测试或 lesson**，等价于"每个事故变成永久 eval"，这是 Stage 3 防止同一坑重踩的机制，而不是靠人记得。

---

## D. 来源可信度边界（不编造）

- **来源 1**：`https://claude.dev/blog/spending-your-effort.md` 一次抓取成功，**全文完整**；A 节所有引号均出自该全文。文中交互图（effort 曲线、失败归因图、分类收益图）是交互式组件，**文本版未含其原始数据**，故本文只引用作者对图的口头结论，不引用具体数值结论以外的推测（数值如 36.6%→65.7% 仅作背景，未当作操作判据）。
- **来源 2**：站点直抓截断在导航。**六段正文（Plan→Maintain）、REVIEW.md、hooks、managed settings、evals、bands.yaml 均取自镜像全文**，未见内容缺失；镜像本身是第三方（GitHub ai-wiki）的抓取存档，`extraction_method: web-fetch`，**属二手转录**——所有引号已尽量保留英文原文以便核对，但**未与 Anthropic 原页逐字校对**。摘要文件（同仓 `summaries/`）仅用于补全被截断的过渡段，其中带**评价性判断**的部分（如"vendor voice""prescriptive, not measured""production-gate hook 的 substring 匹配很弱"）是**第三方的批判性解读，不是原文主张**，本文未把其当作结论使用。
- **未取得**：Firecrawl 抓取（账号额度耗尽，报 `Insufficient credits`）、`r.jina.ai` 代理（`fetch failed`）两个通道均失败；上述内容已由镜像覆盖，**未因此留下已知空白**。
- **对 AMTA 的映射依据**：AMTA 侧只使用了仓库文档中已写明的原则（会话=导演、三入口、证据=报告/artifact/fastcheck、机械护栏分层），**未读取 `src/amta` 实现代码**，故 B/C 节的 AMTA 落地建议是"按现有宪法该怎么接"的设计建议，不是对现有代码行为的断言。
