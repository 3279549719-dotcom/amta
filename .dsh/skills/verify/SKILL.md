---
name: verify
description: 回归验证与发布流程——smoke/check/precheck 门槛与 git/gh 发布规范。改代码后、提交前读本 skill。
---

# Verify & Release

## 回归门槛

- `npm run check` — 语法门（`uv run python -m compileall -q src scripts`）
  ⚠️ **2026-09-12 修复前它是假绿的**：脚本名 `precheck` 是 `check` 的 npm pre-hook，
  `npm run check` 会先跑 koharu 端口检查，koharu 没起就中止，**compileall 一次都没跑**。
  已改名 `koharu:check`，并加了守卫（`tests/test_reference_integrity.py`）。
- `npm run fastcheck` — 全量门（compile+ruff+pyright+pytest）。**tests/ 用 pytest 收集**（unittest discover 只收 `TestCase` 类，静默跳过模块级 pytest 函数会假 PASS）；Windows 下 pytest 尾部 `PermissionError: pytest-current` 是 tmp_path teardown 噪音（L19），**判据 = 汇总行 `N passed` 而非 exit code**（fastcheck 已用 `--basetemp` 根治）。
- **端到端验证按改动自选**（ADR-030，L5 交给 agent 而非死脚本）：改哪个 stage 就真跑哪个 stage 的通路——detect/ocr/translate/inpaint/typeset 各自用对应工位脚本或 `run_pipeline.py --stages <X> --pages 1-1` 真跑一页；只有真动 `koharu_client/runner` 才需要 koharu smoke（`npm start` 后跑 smoke_test.py）。验证选择与理由写进收尾报告。
- `npm run koharu:check` — 4000 端口可达性（exit 0/1）；旧名 `precheck` 会劫持 `npm run check`，已弃用
- `npm run smoke` — koharu 冒烟测试（**需先 `npm start`**）：连引擎→建项目→传图→跑检测→读场景→读 mask→关项目，PASS 即通路 OK。仅当改动涉及 koharu 通路时跑。

改代码后至少过 `check`；端到端验证按你改的具体 stage 自选（见上）；合入 main 前跑 `finish`（L6 独立 model 审核门 `review.py` 已随 ralph 层删除，2026-09-12）。

## 发布流程（git/gh 裸命令，不包进 package.json）

1. `git status` 确认无意外改动（**不用 `git add -A` 一把梭**）
2. `git add <明确文件>` → `git commit -m "type: 摘要"`（type: feat/fix/chore/docs/refactor）
3. 推送前 `git fetch origin` 评估分叉 → rebase 后 `git push`
4. 仓库：`3279549719-dotcom/amta`（私有，main）

## 验收口径

- 冒烟必须输出 PASS
- Benchmark 报告：recall/precision/CER/EM 数字 + FAIL 定位模块
- **不把「看起来没问题」当验收**——程序化门槛为准
