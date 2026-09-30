# 书内翻译记忆 + 有界生成—验证—修复闭环 — 设计

日期：2026-09-30
状态：**待用户确认**（确认后进入实现；确认即实现授权，不是逐页翻译验收）
前置任务书：`docs/superpowers/plans/2026-09-30-translation-memory-agent-task.md`

---

## 0. 这份设计要解决什么（只有两个缺陷，都有磁盘证据）

### 缺陷 A — 书内翻译决定从不进入记忆

同一本书里，一个表达第一次被译成什么，之后**没有任何机制记得**。

证据链：

| 事实 | 位置 |
|---|---|
| 唯一写入 `work_state.terms` 的生产路径是静态主词典匹配，记 `source="pre_scan"`，**无页码、无 region、无置信度** | `src/amta/guards/pre_scan.py:94-99` |
| `pre_scan` 只在 `terms` 为空时跑一次，此后永不增长 | `src/amta/orchestrator/adapters/translate.py:20-25` |
| 另一条写入路径（`suggestions.py:77`）**在生产代码里零调用方** | grep `src/`；唯一引用是 `scripts/archive/merge_suggestions.py` |
| 只有 `status == "confirmed"` 的术语进入 prompt | `src/amta/translation/stage3_minimal.py:216` |
| 跨页上下文硬编码 3 页 | `stage3_minimal.py:264` |
| 上下文取的是"store 里最后 N 页"，**不是"本页之前的 N 页"** | `stage3_minimal.py:101` |

**决定性反例（推翻"把窗口开大就行"这条路）**：在 `workspace/gui-1790591328680` 里，管线 page_1（原图 3）把 `こいつはヤミツキ茸といってな` 译为 `这家伙叫成瘾菇`；page_4（原图 8）翻译时，`page_keys[-3:]` = `[page_1, page_2, page_3]`，也就是 page_1 的译文**物理上就在 page_4 的 prompt 里**，而 page_4 依然把 `ヤミツキ茸` 原样吐出（r01/r04/r16）。

⇒ 前页译文作为**文本**出现在 prompt 里，不构成任何绑定。必须有一条**以原文表达为键、明确作为强制译名注入**的记录。这不是"窗口不够宽"的问题。

### 缺陷 B — 日文残留被检测出来后丢弃

`stage3_minimal.py:353` 算出 `residue`，`:359` 写进产物，然后**结束**：`_guarded.py:42` 无条件返回 `status="ok"`。

同一 work-id 的 `state/pipeline_log.json` 逐字记录：

```
translate page_4  status=ok  detail={"n_residue":3,...}
typeset   page_4  status=ok  detail={"rendered":17,"translated":17,"coverage_complete":true,...}
```

而 `artifacts/typeset/page_4.json` 里 `ヤミツキ茸` 出现 4 次 —— 片假名已经渲进成品，阶段报 `ok`。翻译产物 schema 也因此**没有任何页级/region 级状态字段**（`src/amta/stores/artifacts.py:71-78`）。

`stage3_minimal.py:354` 的注释写明了原因："纯机械检查出违规也无法触发重翻/修正, 无实际价值" —— 这个诊断是对的，缺的是让它**有东西可触发**。

### 顺带必须修的第三个缺陷（需求 7 强制）

`work_state.json` **不在** translate 阶段的 fingerprint 输入里（`orchestrator/pipeline.py:123-131`、`stores/artifact_cache.py:66-83`；输入集只有 `{raw_image, canon}` + 16 个代码文件 + config）。后果：**改翻译记忆后缓存照命中，旧译文静默留下**。任何记忆设计在修掉它之前都是死信。

---

## 1. 事实更正（必须记下来，否则下一轮会在错前提上重做）

任务书里的症状描述与磁盘事实有三处出入。本设计以**磁盘事实**为准，并将出入显式记录，而不是把它抹平：

1. **原图 1 是扉页**（OCR 只有 `DOJIN全年齢全年齢対象` / `どなたでも購入・閲覧できます`），不含任何 `クズ`/`ゲス`。
2. `クズ` 与原图 7（`それでも一本筋の通ったクズだと思ってました!`）—— 该处**已被正常译为 `人渣`**，`residue=[]`。任务书"第 7 页残留日文"在本 workspace **未复现**。全部 `人渣` 字样都出现在 `page_1`，即**原图 2**，其原文是 `☆...開幕ゲス!` —— 是 `ゲス` 不是 `クズ`。任务书把这两个词并成了一个。
3. **原图 8 不含 `クズ`/`ゲス`**（17 框，`n_conf_removed=0`，不是被置信度过滤掉的）。原图 8 的真实缺陷就是 `ヤミツキ茸` 残留。

