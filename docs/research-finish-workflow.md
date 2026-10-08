# AMTA 收尾流程调研报告：业界成熟做法 + 可直接抄的 Template

> 调研日期：2026-10-08
> 范围：只读公开资料，未改动 AMTA 本地任何文件
> 触发背景：`state.py finish` 把"列清单 + 跑全量门禁（6~31 分钟）+ 自动 git add/commit"三件事耦合，已引发两起事故：
> - (a) `git add -A` 把未打算提交的 1MB 图片一起 commit 了
> - (b) 被一个"改动前就已红"的旧测试拦下，白烧 20 分钟
>
> 一句话总览：**业界没有任何主流 agentic 工具是把这三件事糊成一条 `finish` 命令的。** 共识是物理隔离 + 显式枚举 + 三段式解耦。

---

## TL;DR

| 你的痛点 | 第一性解法（不是加两行注释） | 抄谁 |
|---|---|---|
| 三件事糊在一条 `finish` | 拆成 **gate（跑门禁，红就 exit 非零）+ ship（交互式 `git add -p` + commit）** 两条命令 | 社区 gate/ship 双命令模式 + Cline shadow repo |
| `git add -A` 带走 1MB 图片 | staging 按 **session 实际触碰文件白名单** 显式枚举，物理上禁止 `git add -A` | Aider 的 file-list staging + Claude PreToolUse hook |
| 被"本来就红"的旧测试白烧 20 分钟 | **testmon 只跑受影响测试 + baseline red list 开始记、结束 diff**，做两次集合运算 | pytest-testmon + agenticskillset baseline-red recipe |
| OCR 非确定性 stage 被重跑污染下游 | DVC `freeze` 语义 + Snakemake `--omit-from`/`--forcerun` 动词 | DVC + Snakemake + makedown SPEC |
| `font_size >= 30` 一改就红 | **契约断言（文本 bbox ⊂ 气泡多边形）为主 + perceptual diff 兜底** | render-qa 范式 + visualcheck/pixelmatch |

---

## 问题 1：AI Agent 编码工作流里的"收尾/提交"命令怎么设计？

### 结论 1.1 — Cline 的 Shadow Git 仓库：agent 自动 commit 不进主历史（事故 a 的物理隔离解）

Cline 官方明确说：

> Cline maintains a **shadow Git repository separate from your project's actual Git history**. After each tool use, Cline commits the current state of your files to this shadow repo. **Your main Git repository stays untouched.**

agent 每做一个 tool call 就把工作树快照 commit 到旁路 shadow repo，用户的 `git log` 完全干净；用户通过 UI Compare/Restore 看 diff，确认 OK 后**自己手动**在主仓库 `git add` + `git commit`。

对 AMTA 的映射：把 agent 工作过程中的快照丢到 `workspace/<work-id>/.shadow-git/`（已在 ignored 范围里），`finish` 只做 diff 预览，真正 `git add`/`git commit` 由人显式触发。

- 来源：https://docs.cline.bot/core-workflows/checkpoints

### 结论 1.2 — Goose 官方文档直接教你 block 掉 agent 的 `git commit`（最硬哲学）

Block（Square/Cash App 母公司）开源的 Goose，官方 environment variables 文档给了一段可直接抄的 shell 函数：

```bash
if [[ -n "$GOOSE_TERMINAL" ]]; then
  git() {
    if [[ "$1" == "commit" ]]; then
      echo "❌ BLOCKED: git commit is not allowed when run by goose"
      return 1
    fi
    command git "$@"
  }
fi
```

哲学：**agent 可以 `git add`、`git diff`、`git status`，但 `git commit` 这一步必须由人来做。** Agent 写代码，人决定什么时候进历史。

- 来源：https://goose-docs.ai/docs/guides/environment-variables/

### 结论 1.3 — Aider 的 commit 哲学：按文件白名单 staging + dirty-commits 先收编你的脏改动

Aider 是最早把 git 深度集成进 AI coding 的工具，四条规则值得逐条抄：

