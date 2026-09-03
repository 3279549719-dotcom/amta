# AGENTS.md

> 规范本体是 `CLAUDE.md`（本文件仅作入口，避免双份漂移）。CLAUDE.md 全文自动加载，含核心事实 + 坑 + 渐进式加载表。

AMTA：会话驱动漫画翻译自动化——DSH 会话=导演，amta Python=执行器，koharu v0.59.1 headless（:4000）=引擎。翻译走 03_translate 脚本直调 DeepSeek API（ADR-014，弃 koharu 内 llm 引擎）；VQA 走 vqa() 抽象（describe_image）。

**最致命坑**：钉 0.59.1；`comic-text-detector-seg` 只细化已有文字框，前置 detector 漏检则 OCR/mask/inpaint 全漏（`pp-doclayout-v3` 是文档模型，框外字漏检嫌疑元凶）。

细节（接口/流程/坑全表）→ 读 `CLAUDE.md`；按需技能见 `.dsh/skills/`（DSH 原生技能根，进 skill catalog 按需加载）。

---

## Python 运行规范（强制）

**所有 Python 命令必须通过 `uv run` 执行，禁止直接使用 `python` 或 `python.exe`。**

### 为什么
- 系统 Python 是 3.14，没有安装任何项目依赖（requests / pillow / numpy / hayai-ocr）
- 项目虚拟环境 `.venv` 是 Python 3.12，所有依赖已安装
- 直接用 `python script.py` 会报 `ModuleNotFoundError`
- `uv run` 会自动识别 `.venv`、使用正确 Python 版本、加载所有依赖
- 项目包在 `src/` 下，运行模块时需设 `PYTHONPATH=src`（项目脚本内部已自动处理）

### 正确写法
```powershell
# 运行脚本
uv run python scripts/04_inpaint.py --work-id xxx --det xxx.json --raw xxx.jpg --out xxx.json

# 运行模块（需设PYTHONPATH）
$env:PYTHONPATH="src"; uv run python -c "import requests; print(requests.__version__)"

# 运行 pytest
uv run pytest tests/ -v
```

### 错误写法（禁止）
```powershell
python scripts/04_inpaint.py ...          # ❌ 用了系统 Python 3.14，无依赖
python -c "import requests"                 # ❌ 同上
.venv\Scripts\python.exe script.py          # ⚠️ 能用但冗长，统一用 uv run
```

### 常用短命令（通过 run.ps1）
```powershell
.\run.ps1 inpaint --pages 11-20    # 跑 inpaint 阶段
.\run.ps1 report                     # 生成 stage4 报告
.\run.ps1 all --pages 1-5           # 跑全管线
.\run.ps1 python -c "..."           # 透传任意 python 命令（自动 uv run）
```