⇒ 验收锚点定为 **原图 3 → 原图 8 的 `ヤミツキ茸`**（有磁盘证据、页距 > 3、同时压中两个缺陷），不采用"第 7 页残留"。

### 成品参考的实测读法（视觉验证，非推测）

用本地 inpaint 生成无字底板后与 `新建文件夹` 对照读出：

| | 管线出货 | 人工成品（最终读法） |
|---|---|---|
| 原图 3 | `这家伙叫成瘾菇` | **`成瘾菇`** |
| 原图 8 | `ヤミツキ茸`（未译） | **`迷幻菇`** |

**人工成品自身在书内就不一致**：第 3 页成瘾菇、第 8 页迷幻菇。而三个早期 3 页跑（stems 3,4,5）在**第 3 页**用的是迷幻菇。同一份输入、同一个表达，决定被反复改过。

⇒ 这一条直接决定验收规则（见 §7）：**不断言某个具体词，断言"第 8 页复用第 3 页的决定"**。否则测试要么随机变红，要么必须把答案预置进词典 —— 后者正是任务书需求 6 明令禁止的补丁。

---

## 2. 设计原则（Bitter Lesson，以及本次明确的自律）

**模型负责**：这个表达算不算书内表达；两个 OCR 表面形是不是同一个表达；该用哪个译名；残留该怎么修。

**确定性代码负责**：拿本页 OCR 文本去查已记录的表达、注入、残留检测、有界重试计数、落盘、状态、缓存失效。

### 2.1 明确砍掉的东西（以及砍掉的理由）

这一节是防空转的。上一轮我提出的下列机制**没有任何一次真实失败支持它**，按 `docs/friction.md` 的准入条件（预防性机制一律不建）全部砍掉：

| 砍掉 | 理由 |
|---|---|
| 独立 CLI 工具（`memory.py` 风格） | 为"原语化铁律"的对称美学而加，无失败支撑 |
| 跑后 reconcile / 乱序收敛 pass | 没有任何观察到的失败；冲突改为在**下一个真正用到它的页面**上由模型裁定 |
| 分层修复（region 定向 → 升级整页） | 预设了"整页上下文坏掉"这个没发生过的场景；改为**一次修复** |
| Levenshtein 阈值绑定 + 模型引用 id + 关联置信度 | 把我自己的不信任做成机制；`term_dict.match_terms` 的 lev ≤ 2 正是误绑来源，**不再新增任何阈值**。"是不是同一个表达"交给模型 |
| `ok` / `ok_low_confidence` / `failed` 新状态枚举 | 发明词汇表。低置信度改为**已存在字段 + 代码算出的证据**，页级状态静态推导 |
| 独立 `translation_memory.json` store | 发明新概念/新 schema 家族/新审计面。改为 `work_state.json` 加一个顶层键 |
| 接上 `suggestions.py` | 已被证伪（`candidate` 10 条全是片假名正则误抓的普通词 ルール/メリット/ガチャ）。用户已确认不管它 |
| 删除 3 页上下文窗口 | 宽窗口无价值（§0 反例已证），但它做语气/指代一致性零成本；**保留，不动代码** |
| 跨书全局记忆 | 本阶段不做；症状是"一本书内" |

### 2.2 不新增用户可见配置项

本设计**不引入任何新的 knobs**（无 `--memory` / `--repair` / `--threshold` 开关）。行为是默认行为。理由：新增开关等于新增"坏了没人发现"的表面积。

---

## 3. 组件职责

改动集中在 `src/amta/`，新增代码尽量落进**已有的深模块**，不新建平行体系。

