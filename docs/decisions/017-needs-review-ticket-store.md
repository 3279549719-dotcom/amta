# 017 — needs_review 工单机制：TicketStore 状态机 + 判例库回写（维修手册逻辑）
> ⚠️ 2026-09-01 更新：本文描述的 legacy 翻译通道（translate_tools/repair_failed/stage3_planner/page_judge/translate_semantic_check）已清理，现行架构见 stage3_minimal.py。本文保留作历史决策参考。

## Context

- ADR-014/016 导演角色归位（2026-08-26）后：DeepSeek 自修复（repair_failed.py）修不掉的进 needs_review；外部只处理这类工单，需要持久化、可追溯的交接形态，不能再散落在 failure_log。
- 借鉴 CMMS（计算机化维护管理系统）的工单状态机 + 「维修手册」归档：处理结论回写判例库，同类问题下次自动修复/评审直接参考，越修越聪明。

## Decision

1. **工单状态机**：`src/amta/tickets.py` TicketStore——`open → in_progress → resolved / rejected`；JSON 文件即状态（`<state_dir>/tickets.json`，每本一个，符合 ADR-013 per-work 结构）。
2. **自动开单**：repair_failed 达 max_rounds 仍 FAILED → `--tickets` 自动 create（region_id/reason/auto_rounds/source/kind）。
3. **关键词粗分类**：`classify_kind` → term_conflict（术语/护栏/glossary 冲突）/ false_positive（误报：语境/编造/补全）/ hard_case（难句兜底）；kind 可人工修正。
4. **归档闭环（维修手册）**：resolve/reject 时处理结论自动回写 `testsets/case_law.json`（verdict=pass + reason + lesson）——导演处置即沉淀判例。
5. **导演协议**：term_conflict → 校准 work_state/glossary 后重跑修复；false_positive → reject 驳回维持原译；hard_case → resolve 人工终审。

## Consequences

- ✅ 导演处置有持久化载体 + 判例自动沉淀；needs_review 不再散落。
- ✅ 分类（kind）可驱动后续通知/看板（微信推送待接）。
- ⚠️ 判例回写按 region_id 覆盖（同 region 新 case 覆盖旧 case）；scores 字段暂空。
- ⚠️ 测试：tests/test_tickets.py 5 条（状态机/分类/判例回写），fastcheck 全绿。
