# CLAUDE.md

AMTA — 会话驱动的漫画翻译自动化。DSH 会话=导演（决策/翻译判断/修复决策/验收），amta Python=确定性工具层，koharu headless（REST :4000）=引擎。里程碑：Benchmark A/B/C。

## 核心事实
- **原图目录**：`D:\我的汉化\汉化作品\东方\单翼停留之地\`（jpg，`1.jpg`~`41.jpg`，页码即文件名；需整页图时从此目录读，不复制进 workspace）
- 本机 Windows / PowerShell 环境
- **翻译通道**：纯文本 DeepSeek LLM（1 call/page，配置走 .env CHAT_BASE_URL/CHAT_MODEL/CHAT_API_KEY）；VLM refine 2026-09-09 已移除；架构细节见 `docs/module-map.md` + ADR-014/016/017/023
- **本地 OCR / Stage 4-6 架构细节**：见 `docs/module-map.md` + ADR-019/020/021/023/024
- **算力**：CPU-only（i5-1135G7 4C8T/16GB），workers 必须=1；inpainter 只有 lama-manga；本地 VLM 不可行
- **代码地图**：`docs/module-map.md`（`find_code.py --index` 自动更新）；找模块/函数/类用 `uv run python scripts/find_code.py <关键词>`，禁止瞎猜路径或硬 grep
- **关键入口**：管线 `scripts/run_pipeline.py --stages <阶段>`（artifact_cache 增量复用）｜报告 `scripts/gen_report.py`｜质检 `scripts/fastcheck.py`｜外部库文档 `scripts/context7.py`

## 必执行 Checklist（chained，AI 自主触发，无需用户提醒）
- 找代码/模块/函数位置/不确定功能在哪个文件：**先用 `scripts/find_code.py <关键词>` 搜索**，再读目标文件；禁止瞎猜路径或全目录硬 grep
- 遇到任何报错/异常/测试失败/行为不符合预期：**先按 diagnosing-bugs skill 流程定位根因**（复现→读报错→二分定位→验证假设），禁止直接猜答案或瞎改
- 做架构/选型/设计决策前（含"要不要重构""选哪个方案""加不加新依赖"）：**先调用 grilling skill 至少 3 轮苏格拉底追问**，逼出假设和 trade-off 再拍板
- 需要外部信息/调研/查资料/对比方案：**委派 research skill 后台 subagent**，主 agent 不硬搜、不凭记忆答
- 需要跑管线/从中间阶段续跑：**用 `scripts/run_pipeline.py --stages <阶段名>`**（支持 detect,ocr,translate,inpaint,typeset 任意子集；artifact_cache 自动复用上游产物，禁止从头重跑或自己拼 01/02/03 脚本）
- 管线运行完成/阶段产物落盘后：**自动调用 `scripts/gen_report.py` 生成 HTML 报告**（验收唯一视觉载体，无需提醒）
- 会话结束/用户说收尾/落盘：**先 cycle-close，Step 5 委派 finisher subagent 做知识归类**（lessons/CLAUDE.md/skill/ADR/progress 五路分流），主 agent 只审核应用

## 渐进式加载（遇到 X → 先做 Y）
> 完整 skill 清单看 catalog（name+description 自动注入），此处只列高频记忆检索动作；坑的唯一归属是 `docs/lessons.md`，不在此重复。

| 症状 / 场景 | 先做 |
|---|---|
| 任何报错 / 测试失败 / 行为异常 | `uv run python scripts/memory.py grep --query "<关键词>"`（先搜 lessons，别重踩） |
| 接手任务 / 不知道停在哪 | `uv run python scripts/memory.py recent` |
| 架构 / 选型决策前 | `uv run python scripts/memory.py grep --scope decisions --query "<主题>"` |
| 记忆可疑 / 机制自检 | `uv run python scripts/memory.py status` |
| docs 导航 | `docs/README.md`（分工）｜`docs/lessons.md`（坑）｜`docs/decisions/`（ADR） |

## 工作协议
- **任务收尾走 /finish**（cycle-close）：复读任务→审查 diff→确定性验证→修复→反思→知识晋升→只更新真正变化的工件→Finish Report→git 落盘
- **知识晋升五路分流**：全局规则(CLAUDE.md)·流程(.dsh/skills/)·架构(docs/decisions/ADR-N)·瞬时(docs/progress.md)·机械(test/lint/hook)；test/lint/hook 是唯一真强制层，rules/lesson 是 prompt 级；CLAUDE.md 保持精简
- **机械护栏分层**：编码期 `uv run python scripts/fastcheck.py`（收尾必跑）→ **pre-commit（每次 commit 跑完整 fastcheck 8 步）→ pre-push（只跑可选 smoke，koharu 可达才跑，不重复 fastcheck）**。安装：`scripts/install_hooks.ps1`（`git config core.hooksPath .githooks`）
- **知识落地**：可复用经验落 `docs/lessons.md`（坑）或 `docs/decisions/ADR-N`（决策）；检索一律 `memory.py grep/read`，先查记忆再动手；GC 用 `memory.py gc`（已并入 fastcheck）；每 2-4 周 `npm run audit`
- **HTML 报告铁律**：必须用 `src/amta/report/` 深接口，禁止 scripts/ 下新建独立 HTML 生成脚本；新增报告类型=在 `report/stages/` 加适配器，扩展方式见 `src/amta/report/__init__.py` docstring

## Python 运行规范（强制）
所有 Python 命令用 `uv run python`，禁止裸 `python`（系统 Python 3.14 无依赖，`.venv` 是 3.12）。项目包在 `src/` 下，脚本内部已自动处理 PYTHONPATH。详见 AGENTS.md。
