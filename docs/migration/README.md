# 工作台资产清单与恢复说明（2026-10-25）

这是当前 Windows 工作台的可追溯备份，不是已验证的 macOS 安装包。代码快照包含本次开始前已有的五个未提交文件修改；没有改写其业务逻辑。原分支为 `fix/vertical-kinsoku-columns`，基点 `bebbf5c`。

## GitHub 上分别保存什么

- 代码与依赖声明：分支 `codex/migration-inventory-2026-10-25`；`pyproject.toml`、`uv.lock` 是依赖重建依据。
- 模型与旧运行组件：[Release migration-assets-2026-10-25](https://github.com/3279549719-dotcom/amta/releases/tag/migration-assets-2026-10-25)。逐个 ZIP 可以独立下载。
- [assets.json](assets.json)：每个模型/运行组件的用途、来源、归档文件、还原位置、逐文件大小与 SHA-256。
- [SHA256SUMS.txt](SHA256SUMS.txt)：下载后核对 ZIP 完整性。
- [environment-windows.json](environment-windows.json)：当前 Python 和已安装包版本的观察快照，不能直接当作 Mac 安装清单。
- [upload-verification.json](upload-verification.json)：2026-10-26 核对 GitHub 服务端摘要；8 个 ZIP 加两个清单文件全部匹配本地 SHA-256 和大小。8 个 ZIP 共 1,471,353,365 字节，包含 85 个原始模型/运行组件文件。
- 根目录 `.env.example`：无密钥的管线配置模板。实际 `.env` 不入库。
- [performance-and-mac.md](performance-and-mac.md)：历史耗时、PSD 调查、Apple silicon 适配边界。

## Property list

| 资产 | 当前用途 | 备份/恢复方式 |
|---|---|---|
| `src/`、`scripts/`、`tests/`、GUI 静态资源、工程文档 | 当前执行器与工作台 | Git 分支/Release 对应代码提交 |
| `pyproject.toml`、`uv.lock` | Python 依赖与解析锁 | Git；新机重建环境 |
| RT-DETR-v2 `detector.onnx` | 文字/气泡检测 | `ctbd.zip` → `models/CTBD/` |
| CTD `comictextdetector.pt.onnx` | 擦字像素蒙版 | `ctd.zip` → `models/CTD/` |
| Hayai OCR 模型、配置、分词器、自定义 Python 模块 | 默认本地 OCR | `hayai.zip` → `models/hayai-ocr-v2/`；原机在 `E:\models\hayai-ocr-v2` |
| LaMa-Manga 权重 | 漫画擦字修复 | `lama-manga.zip` → `models/lama-manga/`；当前执行代码仍找 D 盘旧路径，见下文 |
| Baberu ONNX 与分词器/加载代码 | 可选 OCR | `baberu.zip` → `models/baberu-ocr/` |
| `big-lama.pt` | 旧通用修复模型；环境门卫仍检查其存在 | `big-lama.zip` → `models/big-lama.pt`；不是当前主线实际修复权重 |
| llama.cpp b10582 的 exe/DLL/原压缩包 | 旧本地模型实验组件，非默认流水线 | `llama-cpp-windows.zip`；仅保留，不在 Mac 使用 Windows 二进制 |
| simple-lama-inpainting 0.1.2 源码与原包 | 旧参考源码 | `simple-lama-source.zip` |
| SigLIP2 processor 配置缓存 | Hayai 初始化辅助配置 | 当前 OCR 代码能本地生成；不备份下载缓存 |
| 云端翻译和可选 VLM 配置 | 远程 API | 模板入 Git；密钥通过密码管理器或私下迁移 |
| Photoshop | 创建可编辑 PSD | 在新机合法安装；不上传商业软件安装目录 |
| 中文字体 | 正文/独白/强调/拟声排版 | 当前使用微软雅黑、楷体、微软雅黑粗、方正舒体，回退黑体；新机安装有授权的字体并建立映射，不上传系统字体文件 |
| `.venv`、`.uv-cache`、Python 字节码、HF 下载缓存 | 可重建机器状态 | 不上传；以锁文件重建 |
| 原图、译文、clean/crops/final/PSD、作品状态与人工修订 | 用户作品资产 | 本次不上传；单独物理备份 `workspace/` 及所需 `output/` |

每个资产的精确字节数与校验值以 `assets.json` 为准。归档保留本地已有版本，不自动升级到上游最新模型。附带的第三方来源与许可说明不改变各项目原许可。

此快照只覆盖当前 checkout 和清单明确列出的外部模型，不声称归档其他 worktree、私人浏览器/AI 客户端设置或其他项目。

备份验证详情见 [VALIDATION.md](VALIDATION.md)：656 项测试通过，但已有类型检查与项目记忆过期问题未消失，故以迁移快照 prerelease 发布。

## 当前路径债务：不能只下载 ZIP 就假定能启动

1. Hayai 支持进程环境变量 `HAYAI_OCR_MODEL`，可以指向解压后的完整目录。不能只搬权重、漏掉 tokenizer 和自定义模型 Python 文件。
2. LaMa-Manga 查找路径仍写在 `src/amta/inpaint/local_lama_inpainter.py` 的 `_LAMA_MANGA_GLOB`：`D:\我的汉化\workflow\koharu_data\models\**\lama-manga.safetensors`。当前没有已生效的 LaMa-Manga 路径环境变量。新 Windows 可临时复原该目录布局；Mac 必须先实现可配置路径。
3. 环境门卫检查 `big-lama.pt`，没有完整验证主线实际使用的 LaMa-Manga、CTD、Hayai；“环境检查通过”不足以证明模型全部齐备。
4. `.env` 的文件读取只覆盖调用方明确读取的键。`HAYAI_OCR_MODEL`、`VISION_MODEL`、`DASHSCOPE_BASE_URL`、`PHOTOSHOP_PATH` 等 `os.environ` 读取项需要放入进程环境；仅复制到 `.env` 不保证生效。
5. Photoshop 启动器和字体默认值仍以 Windows 为前提；Mac 适配还未完成。

## Windows 恢复顺序

1. 克隆并切换到快照分支，或检出 Release 指向的提交；不要把默认 `main` 当成本次快照。
2. 安装 Git、uv、支持项目的 Python 3.12。执行 `uv sync --locked` 重建依赖。CPU/CUDA/Apple silicon 的包选择需按实际平台验证，旧 `.venv` 不可移植。
3. 从 Release 下载所需 ZIP 与 `SHA256SUMS.txt`。Windows 使用 `Get-FileHash -Algorithm SHA256`，macOS 使用 `shasum -a 256`，逐项核对。
4. ZIP 内已经含有 `models/...` 相对目录，解压到项目根。仅在新环境解压，避免覆盖正在运行的模型。
5. 设置 Hayai 的进程变量；按照上一节处理 LaMa-Manga 的旧查找路径。当前门卫仍需 `big-lama.pt`。
6. 复制 `.env.example` 为 `.env`，私下填写新机 API 密钥。其余进程变量按平台设置。不要提交真实 `.env`。
7. 安装 Photoshop 和所需字体，检查路径。启动 `uv run python scripts/run_gui.py`。
8. 手工导入一张备份的代表页，执行翻译、PNG 导出和 PSD 导出；打开 PSD 检查底图、可编辑文字、字体与竖排。此验收必须在新机实际执行，当前 Windows 备份不能替代它。

## 备份完成不等于迁移完成

本次不改变本机生产模型路径、不升级推理后端、不重写 PSD 导出。Mac 上应先完成路径、字体、Photoshop 调用与 MPS 探针，然后再决定提高分辨率或替换模型。API 密钥和有授权要求的商业软件/字体必须单独处理。
