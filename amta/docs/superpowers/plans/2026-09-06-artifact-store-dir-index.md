# 2026-09-06 artifact_store：目录即索引（dir-as-index）+ store 薄门

## 目标

消灭「靠 glob / 平铺命名反查」找产物。机制定死为 **目录即索引**：
- 布局：`artifacts/<stage>/page_11.json`（stage 即目录，文件名退成 `page_N.json`）
- 查询：`store.path(stage, page)` / `store.pages(stage)` 直取或一次 listdir，**禁止再写新 glob**
- 兼容：旧平铺 `artifacts/page_11_detection.json` 作为只读回退，**不迁移存量文件**

纯重构布局层，不改各阶段语义、不改产物内容、不动缓存判定逻辑（fingerprint 仍是 output_path 兄弟文件）。

## 决策（grill 定案）

- **Q1 形态 = a：目录即索引**，无 manifest、无第三份状态。文件系统是物理事实，listdir 永远为真。
- **Q3 兼容 = a（并入）**：新布局只向前写；读侧先新后旧回退；存量 workspace 不迁移、照读。
- 图片类产物（clean/final/crops）已是子目录，**不并入本次改动**（保持 `clean/`、`final/`、`crops/` 原状）。

## 关键事实（与草稿表格的矛盾，执行时必须遵守）

1. **`pipeline.py` 没有 20-30 处硬编码**。它已走 `artifact_paths(...).get(stage.produces)`（orchestrator/adapters 同）。
   真正路径知识散落在两处：
   - `src/amta/artifacts.py:114 artifact_paths()` —— 唯一需改的"布局定义处"（JSON 阶段产物 + fingerprint 推导）
   - 读侧直接拼 f-string / glob 平铺名的站点（见下）
2. **station 不是"不用改"**：
   - `ocr_station.py:164` 直接 `write_json(artifacts_dir / f"{page}_canon.json")` **绕过 artifact_paths**——必须收编为 `artifacts.save_canon(...)` 或新增 `canon_path` 参数，否则 canon 永不进子目录。
   - `detect_station.detect_page` 已有 `out_path` 参数（`target = out_path or (out_dir / f"{page}_detection.json")`），但 orchestrator `adapters/detect.py` 现在只传 `out_dir`、不传 `out_path`——需改 adapter 传参（detect 就进子目录了，station 本体可不改）。
   - ocr/translate/inpaint/typeset 的 adapter 走 `artifact_paths()`，自动跟随新布局；translate/inpaint/typeset 落盘处已显式用 artifact_paths，无需动 station。
3. **指纹跟随 output_path 位置**：`artifact_cache.fingerprint_path = output_path.with_suffix(... + ".fingerprint")` 是兄弟文件，output_path 变子目录 → 指纹自动在子目录旁。缓存判定不变。

## 读侧 glob / f-string 清单（必须全部收编，否则子目录化后读不到）

| 文件 | 现状 | 改为 |
|---|---|---|
| `src/amta/artifacts.py:114-125` | `artifact_paths()` 平铺 7 键 | 返回 `<dir>/<page>.json`（JSON 6 键）；`crops` 目录键维持；保留旧路径推导以支撑回退 |
| `src/amta/artifact_cache.py:216` `invalidate_cache_for_page` | glob `{page}_*.fingerprint` | 遍历 store 目录删对应页指纹 |
| `src/amta/artifact_cache.py:225-226` `cache_status` | glob `*.json` / `*.fingerprint` | 遍历 store 目录（+旧平铺）统计 |
| `src/amta/ocr_station.py:164` | 直接写 canon 平铺 | `save_canon` 或 canon_path 参数 |
| `orchestrator/adapters/detect.py` | 只传 out_dir | 传 `artifact_paths()["detection"]` 作 out_path |
| `report/assembler.py:128-132` `load_from_workspace` | f-string 拼 5 路径 | `artifact_paths()` + 旧路径回退（找不到子目录文件→查平铺旧名） |
| `report/final_report.py:46-48` | f-string 拼 3 路径 | 同上收编 |
| `src/amta/stage3_minimal.py:97-99` | glob `page_*_translation.json` | store.pages("translation") + 旧平铺回退 |
| `src/amta/pre_scan.py:52` | glob `page_*_canon.json` | store.pages("canon") + 回退 |
| `scripts/00_run_all.py:57,79` | glob canon/translation 平铺 | 只读旧布局 workspace 时维持；新布局经 store（见范围决策） |
| `src/amta/report/stages/*`（detect/ocr/filter/translate） | `_load_json(Path)` 直读 | 无需改（路径由调用方传入） |

