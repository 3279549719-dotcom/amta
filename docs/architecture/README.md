# AMTA 架构文档（C4 三视图）

> 生成方式：c4-codebase-architecture skill（从代码证据反推，观察/推断分离）。
> 日期：2026-08-27 · Scope：本仓（amta/）= **AMTA 编排层**，不含 koharu 本体（引擎是外部系统）。

## 1. Scope 声明

本仓库是漫画翻译自动化的**编排/执行层**（Python），不包含引擎实现：
- **amta/ 仓内**：工位脚本（00_run_all → 01_detect → 02_ocr → 03_translate → 04_inpaint → 05_typeset）+ 共享库（src/amta/）+ 状态（workspace/、state/）
- **仓外依赖**（外部系统）：koharu v0.59.1 headless（引擎，:4000）、本地 llama-server（OCR，:8118）、DeepSeek API（翻译/VLM）、DashScope（可选 OCR）、DSH 会话（导演）

## 2. 观察（Observed，来自代码）

- 入口：`scripts/00_run_all.py` 编排 6 个数字前缀工位脚本（断点续跑，文件存在=跳过）
- 共享库：`src/amta/` 20 个模块（koharu_client / pipeline / runner / ocr_engines / translate / workstate / tickets / geometry / metrics / inpaint_strategy / typeset_* 等）
- 状态：`workspace/<work_id>/{raw, artifacts, state}`，state 三件套（touhou_knowledge / work_state / open_questions）+ suggestions + failure_log + pipeline_log
- 外部端点（代码实测）：
  - koharu：`http://127.0.0.1:4000/api/v1`（REST）
  - llama-server：`http://127.0.0.1:8118/v1`（OpenAI 兼容 OCR）
  - DeepSeek：`.env` CHAT_BASE_URL（翻译 + vision-exp VLM 评审）
  - DashScope：`https://dashscope.aliyuncs.com/compatible-mode/v1`（可选 OCR）
- 依赖（第三方 import）：requests / PIL / uv（管理）——零其他运行时依赖（ADR-009/015/018）

## 3. 推断（Inferred）

- DSH 会话是**导演**：决策/翻译判断/修复决策/验收，通过 CLI 调用工位脚本（会话驱动架构，ADR-003/014）
- koharu 是**引擎**：检测/OCR/擦除/排版的原语执行者（REST + 像素 mask 机制）
- 数据流是**文件即状态**：工位间不共享内存，靠 artifacts/ JSON 传递（ADR-013/018）

---

## 4. System Context（系统上下文）

```mermaid
flowchart LR
    subgraph 用户侧
        USER["人类用户<br/>(读成品/给反馈)"]
        DIRECTOR["DSH 会话 = 导演<br/>(决策/终审/验收)"]
    end
    subgraph AMTA["AMTA（本仓）"]
        EXEC["amta Python 执行器<br/>(工位脚本 + 共享库)"]
    end
    subgraph 外部系统
        KOHARU["koharu v0.59.1 headless<br/>引擎 REST :4000"]
        LLAMA["llama-server<br/>本地漫画 OCR :8118"]
        DS["DeepSeek API<br/>翻译 + vision VLM"]
        DASH["DashScope<br/>可选 OCR"]
    end
    USER -->|"读成品/评审"| DIRECTOR
    DIRECTOR -->|"决策/验收"| EXEC
    EXEC -->|"REST 检测/OCR/擦除/排版"| KOHARU
    EXEC -->|"OCR 请求"| LLAMA
    EXEC -->|"翻译/语义评审"| DS
    EXEC -.->|"可选"| DASH
    KOHARU -.->|"提示/反馈"| DIRECTOR
```

## 5. Container 视图（容器）

```mermaid
flowchart TB
    subgraph AMTA["AMTA 编排层"]
        ORCH["00_run_all<br/>编排器（断点续跑）"]
        S01["01_detect<br/>4 detector 并集"]
        S02["02_ocr<br/>OCR + 墨量/类型"]
        S03["03_translate<br/>DeepSeek 翻译"]
        S04["04_inpaint<br/>擦除"]
        S05["05_typeset<br/>排版渲染"]
        LIB["src/amta 共享库<br/>20 模块"]
        WS["workspace/<work_id>/<br/>raw+artifacts+state"]
    end
    ORCH --> S01 --> S02 --> S03 --> S04 --> S05
    S01 -.-> LIB
    S02 -.-> LIB
    S03 -.-> LIB
    S04 -.-> LIB
    S05 -.-> LIB
    LIB --> WS
```

## 6. Component 视图（amta 容器内部）

```mermaid
flowchart LR
    subgraph 工位链["工位脚本（薄 CLI）"]
        A["00_run_all"]
        B["01_detect"]
        C["02_ocr"]
        D["03_translate"]
        E["04_inpaint"]
        F["05_typeset"]
    end
    subgraph 共享库["src/amta/（逻辑收敛，ADR-012）"]
        G["koharu_client<br/>REST 封装 16 方法"]
        H["ocr_engines<br/>OCR 抽象（本地/DashScope）"]
        I["translate<br/>chat client + 护栏 + 工具"]
        J["geometry / metrics / images<br/>纯函数"]
        K["workstate / tickets<br/>状态 + 工单"]
        L["typeset_engine / fonts<br/>排版"]
    end
    A --> B --> C --> D --> E --> F
    B -.-> G
    C -.-> H
    D -.-> I
    C -.-> J
    D -.-> K
    F -.-> L
```

## 7. 待澄清问题（Open Questions）

1. 03.5 语义评审（VLM 逐 region 四维评分）是独立脚本 `scripts/translate_semantic_check.py`，未进 00_run_all 主链（由导演按需触发）——是否应成为正式工位？（v2 计划 D11 讨论中）
2. v2 计划新增 02.5 audit / 02.6 repair 工位（两趟式），本图是 v2 前的现状视图。

## 8. 建议下一步

- v2 落地后更新本图（加 02.5/02.6 节点）
- 可补 Code 级视图（按需）
- 生成 `.mmd` 源文件便于复用（本文件内嵌即源）