| 组件 | 文件 | 职责 | 新增/修改 |
|---|---|---|---|
| 记忆存储 | `src/amta/common/workstate.py` | `work_state.json` 新增顶层键 `decisions`；提供 `load_decisions` / `record_decisions` 两个函数 | 修改 |
| 记忆检索 | `src/amta/guards/term_replace.py` 或同级新函数（**放已有 guards 模块内**） | 用本页 OCR 文本匹配 `decisions` 的 `surface`/`aliases`，返回要强制注入的译名 | 修改 |
| 提示注入 | `src/amta/translation/stage3_minimal.py` | 把命中的决定作为**强制译名**拼进 `system_extra`；翻译调用改为同时返回决定 | 修改 |
| 调用契约 | `src/amta/translation/translate.py` | 输出契约由 `{"translations":[...]}` 扩为同时可带 `decisions`；`max_retries` 死参数启用为**一次**修复 | 修改 |
| 残留修复 | `src/amta/translation/stage3_minimal.py` | 残留非空 → 残留清单回填 → 重问一次；仍残留则落盘低置信度 | 修改 |
| 缓存失效 | `src/amta/orchestrator/pipeline.py` | `_stage_input_files` 对 translate 阶段纳入 `work_state.json` | 修改 |
| 红榜聚合 | `src/amta/orchestrator/quality_audit.py` | 把低置信度计入本页 flag（复用现有 `PageFlags`，不新增字段族） | 修改 |

**不新建**：不新建 `src/amta/memory/` 下的东西（那是"项目知识记忆"，与"书内翻译记忆"同名不同物，混用会污染搜索），不新建 store，不新建 CLI，不新建 HTML 报告路径。

---

## 4. 数据结构

### 4.1 `work_state.json` 新增顶层键

沿用已有文件，新增一个顶层键。形状：

```json
{
  "work_id": "<id>",
  "updated_page": 8,
  "characters": {},
  "relationships": [],
  "terms": { "サグメ": {"translation": "サグメ", "status": "confirmed", "source": "pre_scan", "master_dict": true} },
  "decisions": {
    "ヤミツキ茸": {
      "surface": "ヤミツキ茸",
      "translation": "成瘾菇",
      "aliases": ["ヤミツキ", "ヤミツキ茸"],
      "evidence": [
        {"page": 2, "region_id": "r05", "surface_seen": "ヤミツキ茸", "match": "exact"}
      ],
      "source": "translate",
      "status": "tentative",
      "updated_page": 2
    }
  },
  "current_scene": {"page": null, "location": null, "present": []},
  "recent_context": []
}
```

字段语义（**每个字段都要被读写，否则不要加**）：

- `surface` — 权威键。规范化的原文表达。
- `translation` — 本次生效的译名。
- `aliases` — 见过的 OCR 表面形（`合有量` 这类变体不进这里，进 evidence；`aliases` 只放**模型判定为同一表达的另一种写法**）。
- `evidence` — **任务书需求 3 要求可追踪的东西**：页码、region_id、当时看到的原始表面形、匹配类型（`exact` / `model_judged`）。只有 `exact` 和 `model_judged` 两种值，**不引入数值置信度阈值**。
- `status` — 只允许 `tentative` 和 `confirmed` 两值。首次记录 = `tentative`（任务书："第一次作出的书内翻译决定是暂定决定"）。重复出现同一译名 = 停留（不自动升格，避免"错误提升"）；模型在新证据下改译名 = 更新 `translation` 并追加 evidence（**旧值不删除、不静默丢弃**，见 §5.4）。
- `source` — `translate`（区别于 `pre_scan`/`manual`）。
- `updated_page` — 最后一次改动的页码。

### 4.2 与既有 `terms` 的关系

`terms` 语义**不变**（pre_scan / manual 锁定的术语）。检索时两者**合并**，`terms` 优先（人工/词典先验高于模型暂定决定）。**同名同词冲突时不覆盖**：新决定作为独立 evidence 追加；若 `terms` 里已有同名键而译名不同，`decisions` 照记，检索时 `terms` 的值优先，并在该页产物里记一条 `memory_conflict`。

理由：覆盖是"错误提升"的一种，需求 7 明确禁止。

### 4.3 翻译产物的新增字段

在既有信封上加字段，**不新增状态枚举**：

```json
{
  "translations": {"r01": "差不多消费者也该觉得现在成瘾菇的含量不够劲了吧？"},
  "residue": [],
  "low_confidence": [
    {"region_id": "r04", "reason": "residue_after_one_repair",
     "attempted": "region_rewrite_with_residue_hint",
     "evidence_pages": [2, 7]}
  ],
  "memory_conflict": [
    {"surface": "ヤミツキ茸", "terms_translation": "迷幻菇", "decision_translation": "成瘾菇"}
  ],
  "translation_mode": "translation-v1",
  "work_id": "...", "page": "page_7", "schema_version": "2.1", "generated_at": "..."
}
```