1. **Atomic commit**：每改完一批文件立刻独立 commit，message 由 weak-model 读 diff 后生成。
2. **Dirty-commits（默认开）**：启动时如果仓库 dirty，**先把 preexisting changes 单独收编成一个 "Pre-existing changes" commit**，然后才开始改你的代码——aider 的改动和你的改动永不混在一个 commit。
3. **只 add 它自己编辑过的文件**：内部维护 session 打开/编辑过的文件列表，**从不 `git add -A`**。这就是事故 (a) 的正解——不是靠 .gitignore，而是 staging 时按白名单枚举。
4. **`/diff`、`/undo`、`/commit` 三个独立命令**，`/commit` 不跑任何测试。

对应 flags：`--auto-commits`、`--dirty-commits`、`--no-git`。

对 AMTA 的映射：`finish:preview`（列 changeset + 跑 gate）和 `finish:ship`（只 add 这次 session 动过的文件白名单 + commit）拆成两条命令；staging 列表从 orchestrator 实际触碰过的文件里收集，不是 `git add -A`。

- 来源：https://aider.chat/docs/git.html
- 来源：https://aider.chat/docs/config/options

### 结论 1.4 — Claude Code 官方 hooks：PreToolUse 拦截 `Bash(git *)`，Stop hook 防止谎报 done

Anthropic 官方 hooks guide 给了两段直接可用的配置：

