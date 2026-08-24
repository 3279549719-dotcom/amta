# 014 — 翻译工位架构定稿：DeepSeek API 直调 + 双层护栏 + 分层 Loop

## Context

- ADR-013 定了产物结构（per-work workspace + work_state），本 ADR 落地其核心工位——**翻译工位**的形态。
- 参考 two references（first-principles/DIKW + simple structure factory）后 grill 定案：
  - 原锁定决策 #5（koharu 内 `llm` 引擎 + Story Memory 注入）**悬空未兑现**：koharu 未在跑、`llm` 引擎 not-ready（需 Settings 配 provider，`llm_status()` 校验不过）。
  - `.env` 已有现成 DeepSeek 通道：`CHAT_BASE_URL=https://api.deepseek.com` + `CHAT_MODEL=deepseek-v4-pro-0813` + `CHAT_API_KEY` → 脚本直调可行。
  - 用户明确：多 OCR 忽略（For-Manga 单引擎已定案 ADR-011），reference 的 Harness 四维度有出入需按会话驱动架构修正。

## Decision

### 1. 翻译层 = 脚本直调 DeepSeek API（修订锁定决策 #5）

- `04_translate.py`（实际编号 03）组装结构化 prompt → 调 `https://api.deepseek.com` → 写 `translation.json` + `state/suggestions.json`。
- 不再依赖 koharu 内 `llm` 引擎。koharu 仅用于 detect/ocr(可选)/inpaint/typeset 的机械引擎面。
- 会话驱动不变：DSH 会话=导演，负责语义 loop 与最终验收；翻译执行从"会话逐页"转为"脚本可批跑"（解决速度痛点）。

### 2. Harness 四维度取舍

- **做 Context**：分层组装 System / Current（canon_text 当前页）/ History（前 3 页译文）/ Knowledge（work_state 术语）/ Uncertainty（open_questions）。
- **做 Guardrails**：双层护栏（见下）。
- **做 Loop**：分层（见下）。
- **砍 Tools**：不做 function calling——脚本本地直读文件（lookup_term/get_prev_page 都是本地文件读取，无 API 往返价值）；suggestions 由脚本直接写 `state/suggestions.json`。

### 3. 双层护栏（工位边界：translate 只管文本质量）

**机械护栏（脚本内纯代码，类比 fastcheck/hook）**：
- ① 结构错：输出合法 JSON、region_id 与输入 canon_text **一一对应**（数量/集合一致，无漏无重 → 天然杜绝"贴错框"）、字段齐全。
- ② 残留错：日文残留检测（正则）+ 空译文检测。

**语义护栏（手搓 VLM 脚本，DASHSCOPE 通道现成）**：
- ③ 语义错：crop 图 + 译文 → VLM 判断译文是否忠实原文 / 漏译 / 人名歧义（豊姫/星姫/豊妃）。
- 明确：VLM 只做**语义验证**，不做坐标/仲裁（单引擎无候选可仲裁）。

**工位边界**：detect 漏检、inpaint 擦字失败、typeset 排版错位 = **各自工位自己的 mechanical check**（future work），不塞进 translate。

### 4. 分层 Loop（backward reasoning：无 observe/feedback 的重试是随机重掷）

- **脚本层机械 loop**：初译 → 机械护栏失败（如 JSON schema 错）→ 错误回填 prompt → 自动重译 **1 次**。
- **导演层语义 loop**：VLM 语义护栏拦出问题 → 脚本标记 `FAILED` + 附证据（VLM 输出/错误行）→ 交 DSH 会话修订（导演是最终 loop 层，脚本不硬编码翻译判断）。
- 确定性错误（机械护栏失败 2 次仍不过）→ 不无限重试，标 FAILED 交导演；重跑由 00_run_all 断点机制覆盖（删除工件再跑）。

### 5. 术语演进（suggestions → 导演自动合并）

- 翻译发现新角色/术语 → 脚本写 `state/suggestions.json`（含来源页 + 证据）→ 导演批跑后自动合并进 `work_state.json`（canon 类进 `touhou_knowledge.json`）。
- **零人工卡点**（导演即 DeepSeek 会话，用户无需审批）；保留 suggestions 中间层为可追溯记录。

### 6. 工位清单与编排（ADR-013 落地形态）

```
00_run_all.py   编排器（文件存在=跳过，断点续跑）
01_detect      → detection.json（koharu 检测）
02_ocr         → canon_text.json（For-Manga 单引擎，带 region_id）
03_translate   → translation.json + state/suggestions.json（本 ADR 核心）
04_inpaint     → cleaned.png（koharu lama-manga）
05_typeset     → final.png（koharu renderer 或自建）
```

state/ 三文件保持 ADR-013：`touhou_knowledge.json`（canon prior，跨本子）+ `work_state.json`（当前本子）+ `open_questions.json`；新增 `suggestions.json`。

## Consequences

- ✅ 翻译可后台批跑、可重跑、不依赖 DSH 在线（速度痛点解决）；`llm_status()` 依赖消失。
- ✅ 护栏哲学与项目一致（机械强制层 + 验收层）；VLM 只做语义，不做坐标/仲裁。
- ✅ 导演仍是最终裁决层（语义 loop + 验收），脚本不硬编码翻译判断。
- ⚠️ **修订锁定决策 #5**：progress.md「已锁定决策」需同步；koharu 内 llm 引擎弃用（除非未来需要其 Story Memory 注入面）。
- ✅ **03_translate 已实现（2026-08-25）**：`src/amta/translate.py`（纯库：chat client/3 机制/Context/护栏/Loop/suggestions）+ `scripts/03_translate.py`（薄 CLI）+ `tests/test_translate.py`（11 测试）；fastcheck ALL PASS。
- ⚠️ VLM 语义护栏脚本、04/05 工位 mechanical check 是后续工作。
- 代码落点：`src/amta/translate.py` + `scripts/03_translate.py`。

## 借鉴来源与许可证（grill 定案，2026-08-24）

- **机制① glossary 相关条目提取** —— 借鉴自 manga-image-translator（zyddnys，GPL-3.0）`extract_relevant_terms` 设计：只喂与当前文本匹配的术语，防大词表稀释 system 权重。**只借鉴设计，不复制代码**。
- **机制② 分层拆分重试** —— 借鉴自 manga-image-translator（GPL-3.0）：数量校验 → 重试 → 二分拆分递归 → 保留原文。**只借鉴两层（数量校验+拆分重试），不抄其 300+ 行全逻辑**。
- **机制③ 翻译缓存层** —— 借鉴自 comic-translate（ogkalu2，Apache-2.0）：源文 hash 作键，源文变才重翻。
- **纪律**：GPL-3.0 仓库仅借鉴设计思路；Apache-2.0 可自由复制（带署名）。代码注释已记录来源（`src/amta/translate.py` 文件头 + 各机制函数 docstring）。若未来开源 AMTA，GPL 借鉴点需换实现。
