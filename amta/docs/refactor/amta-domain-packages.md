# amta 领域子包重构（refactor/amta-domain-packages）

把 `src/amta` 顶层约 40 个平铺模块按领域归入 8 个子包，公开导入路径重铺为
`from amta.<pkg>.<mod> import ...`，全仓库（amta 内部 / scripts / tests）import 同步重写。

## 分层（包级严格只依赖下层，无环）

| 包 `src/amta/<pkg>/` | 内容模块 | 依赖 | 层 |
|---|---|---|---|
| `common/` | paths·metrics·geometry·images·config·pipeline_log·punctuation_align·workstate·tickets·evalkit | 无（包内互依） | L0 叶子/通用 |
| `stores/` | artifacts·artifact_store·artifact_cache | common | L1 产物/存储 |
| `backends/` | chat_client·koharu_client·koharu_blocks·runner·ocr_engines·vlm_verify | common | L1 引擎/传输 |
| `guards/` | guardrails·glossary·canon_schema·suggestions·term_dict·term_replace·rule_filter·pre_scan·vlm_filter | common·stores·backends | L2 护栏/术语/VLM |
| `inpaint/` | inpaint_strategy·inpaint_station·local_lama_inpainter·_lama_ffc·_lama_model·_lama_util | common·backends | L2 Stage4 |
| `typeset/` | typeset_engine·typeset_render·typeset_station·fonts | common·stores | L2 Stage5-6 |
| `translation/` | translate·stage3_minimal·translate_station | common·stores·guards·backends | L3 Stage3 |
| `stations/` | detect_station·ocr_station | 各下层域 | L4 工位入口 |

原已存在的 `memory/`、`orchestrator/`、`report/` 保持原位。

## 迁移做法（可重现）

1. `git mv` 每一扁平模块 → 归属包。
2. AST + 文本双通道 import 重写器（scripts/probes/_migrate2.py）：
   - 文本：`amta.<旧矮名>` → `amta.<pkg>.<旧名>`（词边界、幂等）。
   - AST：`from amta import a, b as c` 精确再分层/保留别名，**保留函数内 import 的缩进**；
     需以 `utf-8-sig` 读入（14 个源文件带 BOM，否则 ast.parse 失败而漏改写）。
3. 每包新建 `__init__.py`（docstring 说明成员 + 依赖），根 `amta/__init__.py` 清空为壳。

## 验证

- `compileall`（src/amta/scripts/tests）全过。
- 全仓 441 个 pytest 收集无 import 错误。
- 迁移域单测批（~20 个 test_*）：172 passed；全量 pytest 430 passed / 8 failed / 3 skipped。
- 8 失败均为 HEAD 已存在（非本次引入）：`report/` 子包残缺态
  （`refine_text_mask` 未定义的四条 render 测试）、VLM refine 移除后的陈旧测试
  （`translate_station` llm_vlm、final_integration tri-state）、缺模型实验探针
  （exp_p1_manga ModuleNotFoundError）。佐证：迁移文件的 diff 纯 import 行改写，无函数体/签名变更。
- 遗留：`report/` 子包在 HEAD 即处残缺态（`refine_text_mask`/`raw_img_gray`/`btype` 等死引用
  与多条 F821），与本次顶层归类无关、未纳入；已修 `report/stage4_report.py` 一处兼容别名
  `extract_text_free_boxes`（ADR-031 旧名退化 aliasing，消除 `import amta.report` 崩溃）。