- `low_confidence` — 空数组 = 高置信度。**这就是"机器可读的低置信度状态分"**，不是新枚举。页级呈现静态推导：`low_confidence` 非空 ⇒ 该页不是干净的 `ok`。
- `residue` — 保留原语义（修复后仍残留的原文列表）。
- `memory_conflict` — 仅在真有冲突时非空。

`TranslationArtifact` TypedDict（`stores/artifacts.py:71-78`）同步加这两个可选键。

---

## 5. 数据流与生命周期

### 5.1 单页流程（page-major，与现有管线一致）

```
_run_stage(translate, page_N)
  │
  ├─ fingerprint 输入 = {raw_image, canon/page_N.json, state/work_state.json}   ← 修复 §0 第三缺陷
  │
  ├─ stage3_minimal.translate_page_minimal
  │    │
  │    ├─ 1. 读 work_state.json → terms + decisions
  │    ├─ 2. 拿本页 canon 的 OCR 文本，去 terms/decisions 里查命中的表达
  │    │      （规范化后相等 = exact；模型在本次调用里判定 = model_judged）
  │    ├─ 3. 命中项作为「必须使用以下译名」拼进 system_extra
  │    ├─ 4. 一次 LLM 调用：
  │    │      · 输入 = 本页原文数组 + 强制译名 + 既有前页上下文(3页，不动)
  │    │      · 输出 = {"translations":[...], "decisions":[{"surface","translation","surface_seen"}]}
  │    │      decisions 是可选的；模型认为本页没有新表达就不返回
  │    ├─ 5. 残留检测 japanese_residue_check
  │    │      非空 → 残留清单回填 → 【一次】重问 → 再检测
  │    ├─ 6. 仍残留 → 组装 low_confidence（带 reason + attempted + evidence_pages）
  │    └─ 7. 落盘：work_state.decisions += 本页新决定（追加 evidence，不覆盖旧值）
  │
  └─ write artifacts/translation/page_N.json
       guarded() 返回 status="ok"（不阻塞流水线）
```

### 5.2 检索为什么与页距无关（缺陷 A 的正解）

检索**不按页码邻近**，按**本页 OCR 文本里出现了哪些已记录的表达**。第 3 页记下的东西，第 8 页（或第 80 页）出现就能命中。页距这个概念在本设计里不存在。

### 5.3 OCR 邻近变体如何留下证据（需求 3）

三层，每层都留痕，且**不引入任何新阈值**：

1. **规范化相等**（`common/metrics.norm` 去标点空白后相同）⇒ 自动命中，evidence 记 `match: "exact"`，`surface_seen` 记**实际看到的那个表面形**。
2. **模型判定**：规范化后不同、但模型在本页判断是同一个表达 ⇒ 该表面形进 `aliases`，evidence 记 `match: "model_judged"`。
3. **判定不了** ⇒ 不绑定，按新表达记一条 `tentative`。**漏绑退化为"这页重新翻一次"，误绑会污染之后每一页**，所以宁可漏绑。

**明确不做**：不写片假名正则、不写停用词表、不写类别白名单、不沿用 `term_dict` 的 lev ≤ 2 模糊匹配。这三样正是 `candidate` 假阳性的来源。

### 5.4 决定修订与已出图旧页（Q4 决策 = (a)）

- 暂定决定因新证据被修订 ⇒ 更新 `translation`，旧值连同其 evidence **保留在同一 `decisions` 条目里**（不删、不新建条目、不静默丢弃）。
- 已出图的旧页**不回改**（成本无界）。改用旧译法的页在**下一次跑到它时**自然被重翻（因为它依赖 `work_state.json` 的 fingerprint 变了）。
- 已渲染的旧 PNG **保持原样**；被取代这件事通过 `decisions` 里的 evidence 链和下一轮重跑可见，不做静默一致化。

### 5.5 低置信度的表现（需求 4、Q5 决策 = (a)）

