# 06-代码架构整理/可视化 skill 与 CLI 工具调研详报

> 日期：2026-08 · 调研人：驻场调研 agent · 范围：项目文件/代码架构整理、归纳、可视化（目录树、依赖图、C4 架构图、代码库地图、文档整理、仓库卫生审计）
> 环境约束：Windows、无管理员权限、可装用户目录；AI 协作栈 DSH + `.dsh/skills/`；已有 superpowers（Matt Pocock）栈，经 `npx skills add` 落 `~/.agents/skills`。

## 一、候选清单（已逐一验证安装命令与许可）

| 名称 | 能力 | 安装方式（Windows 用户目录） | 平台 | 许可 |
|---|---|---|---|---|
| **repomix**（yamadashy/repomix） | 把整个仓库打包为单个 AI 友好文件：目录树 + 文件内容 + token 计数；支持 markdown/tree 输出、.gitignore 尊重、自定义 include/exclude；另提供 MCP server | `npm i -g repomix`，或免安装 `npx repomix` | Node.js（Windows ✓） | MIT |
| **code2prompt**（mufeedvh/code2prompt） | 代码库→LLM 提示词：源文件树 + Handlebars 模板 + token 计数 + git 集成；提供 Python SDK（`code2prompt-rs`）与 MCP server | `pip install code2prompt-rs`（Python 绑定）；或 GitHub Releases 下载 Windows 二进制 | Rust 核心 / Python 绑定（Windows ✓） | MIT |
| **c4-codebase-architecture-skill**（lmammino） | agent skill：从代码证据（入口点、manifest、基础设施描述）反推 C4 架构文档（Context/Container/Component），区分观察事实与推断，输出 Markdown + **Mermaid** / PlantUML / Structurizr DSL | `npx skills add lmammino/c4-codebase-architecture-skill --skill c4-codebase-architecture`（落 `~/.agents/skills`，与现有 superpowers 同目录）；或手动拷 `skills/c4-codebase-architecture/` 到 `.dsh/skills/` | 任何 agent 环境（纯 SKILL.md，可移植） | MIT |
| **Repo Skills**（rjwalters/repo） | 仓库卫生 skill 集（Claude Code `/repo:*` 命令）：`/repo:audit` 全量健康扫描、`/repo:tidy` 清理构建产物/缓存/空目录、`/repo:orphans` 找无引用死文件、`/repo:docs` 文档健康、`/repo:readme` 校验 README 与目录实际内容一致性、`/repo:links` 校验内部交叉引用、`/repo:gitignore` 审计 | `git clone https://github.com/rjwalters/repo` 后 `./install.sh <repo路径>`（bash 安装器；Windows 需 Git Bash，或手动把 `skills/repo/` 拷入 `.dsh/skills/`）。安装器面向 `.claude/` 与 `.agents/skills/`，skill 本体是开放 Agent Skills 格式可移植 | Claude Code / Codex（开放 SKILL.md 格式） | MIT |
| crystal（dbinagi） | LLM 上下文感知代码库洞察 | ❌ **未能验证**：GitHub raw 404、PyPI 上 `crystal` 是无关绘图库（plot.ly）。不推荐 | — | — |

## 二、推荐结论

### 装 1：c4-codebase-architecture-skill（补「架构可视化」缺口）
现有 skill 栈（superpowers + 自研）里**没有**生成 Mermaid/C4 架构图的能力；该项目 skill 是 skills.sh 生态里少见的"从代码证据反推架构"的实现，输出 Markdown + Mermaid 可直接晋升进项目知识体系/ADR。安装方式与现有 superpowers **完全一致**（`npx skills add` 落 `~/.agents/skills`），零新工具链、零管理员权限。

### 装 2：repomix（补「目录树/代码库地图」缺口）
一条命令产出完整目录树 + token 计数 + 单文件打包，Windows 下 `npx repomix` 免安装即用；输出可作 DSH 会话的全局上下文，或作为 audit/收尾流程的输入（生成 `.dsh/` 下的结构快照）。与 code2prompt 相比：code2prompt 在 Windows 需装 Rust 或下二进制，repomix 是纯 npm，更省事，故二选一推 repomix。

### 候选（可选）：Repo Skills 的 `/repo:orphans`、`/repo:tidy`、`/repo:readme`
对现有 audit skill 的成熟补强（死文件、缓存/空目录、README 失真的检测），但安装器面向 `.claude/`，Windows 下需 Git Bash 或手动拷贝到 `.dsh/skills/`，且会向 CLAUDE.md / settings.json 写钩子，与 DSH 栈需适配，列为候选而非首推。

## 三、诚实声明（无确切匹配的领域）

1. **「文档体系整理 / README 生成」无专门高 star skill**：skills.sh 生态未检索到成熟的 README 生成/知识库组织 skill；最接近的是 Repo Skills 的 `/repo:docs` `/repo:readme`（校验而非生成）与已有 writing-for-agents。
2. **目录树专用 skill** 未单独找到：tree 输出由 repomix / code2prompt 内建承担，无需额外 skill。
3. **crystal 无法验证**（GitHub/PyPI 均无可靠入口），不推荐；同类替代即 repomix/code2prompt。

## 四、来源

- repomix：https://github.com/yamadashy/repomix · npm：https://www.npmjs.com/package/repomix（v1.18.0, MIT）
- code2prompt：https://github.com/mufeedvh/code2prompt（MIT；PyPI `code2prompt-rs`）
- c4-codebase-architecture-skill：https://github.com/lmammino/c4-codebase-architecture-skill（MIT，README 含 `npx skills add` / `npx skills install npm:@lmammino/...` / 手动拷贝三种安装法）
- Repo Skills：https://github.com/rjwalters/repo（MIT；`install.sh` 用法见 README）
- skills.sh 生态入口：https://github.com/antfu/skills-cli · https://skills.sh · 注册表 https://askill.sh
- 其他检索过的同类：vsxd/agent-skills（https://github.com/vsxd/agent-skills）、aronpc/ai `codebase` skill（askill.sh，葡萄牙语，偏改进机会挖掘而非可视化）
