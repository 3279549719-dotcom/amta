---
name: verify
description: 回归验证与发布流程——smoke/check/precheck 门槛与 git/gh 发布规范。改代码后、提交前读本 skill。
---

# Verify & Release

## 回归门槛

- `npm run check` — 语法门（`python -m compileall -q src scripts`）
- `npm run precheck` — 4000 端口可达性（exit 0/1）
- `npm run smoke` — 冒烟测试（**需先 `npm start`**）：连引擎→建项目→传图→跑检测→读场景→读 mask→关项目，PASS 即通路 OK

改代码后至少过 `check`；动 `koharu_client.py` / 流水线 / 引擎相关必须过 `smoke`。

## 发布流程（git/gh 裸命令，不包进 package.json）

1. `git status` 确认无意外改动（**不用 `git add -A` 一把梭**）
2. `git add <明确文件>` → `git commit -m "type: 摘要"`（type: feat/fix/chore/docs/refactor）
3. 推送前 `git fetch origin` 评估分叉 → rebase 后 `git push`
4. 仓库：`3279549719-dotcom/amta`（私有，main）

## 验收口径

- 冒烟必须输出 PASS
- Benchmark 报告：recall/precision/CER/EM 数字 + FAIL 定位模块
- **不把「看起来没问题」当验收**——程序化门槛为准