- 一次有证据的修复后仍不确定 ⇒ **用当前证据支持的最佳译文继续出图**，并行落盘 `low_confidence`。
- 阶段仍返回 `status="ok"` ⇒ **不阻塞整本流水线**（任务书明文要求），inpaint/typeset 照跑。
- 红榜（`quality_audit`）把 `low_confidence` 计入本页 flag，于是 **`run_pipeline` 收尾会吐出来**，不是埋 JSON。
- 退出码**不受影响**（保持 `return 1 if result.failed_pages else 0`）。

### 5.6 失败处理矩阵

| 情况 | 行为 |
|---|---|
| LLM 返回长度不符 / JSON 崩坏 | 保持现有语义：整页空译文（`translate.py:172-173`），**不重试**（数组契约已加固；重试是 `L52` 说的臭味） |
| 网络错误 | 复用 `chat_client` 既有 2 次传输层重试（`chat_client.py:52-70`） |
| 残留非空 | 回填残留清单，**一次**修复调用 |
| 修复后仍残留 | `low_confidence` + 最佳译文继续出图 + 红榜可见 |
| `work_state.json` 损坏/不可读 | 记忆为空继续翻译（不阻塞），打印可见降级信号（沿用 `pre_scan.py:70-74` 的 stderr 警告风格） |
| `decisions` 里同名不同译名冲突 | 两条并存，`terms` 优先；记 `memory_conflict`；由模型在下一个用到它的页面裁定 |
| 模型返回空 `decisions` | 合法。本页不新增记忆 |

---

## 6. 缓存 / 重跑语义（需求 7）

| 场景 | 结果 |
|---|---|
| 改了 `work_state.json`（新增/修订决定） | `work_state.json` 在 translate 的 fingerprint 输入集里 ⇒ 相关页 fingerprint 失效 ⇒ 重翻。**不再是静默用旧译文** |
| 缓存命中（记忆未变、canon 未变、代码未变） | 跳过，产物原样复用。**不重复污染记忆**：记忆写入只发生在真正跑了的页面上，缓存跳过的页不会重放写入 |
| 断点重跑（部分页已跑） | 已跑页缓存命中；未跑页正常跑并在需要时读记忆 |
| 整本重跑（`--force-rerun`） | 每页都重跑 ⇒ 每页都会追加 evidence。**必须有幂等保护**：同一 `(surface, page, region_id)` 已有 evidence 时不重复追加，避免 evidence 列表随重跑无限膨胀、被误读成"重复证据提高了置信度" |
| 乱序 / 部分跑（先 8 后 3） | 两条决定可能并存且译名不同。**不写调和代码**；下一个碰到该表达的页面由模型裁定。这与"第一次决定是暂定、新证据可修订"是同一条规则 |

**幂等键** = `(surface, page, region_id)`。这是需求 7"不会无声丢失、重复污染或错误提升"的机械保证，也是它唯一的测试锚点。

---

## 7. 验收规则（Q 决策 = (a)：断言机制，不断言词）

**不做**：断言第 8 页输出 `迷幻菇`。理由已由 §1 实测证实：原图 3 同一输入曾产出 `成瘾菇` 与 `迷幻菇` 两种结果，硬断言具体词要么随机变红，要么必须预置答案 —— 需求 6 明令禁止预置。

**做**：断言**跨页复用机制**：

1. 原图 3（管线 page_2）先跑，对 `ヤミツキ茸` 产生一条 `decisions` 条目（`status="tentative"`，带 `evidence[{page, region_id, surface_seen, match}]`）。
2. 原图 8（管线 page_7）跑时，该表达的译名被强制注入（可在请求构造层断言）。
3. 原图 8 的 `translations` 里 `ヤミツキ茸` **不再以片假名出现**，且所用词**等于第 3 页那条决定的 `translation`**（逐字相同，具体是哪个词由实现决定）。
4. `residue` 为空 ⇒ 高置信度路径。

**低置信度分支**另立一个测试，用**注入的假 LLM**（两次都吐残留）驱动，断言：`residue` 非空、`low_confidence` 非空且 `reason == "residue_after_one_repair"`、`status == "ok"`（不阻塞）、且红榜包含该页。

---

## 8. 测试策略

原则：**夹具小、不提交漫画/权重/密钥/workspace/生成页**；先红后绿。

### 8.1 单元/契约层（新增或扩充，全部用假 LLM，不烧 API）