## 新增 `src/amta/artifact_store.py`

```
class ArtifactStore:
    def __init__(self, artifacts_dir): ...
    LAYOUT = {detection, canon, translation, needs_review, inpaint, typeset}  # 子目录 JSON
    LEGACY_NAME = {detection: "{page}_detection.json", ...}                    # 旧平铺名推导
    def path(self, stage, page) -> Path          # 新布局确定路径（<dir>/<page>.json）
    def resolve(self, stage, page) -> Path|None  # path 若不存在→回退 LEGACY_NAME，仍不存在→None
    def pages(self, stage) -> list[str]          # 目录 listdir 出 page_key 列表（新+旧并集）
    def exists / clear_stage(stage) / clear_page(page)
    @classmethod from_artifacts_dir(...)
```

- `artifacts.py:artifact_paths()` 改为委托 store.path 或直接内联新布局；**契约仍是那 7 键 dict**（crops 键 = `artifacts_dir/"crops"`，维持）。
- 回退封装一个 helper（如 `resolve_artifact(artifacts_dir, page, stage)`），供 report/assembler、final_report、stage3、pre_scan 共用，不重复写「新→旧」查找逻辑。
- `store.pages()` 语义：`listdir(stage_dir)` 出 `page_N.json` 的 stem；兼容旧平铺 = 根目录 glob `{stage}.json` 并集。**glob 只允许出现在 store 模块内部一处**，模块外禁止。

## 测试更新

- `tests/test_artifacts.py`：artifact_paths 期望值改新布局；加 resolve 回退用例。
- `tests/test_artifact_cache.py`：fingerprint 兄弟路径断言改子目录；cache_status/invalidate 遍历语义。
- `tests/test_orchestrator_smoke.py` + fakes：临时目录布局跟随（若 fakes 造平铺名则改造 store.path）。
- report/convergence、context_semantic、report 引擎测试若手拼平铺名 → 改走 store/artifact_paths 或新布局。
- 新增 `tests/test_artifact_store.py`：path/resolve/pages/clear 单测（新布局、旧回退、混合两态）。

## 范围决策

- **做**：artifacts.py 布局、artifact_store.py、上述读侧收编、ocr_station canon 收编、detect adapter 传 out_path、测试对齐。新写的产物一律进子目录。
- **不做**：存量文件迁移脚本、图片子目录并入、trace/semantic 布局（`*_trace.json`/`*_semantic.json`/`*_judge.json` 非产物契约，保持平铺）、版本管理、manifest。
- **00_run_all.py**：保留旧平铺读（它在读旧 workspace 存量时不能断）；**不迁移**，是否收编视工作量在 C 里定，收编也必须经 store 共用 helper。

## 验证

- 分层：`uv run python scripts/fastcheck.py`（compile+ruff+pyright+pytest）；新增/改的测试全绿。
- 行为等价探针：造一个双态临时 workspace（旧平铺 2 页 + 新布局 2 页），断言 store.resolve / pages / report 组装都能读两态。
- 回归跑 orchestrator smoke（7 测）确认 pipeline 读新布局正常、缓存判定不受影响。
- 不夹带：不改 station 语义、不改产物 schema、不搬存量、不新建第三方 glob。

## 落地顺序（每步独立 commit + fastcheck）

1. 新增 `artifact_store.py` + `artifacts.py:artifact_paths` 改新布局 + resolve 回退 helper → 跑 test_artifacts 对齐
2. ocr_station canon 收编 + detect adapter 传 out_path → 定向测试
3. report/assembler + final_report + stage3 + pre_scan 收编读侧 → report/convergence + context 测试
4. artifact_cache cache_status/invalidate 遍历 store → test_artifact_cache 对齐
5. 新增 test_artifact_store 双态用例 → 全量 fastcheck 绿
6. （收尾）验证 report 对旧 workspace 仍可读（gen_report 冒烟）

## 执行方式

本计划由 headless `claude -p` 在 worktree `amta-wt-artifact-store`（分支 feat/artifact-store-dir-index）执行，
逐 chunk 走 fastcheck，提交只在 feature 分支。合入 main 留给人。