**PreToolUse + `if: "Bash(git *)"`**：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{
          "type": "command",
          "if": "Bash(git *)",
          "command": "\"$CLAUDE_PROJECT_DIR\"/.claude/hooks/check-git-policy.sh"
        }]
      }
    ]
  }
}
```

`check-git-policy.sh` 可以：命中 `git add -A` / `git add .` → exit 2 拒绝；命中 `git commit` → 检查 staged 里有没有 `workspace/`、`*.png`、`*.jpg` 黑名单路径，有就 block。PreToolUse exit 2 = block，stderr 喂回给 Claude 自己修正。

**Stop hook** 防谎报 done：官方明确说 **Stop hook 只适合跑 fast suite**，慢测试属于 CI——这正是你们"6~31 分钟门禁"事故 (b) 的反面教材。

**Anthropic 官方推的不是一条命令，而是 skill chain**：`/code-review → /simplify → /verify → (commit)`，每步独立可调用。

- 来源：https://code.claude.com/docs/en/hooks-guide
- 来源：https://claude.com/blog/building-verification-loops-in-claude-code-with-skills

### 结论 1.5 — 社区 gate / ship 双命令模式：三段式 CLI 的标准答案

| 别名 | 跑什么 | 什么时候用 |
|---|---|---|
| `gate` | 跑 pytest，红就 exit 非零 | 交给下一步之前 |
| `ship` | `gate` 绿了之后，**交互式 `git add -p` + `git commit`** | 测试绿了、准备 commit 时 |

三段式：列 changeset（dry-run 预览）→ 跑 gate（红了就停，不 commit）→ 交互式 staging + commit（`git add -p` 逐 hunk 选，不是 `git add -A`）。

另一个可抄的 AGENTS.md 模板：gastownhall/gastown 的 `Session Completion` 把 "file issues / run gates / git push" 列成三步，不是一条命令糊完。

- 来源：https://pravindurgani.github.io/claude-code-multipane-iterm2/
- 来源：https://github.com/gastownhall/gastown/blob/main/AGENTS.md

**反面教材（别抄）**：OpenHands resolver 直接 `git add -A` 是因为跑在隔离 Docker sandbox 里，你们本地不能照搬。

---

## 问题 2：怎么区分"这次改动引入的红" vs "仓库本来就有的红"？

### 结论 2.1 — Test Impact Analysis：只跑"被我改动影响到的测试"，10 秒定位

不要跑全量看谁红，反过来：先算"我的改动会影响哪些测试"，只跑那一小撮。没在影响集合里却红的，**大概率是本来就红的**。

| 工具 | 怎么知道"谁被影响" | 安装 / 命令 |
|---|---|---|
| **pytest-testmon**（最流行） | 基于 coverage 细粒度追踪：跑过一次后把"哪个测试覆盖哪些源码行/方法"存进 `.testmondata`，下次只重跑受影响测试，方法级精度 | `uv pip install pytest-testmon`；`pytest --testmon`（首次建库） |
| **pytest-impacted** | 纯静态：`git diff` → AST(astroid) 抽 import 关系 → NetworkX 依赖图传到 test 模块。宁可误报不可漏报 | `uv pip install pytest-impacted`；`pytest --impacted --impacted-module=src` |

testmon 跑完只列"与本次 diff 相关的测试"。一个旧测试红了——而它根本不在 testmon 选出的影响集合里——它就是仓库存量红，与你无关，`finish` 不该因此拦下你。

- 来源：https://github.com/tarpas/pytest-testmon
- 来源：https://pypi.org/project/pytest-impacted/0.19.0/

### 结论 2.2 — 维护一份 baseline 红名单：开始记一次、结束 diff（AI agent 场景的成熟 recipe）

业界（agentic QA 圈）已有完整 recipe。核心是两份清单：

1. **`known-issues.md`**：人工维护、已接受不修的存量红。
2. **`baseline-failures-latest.txt`**：在干净 main 跑一次，把失败测试名 dump 成文件提交进仓库；每次 session/PR 结束时和它做差集。

**四类分类法则**（直接写成 skill prompt）：

- `NEW_FAILURE`：不在 baseline、不在 known-issues → **这次 PR 引入的，才该拦**
- `PRE_EXISTING`：在 baseline 里 → 不是我引入的，不阻塞
- `KNOWN_ISSUE`：在 known-issues.md 里 → 已接受
- `UNCERTAIN`：上下文不足 → 再查

AMTA 本地落地：session **开始**先跑一次快速 smoke 把当前红快照存到 `workspace/<work-id>/baseline-red.txt`；**finish** 时只对"快照里没有的新红"负责。

- 来源：https://agenticskillset.org/en/topics/continuous-feedback-autonomous-execution-and-regression-analysis/
- 来源：https://github.com/jMerta/codex-skills/blob/main/ci-fix/SKILL.md

### 结论 2.3 — 必须跑全量时用 pytest-split 按历史耗时压时间

```bash
uv pip install pytest-split
pytest --store-durations --durations-path=.test_durations   # 先存一次，提交进仓库
pytest --splits 4 --group 1 --durations-path=.test_durations # 之后按组跑
```

`.test_durations` 记录每个测试历史耗时，greedy bin-packing 保证最慢那块尽量短。和 testmon 互补：日常用 testmon 只跑受影响；全量门禁用 split 压墙钟。

- 来源：https://pypi.org/project/pytest-split/0.2.2/

### 结论 2.4 — flaky / 环境干扰：rerunfailures + 连跑 3 次对比

```bash
uv pip install pytest-rerunfailures
@pytest.mark.flaky(reruns=5, reruns_delay=2)
# 或命令行：pytest --reruns 5 --reruns-delay 1
```

更进一步，agentic 做法是**连跑 3 次对比**：结果在 3 次里变来变去的就是 flaky，三次都红的才是真坏。把 flaky 和环境问题（端口占用、别的进程在跑、临时文件残留、缺凭据）单独列为一类，**不算回归**。

- 来源：https://pytest-rerunfailures.readthedocs.io/latest/mark.html

### 直接回答：怎么在 10 秒内知道"这个红是我引入的还是本来就红的"？

**不跑全量，做两次集合运算：**

1. **算影响集合 I**（testmon，秒级）：`I = 我的 diff 影响到的测试`
2. **读 baseline 红名单 B**（session 开始快照 + `baseline-failures-latest.txt` + `known-issues.md`）
3. 对每个 finish 时的红测试 t：
   - `t ∈ B` → **PRE_EXISTING，不阻塞**
   - `t ∉ B 且 t ∈ I` → **NEW_FAILURE，必须处理**
   - `t ∉ B 且 t ∉ I` → UNCERTAIN（testmon 漏报？flaky？），rerun 一次再定

"被一个旧测试拦下白烧 20 分钟"在第一步就被 baseline 名单挡掉——它根本不该出现在阻塞列表里。

---

## 问题 3：非确定性阶段的流水线怎么"锁上游"？

### 结论 3.1 — 最像 `--freeze-upstream` 的现成设计：DVC 的 `dvc freeze`（直接抄 flag 语义）

DVC 在 `dvc.yaml` 里给每个 stage 一个 `frozen: true` 字段，CLI 也有 `dvc freeze <stage>`。官方原话：

> Stage reproduction will not regenerate outputs of frozen stages, **even if their dependencies have changed, and even if `--force` is used**. Freezing a stage is useful to avoid syncing data from the top of its pipeline, and **keep iterating on the last (non-frozen) stages only**.

配套机制：

- `dvc.lock`：state file，记录每个 stage 输出的 content hash（输出是 content-addressed）
- `dvc commit`：**强制把工作区里已改动的输出"签收"进 lock**——对应"人工确认 OCR 重跑结果后，冻结新基线"
- `always_changed: true`（与 frozen 相反）：声明某 stage 永远视为脏，对应 OCR 这种"每次都可能变"的 stage
- `dvc checkout`：按 lock 把工作区输出恢复到冻结版本

对 AMTA：锁住 detect/ocr 两个非确定性 stage，之后无论怎么改 translate/inpaint/typeset，都不会回头碰 OCR 产物。

- 来源：https://doc.dvc.org/command-reference/freeze
- 来源：https://doc.dvc.org/user-guide/project-structure/dvcyaml-files

### 结论 3.2 — "downstream-only / render-only" 的 CLI 动词范本：Snakemake

| Snakemake flag | 语义 | 映射 AMTA |
|---|---|---|
| `--until <target>` / `-U` | 只跑到 target 为止，不跑下游 | `--stages ...,typeset` 的更早版本 |
| `--omit-from <target>` / `-O` | **阻止 target 及其所有下游执行**，只跑独立 sibling DAG | `--render-only`：`--omit-from detect,ocr` = 只用已冻结中间产物渲染 |
| `--forcerun <target>` | 输出再新也强制重跑 | "我确认 OCR 要重跑一次"：`--forcerun ocr` |
| `--rerun-incomplete` / `--ri` | 只重跑输出不完整的 job | 上次崩了半截，从中断处续 |

- 来源：https://snakemake.readthedocs.io/en/v9.4.1/executing/cli.html

### 结论 3.3 — LLM/agent 流水线的专属缓存规范：khoi03/makedown SPEC（强烈建议整段抄）

2026 年新出的开源规范（Apache-2.0），专门给 prompt/LLM 构建图用，和 AMTA 同构。identity hash：

```
id = sha256(
  canonical(resolved_input_hashes) ||
  canonical(recipe_header_normalized) ||   # model id + params + system prompt
  prompt_body ||
  model_id ||
  canonical(params)
)
```

每个 target 一个 `cache` 策略枚举，正好对应 AMTA 的 station 分类：

| cache 值 | 行为 | 映射 AMTA |
|---|---|---|
| `deterministic` | 要求 temperature:0 + seed，按 id 缓存 | typeset / inpaint（确定性代码） |
| `stochastic(n=k)` | **同一 id 下存最多 k 个采样产物作为 sibling，用户 pin 一个 "blessed" 样本，下游只消费这个 pinned 产物** | OCR：重跑产生新气泡数 → 存为新 sibling，人工挑一个 blessed 冻结 |
| `always` | 永不缓存，每次重算 | LLM translate（非确定、有副作用） |

非确定性 side-effectful step 的放行机制 `approval: required`：**产物只有在人工明确批准后才写盘/进 CAS，否则丢弃且下游 target 全部跳过**——正是"OCR 重跑结果在人工确认前不许污染下游"的规则化。

- 来源：https://github.com/khoi03/makedown/blob/HEAD/SPEC.md

### 结论 3.4 — Nextflow `-resume` + task hash：content-addressed task cache 范本

Nextflow 每个 task 一个内容哈希，命中就整体复用 work dir。task hash 由 session ID、task name、container image、conda env、**inputs 文件内容**、task script、引用的全局变量、ext 属性、bundled scripts 组成。

关键点：文件哈希有三档 cache mode——`standard`（path+mtime+size）、`lenient`（忽略 mtime）、`hash`（文件内容 hash）。OCR 输出文件如果 mtime 总在变，就该用"内容 hash"判定而不是时间戳。官方明确反模式：**process 不许修改自己的输入文件**，否则无法 resume。

- 来源：https://www.nextflow.io/docs/latest/cache-and-resume.html

### 直接回答：`--freeze-upstream` 借鉴谁？

**主抄 DVC，动词抄 Snakemake，非确定性 stage 策略抄 makedown。**

- DVC `dvc freeze <stage>` / `frozen: true`：语义就是"上游变了、`--force` 也不重跑，只迭代最后几个 stage"
- 配套动词照 Snakemake：`--render-only` ≈ `--omit-from detect,ocr`；`--rerun-upstream ocr` ≈ `--forcerun ocr`
- OCR stage 本身不要假装确定性：按 makedown 的 `stochastic(n=k)` + `approval: required`——重跑产生新结果时存为 sibling，人工 pin 一个 blessed 后下游才消费；未批准前下游一律跳过

---

## 问题 4：有没有现成的开源 Skill / Hook / Agent 工作流模板可以直接搬？

### 结论 4.1 — 最值得 fork 的收尾 skill：`obra/superpowers` 的 `finishing-a-development-branch/SKILL.md`

完整路径：`skills/finishing-a-development-branch/SKILL.md`（repo: https://github.com/obra/superpowers）。

它已经把 `state.py finish` 耦合的三件事解耦成标准流程（验证 → 探测环境 → 列选项 → 等人选 → 执行 → 清理）：

1. **Step 1 先跑全量测试，红了就停下来报失败，菜单只在绿之后出现**——收尾命令不许在红的树上面谈 integration
2. **Step 2** 用 `git rev-parse --git-dir` vs `--git-common-dir` 探测当前是不是 worktree，决定显示哪个菜单
3. **Step 4 只列固定 3 个选项（本地 merge / push+PR / 保持原样），然后 WAIT，绝不自己替人选**；discard 只在人明确说、且必须逐字打 `discard` 才执行
4. **Option 1 本地 merge 的顺序：先 merge → 在 merge 结果上重跑测试 → 绿了才删 branch**；merge 后测试红 = 一切停下
5. **清理 worktree 被拒时，永远不许自己 `--force`**，先 `git status --porcelain -uall` 把"只存在于 worktree、从没 commit 的文件"列给人
6. 文末附一张 **"Common Rationalizations" 表**，把 agent 容易自我说服的借口逐条怼掉："这 session 早些时候测试是绿的"、"merge 后那个失败大概是 flaky"、"清理被拒，--force 只是把收尾做完"

- 来源：https://github.com/obra/superpowers
- 来源：https://raw.githubusercontent.com/obra/superpowers/main/skills/finishing-a-development-branch/SKILL.md

### 结论 4.2 — 配套 review skill：同 repo 的 `requesting-code-review` / `verification-before-completion`

- `requesting-code-review`：派一个**全新 subagent** 做 reviewer，只给它精确的 `BASE_SHA`/`HEAD_SHA` + diff，**不给它 session 历史**；发现分三级 Critical / Important / Minor
- 两阶段 review：先 spec-compliance review（"需求全做了吗、有没有多做 YAGNI"），过了才派 code-quality review
- `verification-before-completion`：**声称 "done" 之前必须先拿出证据**——这就是你要的 "evidence before claiming root cause" 的现成 skill

- 来源：https://github.com/obra/superpowers （skills/ 目录）

### 结论 4.3 — 防 `git add -A` 带走无关文件的强制层：Claude Code PreToolUse hook

Skill 管"劝"，hook 管"拦"。在 `.claude/settings.json` 里挂 `PreToolUse`，matcher 选 `Bash`，脚本 exit code 2 就拦下这条命令。`guard-git.sh` 可以解析 stdin 里的 command 字符串：命中 `git add -A` / `git add .` 且没有对应 staged-file manifest 时直接 deny；命中 `git commit` 时检查 staged 列表里有没有 >500KB 的图片（我们那起 1MB 图片事故）。

- 来源：https://code.claude.com/docs/en/hooks
- 来源：https://github.com/lekman/ai-toolkit/blob/main/security/isolated/README.md

### 结论 4.4 — SKILL.md 格式的官方标准答案：`anthropics/skills`

官方 repo 里全是**领域 skill**（docx/pptx/pdf/mcp-builder/frontend-design/brand-guidelines…），没有"收尾/commit gate"类 workflow skill——workflow skill 的天花板是 superpowers。但它是格式范本：每个 skill = 一个文件夹 + 根 `SKILL.md`，YAML frontmatter 只有 `name` + `description`（description 决定何时触发），正文是 markdown 指令；重资源放 `scripts/`、`references/` 做 progressive disclosure。repo 里的 `skills/skill-creator/SKILL.md` 就是教你怎么写 skill 的元 skill。

- 来源：https://github.com/anthropics/skills/tree/main/skills

### 直接回答：GitHub 上最值得 fork 的一个 agent 收尾 skill 文件是哪个？

**`obra/superpowers` 的 `skills/finishing-a-development-branch/SKILL.md`。**

理由：它已经把 `state.py finish` 耦合的三件事解耦成了标准流程（测试先绿才出现菜单 / 列固定选项等人选 / merge 后重测才删 branch / 清理被拒永不 --force / Rationalizations 表预防 agent 自我说服）。要做的只是把它的 worktree 语境换成 AMTA 的 workspace 语境。

---

## 问题 5：数值型测试断言怎么写才不脆？（排版/渲染类）

### 结论 5.1 — 首选"契约式几何断言"（contract assertion）：断言不变量，不断言魔法数字

这是治 `font_size >= 30` 的**正解**。不要断言"字号等于 12"或"字号 >= 30"，而是断言排版为什么成立的那条几何不变量：

- 文本块的 bounding box **完全落在气泡多边形内部**（`text_rect.within(bubble_poly)`，留一点 padding）
- 气泡**完全落在 panel 边界内**
- 内边距 `padding > 0`（而不是 `== 某值`）
- 文本宽 ≤ 气泡可用宽（文字不溢出）

业界把这种"不存基线截图、只问单帧这一帧布局对不对"的工具叫 **baseline-free / contract rendering check**。范式是 render-qa：不比对基线截图，只跑活的布局几何，规则就是 `clipped-text`（文字被裁掉且无省略号）、`viewport-overflow`（文字越过视口右缘）这类**单帧不变量**，命中即非零退出。

AMTA 不是 Web（DOM），但范式可平移——用 Pillow 的 `font.getbbox()` / `textbbox()` 量出文字实际包围盒，再和气泡多边形做几何包含判断：

```python
# 不要这样（脆）：
assert font_size >= 30
# 要这样（契约，改字号算法也不该红，除非真的溢出）：
text_box = font.getbbox(text)                 # 实际文字尺寸
usable_w = bubble.w - 2 * PADDING
assert text_box.width <= usable_w             # 文本不溢出气泡
assert inset_by_padding(text_box, bubble) > 0 # 四周留得出边距
```

- 来源：https://www.npmjs.com/package/render-qa
- 来源：https://github.com/mholecy/averi/blob/HEAD/skill/SKILL.md

### 结论 5.2 — 视觉观感用 golden image / perceptual diff：只覆盖"拆不成几何不变量"的部分

凡是"文字有没有溢出气泡"这种**能拆成数字不变量**的，用 5.1 的契约断言；凡是**拆不出来的视觉观感**（字形 shaping、inpaint 纹理是否自然、整页构图），才用 golden image。

| 工具 | 特点 | 安装 |
|---|---|---|
| **pytest-mpl** | matplotlib figure 专用：生成图减参考图算 RMS 差，默认 tolerance=2 | `uv pip install pytest-mpl` |
| **pixelmatch**（Mapbox） | ~150 行零依赖，RGBA 逐通道 + anti-aliasing 检测，`threshold` 0~1 默认 0.1 | `npm i pixelmatch` |
| **odiff**（dmtrKovalenko） | Zig/SIMD 重写，比 pixelmatch 快约 6 倍，内置 anti-aliasing 检测、**ignore regions** | GitHub: dmtrKovalenko/odiff |
| **visualcheck**（PyPI） | Python 侧：pixel diff % **+ SSIM**、ignore regions、HTML 报告、**runtime baseline 缺失时自动创建、默认绝不覆盖**基线 | `uv pip install visualcheck` |
| **imdiff**（PyPI） | 整目录图片对比 + Tk 人工复核窗，适合 golden-file 审批 | `uv pip install imdiff` |

- 来源：https://pytest-mpl.readthedocs.io/en/latest/usage.html
- 来源：https://github.com/mapbox/pixelmatch
- 来源：https://github.com/dmtrKovalenko/odiff
- 来源：https://pypi.org/project/visualcheck/0.3.19/

### 结论 5.3 — tolerance 与 golden drift：别 byte-compare，要"容差 + 可审批更新"

golden image 最大的坑是**环境漂移**——换了分辨率、GPU 驱动、headless 渲染后端，每个像素都轻微不同。业界三件套：

1. **容差分级**：Playwright 的 `toHaveScreenshot` 给了范本——`maxDiffPixels`（允许差多少像素）和 `maxDiffPixelRatio`（允许差总像素的百分之几）。**用 ratio 而不是固定像素数**，不同 DPI/分辨率下行为一致。
2. **ignore regions**：把每次都会变的区域（如 OCR 出来的气泡位置、时间戳）mask 掉，别让它参与 diff。
3. **baseline 审批流**：基线图是"受审产物"，不是随便覆盖。Playwright 用 `npx playwright test --update-snapshots` 显式更新；visualcheck 的"缺失才自动建、默认绝不覆盖"是更安全的默认。**更新基线必须是一次有意识的 commit，而不是 CI 一红就自动覆盖**。

- 来源：https://playwright.dev/docs/test-snapshots

### 直接回答：排版/渲染代码该用 golden image 还是 contract assertion？

**两者都要，按"能不能拆成数字"分层，不要二选一：**

| 层 | 断言什么 | 用什么 | 脆不脆 |
|---|---|---|---|
| **几何契约层**（首选、量大） | 文本不溢出气泡、气泡不出 panel、padding>0、无兄弟元素重叠 | `font.getbbox()` 量数字 + 不等式断言（render-qa 范式） | **不脆**——改字号/换行算法，只要几何不变量守住就不红 |
| **视觉观感层**（少量、兜底） | inpaint 纹理自然、字形 shaping、整页构图没崩 | golden image + perceptual diff（pixelmatch/odiff/visualcheck）+ 容差 + ignore regions | 用容差吸收抗锯齿噪声，只对真实视觉回归报警 |

`font_size >= 30` 之所以脆，是因为它把"实现细节"当成了断言目标。**正确做法是把它翻译成契约**：你真正在意的不是"字号≥30"，而是"文字在气泡里放得下"。

---

## 最值得 AMTA 直接抄的 3 个东西（短名单）

### 🥇 1. `obra/superpowers` 的 `skills/finishing-a-development-branch/SKILL.md`

- **为什么**：它就是把你 `state.py finish` 耦合的三件事拆开的成熟范式——**测试先绿才出现菜单 / 列固定 3 选项等人选 / merge 后重测才删 branch / 清理被拒永不 --force / 文末 Rationalizations 表专门怼 agent 自我说服**。已经精准覆盖你那两起事故（误提交 1MB 图片 + 被旧测试白烧）。
- **抄哪部分**：6 步流程 + 3 选项菜单 + Common Rationalizations 表。把它的 worktree 语境换成 AMTA 的 `workspace/<work-id>/` 语境。
- **URL**：https://github.com/obra/superpowers
- **配套抄**：同 repo 的 `requesting-code-review`（派全新 subagent 只给 SHA+diff）和 `verification-before-completion`（声称 done 前必须先拿证据）。

### 🥈 2. Aider 的 file-list staging + Claude Code PreToolUse git hook（组合拳）

- **为什么**：事故 (a) 不是"加两行 .gitignore"能治的——你要的是**staging 时按 session 实际触碰文件白名单显式枚举，物理上禁止 `git add -A`**。Aider 教你怎么列白名单，Claude PreToolUse hook 教你怎么机器 enforce。
- **抄哪部分**：(i) 进入 session 时如果工作树 dirty，先把 preexisting changes 单独收编成一个 commit（Aider dirty-commits）；(ii) `git add` 时只加这次 session orchestrator 实际触碰过的文件列表（从 stations 产物清单收集）；(iii) 写一个 `check-git-policy.sh`，拦截 `git add -A`/`git add .`，检查 staged 里有没有 `workspace/`、`*.png`、>500KB 文件。
- **URL**：https://aider.chat/docs/git.html + https://code.claude.com/docs/en/hooks-guide

### 🥉 3. pytest-testmon + baseline red list 四类分类（治"被旧测试白烧 20 分钟"）

- **为什么**：你现在 `finish` 一把梭跑全量 pytest（6~31 分钟），第一性解不是"优化跑测试的速度"，而是**"根本不该跑那部分测试"**。testmon 秒级算出"本次 diff 影响哪些测试"，baseline red list 告诉你"哪些红本来就在"。两个一交叉，10 秒内就能判定"这个红归不归我"。
- **抄哪部分**：(i) `uv pip install pytest-testmon`，首次建 `.testmondata` 后 `pytest --testmon`；(ii) session 开始先 snapshot 当前红到 `workspace/<work-id>/baseline-red.txt`，finish 时按 NEW_FAILURE / PRE_EXISTING / KNOWN_ISSUE / UNCERTAIN 四类归因，只对 NEW_FAILURE 负责；(iii) 必须跑全量时用 `pytest-split` 按 `.test_durations` 分 shard 压墙钟；(iv) flaky 用 `pytest-rerunfailures`。
- **URL**：https://github.com/tarpas/pytest-testmon + https://agenticskillset.org/en/topics/continuous-feedback-autonomous-execution-and-regression-analysis/

---

## 附：流水线锁上游的额外弹药（如果你决定改 `run_pipeline.py`）

| 工具 | 直接可搬的 flag / 语义 |
|---|---|
| **DVC** | `dvc freeze <stage>` / `frozen: true`（上游变了、`--force` 也不重跑）；`dvc commit`（人工签收新基线） |
| **Snakemake** | `--omit-from detect,ocr`（= render-only）；`--forcerun ocr`（= 就重跑这一个上游）；`--rerun-incomplete` |
| **khoi03/makedown SPEC** | identity hash 公式（input hash + recipe + prompt + model_id + params）；`stochastic(n=k)` blessed-sample；`approval: required` 非确定性产物人工放行 |
| **Nextflow** | `-resume <sessionId>` 冻结到某次 run；`cache: hash` 用内容 hash 而不是 mtime；process 不许修改自己的输入 |

---

## 安装命令速查

```bash
# 问题 2：测试影响分析 + baseline
uv pip install pytest-testmon        # 只跑受影响测试
uv pip install pytest-impacted       # 纯 AST/git diff 的影响分析
uv pip install pytest-split          # 按历史耗时分 shard
uv pip install pytest-rerunfailures  # flaky 重跑

# 问题 5：视觉回归
uv pip install pytest-mpl            # matplotlib figure golden 对比
uv pip install visualcheck           # Python 侧 pixel diff % + SSIM + ignore regions + HTML
uv pip install imdiff                # 整目录图片对比 + 人工复核窗
npm i pixelmatch                     # 逐像素 + 抗锯齿检测
# odiff: GitHub dmtrKovalenko/odiff （Zig/SIMD，更快）
```