| 测试 | 断言 |
|---|---|
| `test_workstate_decisions` | `decisions` 读写往返；首次记录 `status="tentative"`；evidence 结构完整 |
| `test_decisions_idempotent` | 同一 `(surface, page, region_id)` 跑两次，evidence **不重复追加**（需求 7） |
| `test_decisions_revision_keeps_old_evidence` | 修订译名后旧 evidence 仍在、旧译名不静默消失 |
| `test_decision_retrieval_ignores_page_distance` | 第 3 页记的决定在第 8 页被检索命中（**纯函数层，无 LLM**） |
| `test_decision_injected_as_binding_rule` | 命中项出现在构造出的 `system_extra` 里，且措辞是"必须使用"级 |
| `test_new_decisions_from_translate_response` | 假 LLM 返回 `decisions` ⇒ 落进 `work_state.decisions` |
| `test_residue_triggers_exactly_one_repair` | 残留 ⇒ LLM 调用次数 == 2；不残留 ⇒ == 1 |
| `test_residue_after_repair_sets_low_confidence` | `low_confidence` 内容、`reason`、`attempted`、`evidence_pages` |
| `test_low_confidence_does_not_block_stage` | `guarded` 仍返回 `status="ok"`；inpaint 不被跳过 |
| `test_quality_audit_surfaces_low_confidence` | 红榜文本包含该页 |
| `test_translate_fingerprint_includes_work_state` | 改 `work_state.json` ⇒ `is_fresh` 变 False（需求 7） |
| `test_terms_take_precedence_and_conflict_recorded` | `terms` 与 `decisions` 同名不同译 ⇒ `terms` 生效 + `memory_conflict` 非空 |

**回归锚点**：`test_translation_input_contract.py` 已锁"多行 region 在 LLM 边界仍是单个 JSON 元素"，扩 `decisions` 时不得破坏它。

### 8.2 聚焦回归测试先红后绿（任务书硬要求）

实现前先写、并**记录它们红**的测试：
- `test_decision_retrieval_ignores_page_distance`
- `test_residue_triggers_exactly_one_repair`
- `test_translate_fingerprint_includes_work_state`

这三个分别对应两个缺陷 + 顺带缺陷，能各自独立复现行为。

### 8.3 全量门禁

- `uv run python -m pytest -q`
- `npm run check`
- 收尾走仓库唯一入口 `state.py finish`（内置全量质检；需如实报告它实际跑了哪些检查）

### 8.4 真实样本验证（Q3 决策：范围 0–15，新 work-id）

- 源：`D:\我的汉化\汉化作品\东方\幻想乡居民们的赚钱大法！\原图`（**只读**）
- 新 work-id，写入被忽略的 `workspace/`；**不碰** `gui-1790591328680`（保留为 before 基线）；**不写** `原图`／`新建文件夹`
- 分两趟（Q6 决策 = (b) 再 (a)）：
  1. `--stages detect,ocr,translate --start-page 0 --end-page 15`：拿跨页复用与残留修复的语义证据
  2. 通过后补 `inpaint,typeset`：证明低置信度不阻塞下游、产物真的出图
- 用 `scripts/run_pipeline.py` / `artifact.py` / `peek.py` / `gen_report.py`，不手工拼旧阶段脚本
- before 侧不需要重跑：`gui-1790591328680` 已经是有磁盘证据的失败基线（page_4 `n_residue=3`、`status=ok`、片假名渲进成品）

### 8.5 不得声明的通过

- 测试通过 ≠ 语义证据存在。最终报告逐条对应任务书八项结果，给测试名／命令结果／产物查询，**无法观察的标为未知**。
- 不得凭配置或 Agent 自述判定通过。
- 不得声称"第 7 页残留"被修复 —— 它未复现（§1）。

---

## 9. 与任务书八项结果的对应

| # | 任务书要求 | 本设计的落点 |
|---|---|---|
| 1 | 第 3 页首次出现的未知表达产生可追溯暂定决定，无需静态词典 | §5.1 步骤 4/7：`decisions` 条目 `status="tentative"` + evidence；不依赖 `data/thbwiki_master_dict.json` |
| 2 | 第 8 页超出三页窗口仍能检索并优先复用 | §5.2 按表达检索，页距不存在；§7 验收 1–3 |
| 3 | OCR 小差异靠通用规范化 + 模型语义判断关联；原形/别名/证据页/region/置信度/来源可追踪 | §5.3 三层次 + `decisions` 的 `aliases`/`evidence`/`source`；置信度以 `match: exact|model_judged` 表达**证据类型**，不设数值阈值 |
| 4 | 日文残留不能静默 `ok`：一次有证据修复；仍不确定则最佳译文 + 机器可读低置信度 | §5.1 步骤 5–6、§5.5、§4.3 `low_confidence` |
| 5 | 暂定决定能因新证据自动增强或修订，无需人工确认 | §5.4 修订写回 `work_state.json`；无审批门槛 |
| 6 | 生产代码/prompt/专用规则不硬编码 `ヤミツキ茸`/`迷幻菇`/`クズ`/`人渣` | 设计里无任何词的硬编码；§7 明确拒绝断言具体词。**实现期以 grep 断言验证**（见下） |
| 7 | 缓存命中、断点重跑、再次翻译不无声丢失/重复污染/错误提升 | §6 幂等键 + fingerprint 纳入 `work_state.json`；§8.1 两个测试 |
| 8 | 人工 PSD 兜底不成为运行依赖，本阶段不做 PSD 反向抽取 | 设计不含 PSD 读取；`psd` 只在 typeset 阶段被写 |

**需求 6 的验证方式**：实现完成后跑
`git grep -n -e ヤミツキ茸 -e 迷幻菇 -e クズ -e 人渣 -- src/ tests/ scripts/`，
要求**生产代码、prompt、专用规则零命中**（测试夹具与文档中的事实记录不算 —— 但需逐条说明哪一处命中属于哪一类，不接受笼统豁免）。

---

## 10. 反向证据：现有 25 个相关测试不会被破坏的理由

| 现有测试 | 为什么不受影响 |
|---|---|
| `test_stage3_minimal.py::test_prompt_parts_terms_injected` | 该断言（`system_extra == ""`）成立的前提是"术语预替换后无注入"。新增的 `work_id` 参数设计为**可选默认 `None`**，而此测试不传 `work_id` ⇒ 无 `decisions` ⇒ `system_extra` 仍为空。**该测试无需修改**（实现计划 Self-Review §4 已核对） |
| `test_stage3_minimal.py::test_build_prefetch_context_passthrough` | 同上：三位置参数调用，`work_id` 省略 ⇒ `refined_canon == canon` 原样透传 |
| `test_stage3_minimal.py` 长度不符 → 1 call + 全空 | 不变（不加重试；修复是"残留驱动的一次调用"，不是长度不符重试） |
| `test_translate_station.py` 三例 | 不变；`residue == []` 仍成立 |
| `test_guardrails.py` | `mechanical_guardrails` 语义不变 |
| `test_artifact_cache.py` 各阶段 code_files 存在 | 新增文件必须同时进 `registry.code_files`，否则该测试会红 —— 这是**期望的**护栏 |
| `test_context_semantic_transfer.py` | 3 页窗口保留、未改代码 ⇒ 不变 |
| `test_quality_audit.py` | `PageFlags` 复用、不新增字段族 ⇒ 现有断言不变 |
| `test_workstate.py` | `TEMPLATE_WORK_STATE` 加键需同步该测试的 schema 断言；显式更新 |

---

## 11. 未决 / 明确不在本阶段

- **不做** PSD 反向抽取（任务书需求 8）。
- **不做** 跨书全局记忆。
- **不做** 乱序调和器、分层修复、独立记忆 CLI、数值置信度模型（§2.1）。
- **不解决**：`contains_japanese` 对 `・`/`ー` 的假阳性（lesson `L48`）。它是**误报**方向，与本任务"漏报后静默出货"方向相反，且本次原图 8 的残留是真片假名。**记录为已知约束，不在本阶段修**。
- **不解决**：`glossary_violations` 停用（`stage3_minimal.py:354`）。本设计不重新启用 `check_glossary`；语义绑定由 `decisions` 承担。
- **待真实跑验证的未知**：原图 3 在**新 work-id** 下会选 `成瘾菇` 还是 `迷幻菇` —— 未知，且**设计上不重要**（§7 不断言）。原图 8 是否因此在第一次调用就干净（无需修复）也未知；若干净，则低置信度分支只能由 §8.1 的注入式假 LLM 测试 + 单元测试证明，真实跑证明的是高置信度路径。这一点在最终报告里必须如实标注，不得用配置或自述顶替。
