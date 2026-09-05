# koharu 上游深度调研详报（subagent 2 完整报告）

> 来源：subagent 29affab6 最终报告全文归档（GitHub API + 源码 + 0.61.2 tag 文档 + web_search 交叉验证）
> 与主报告 `01-调研报告与集成编排方案.md` §2 互为补充。

## 1. 项目概览
- 仓库：https://github.com/mayocream/koharu（2025-04-09 创建）；约 5,345 stars / 352 forks
- License：当前 main 为 **MIT OR Apache-2.0 双许可**（注意：本地 v0.59.1 是 GPL-3.0，中途换过许可）
- 文档：https://koharu.rs（含 ja-JP / zh-CN）；活跃度极高，近一月几乎每天发版，最新 **0.77.5（2026-08-21）**
- 发布：GitHub Releases（Win/Linux 64 + Apple silicon）、`winget install koharu`、`brew install --cask koharu`

## 2. 架构（当前 main）
单体桌面应用（Tauri + CEF webview），**无独立后端**：「Koharu is one desktop application, not a web client attached to a separate server」。
- 前端 Next.js/React（9 语言 i18n）→ packages/bridge（specta 生成协议）→ crates/koharu-app（commands/lifecycle/Agent 托管）
- 领域：koharu-scene（内存语义工程模型）/ koharu-storage / koharu-pipeline → koharu-ml → 原生运行时 / koharu-translator / koharu-renderer → koharu-rasterizer / koharu-canvas(WASM+WebGPU) / koharu-psd / koharu-agent(Codex)
- 推理后端：koharu-torch / koharu-llama / koharu-diffusion（各配 -sys 动态加载）；koharu-runtime 从 HF/GitHub/PyPI 下载运行时包
- 硬件：CUDA 13.0 / ROCm / Metal / Vulkan / CPU；构建门槛高（Tauri CEF git 分支 + LLVM 22.1.8 + Ninja + Bun 1.3.14 + Rust 1.97.1）

## 3. 端到端流水线
`Detection → OCR → Translation`，同时 `Detection → Inpainting`
- 导入 PNG/JPEG/WebP/CBZ/ZIP/RAR/PDF → `.khrproj`
- Detection：Koharu Layout RF-DETR Seg 2XL（+ comic-text-detector、speech-bubble-yolo、manga-text-mask、pp-doclayout-v3 等）
- OCR：PaddleOCR VL 1.6（默认）/ Manga OCR / Baberu OCR（+ pp-ocr-v6、mit48px-ocr、拟声词识别）
- Translation：本地 GGUF（LFM 2.5、Ministral 3、Gemma 4、Qwen 3.5/3.6/3.8）+ 云端（Atlas Cloud/OpenAI/Gemini/Claude/Grok/MiniMax/DeepSeek/OpenRouter/OpenAI-compatible/LM Studio）+ MT（DeepL/Google/彩云）；支持 vision input 整页直翻、thinking、工程级指令
- Inpainting：LaMa（默认）/ AOT-GAN / FLUX.2 Klein / RORem mixed
- 排版：harfrust + skrifa，自动字号/字体回退/竖排 CJK/RTL/描边填充；导出 PNG / PSD
- 处理粒度：整工程/选中页/选中元素，阶段子集可选，增量提交，一次一个 job

## 4. 自动化钩子（当前 main）
- **(a) CLI 二进制（需 cargo 构建）**：`koharu-pipeline run`（单图全流水线，翻译仅本地 LLM，无工程/PSD）；`koharu-translator translate`（纯文本翻译，全 provider + `--json` + env/keyring 密钥）；`koharu-ml` 每模型一个 bin
- **(b) 内置 Codex Agent**：ChatGPT 账号 device-code 登录；15 宿主工具（inspect_project/view_page 视觉/rename|move|delete_pages/add_text_box/set_source_text/set_translation/set_typography/set_geometry/set_visibility/delete_elements/move_element/run_pipeline）；不能导入/导出/管凭证；一次一个请求
- **(c) 33 个 Tauri IPC 命令**（webview 内）：lifecycle 11 / editing 12 / processing 2 / output 2 / fonts 2 / preferences 3 / agent 6 / canvas 9；外部只能走 CEF 远程调试（debug 构建 127.0.0.1:4000）+ CDP
- **(d) 配置文件**：`~/.koharu/config.toml`（不存密钥）；密钥在 OS keyring；工程 `Documents/Koharu/*.khrproj`；缓存 `<cache>/koharu/packages/`
- **(e) 旧版 0.61.2 全自动面**（详见主报告 §2.2）：REST /api/v1 + MCP /mcp + SSE /events + Docker ghcr.io/mayocream/koharu:0.61.2

## 5. 限制与缺口
1. 0.63+ 无 headless/无服务端/无 Docker（[#904](https://github.com/mayocream/koharu/issues/904)）；NAS/容器用户被卡 0.61.2
2. 一次一个 job（process 直接报错）；Agent 一次一个请求
3. Agent 绑 ChatGPT/Codex 登录
4. run CLI 仅本地 LLM、单图、无工程语义、无 PSD；构建重
5. translate CLI 只做文本翻译；**批量翻译曾有质量劣化（[#225](https://github.com/mayocream/koharu/issues/225)）**
6. 无 hot folder / watcher / webhook / 插件 API（[#107 ComicReadScript 脚本集成](https://github.com/mayocream/koharu/issues/107) open）
7. config.toml 手改可阻止初始化；keyring 是 headless 历史痛点（#287/#308/#520）
8. 官方要求导出前人工 review；并行/上下文仍在演进（[#873](https://github.com/mayocream/koharu/issues/873) open）
9. 首次运行下载数 GB 运行时/模型，依赖外网
10. **遥测：koharu-metrics（machine id + Sentry）**，自动化部署注意隐私

## 6. 自动化方案矩阵
| 方案 | 可行性 | 说明 |
| --- | --- | --- |
| A. 钉 0.61.2 headless + REST/MCP/Docker | ✅ 最接近全自动 | 缺后续改进，老 GPU/Vulkan bug |
| B. 内置 Agent 面板（Codex） | ✅ 官方支持 | 需 ChatGPT 账号、GUI 常开、串行、无导入/导出 |
| C. 编译 CLI（pipeline run + translate） | ✅ 可脚本化 | 单图/纯文本，无批量工程，需自建编排 |
| D. CDP 驱动 webview（debug 127.0.0.1:4000） | 🟡 需实验 | 官方调试路径；release 端口未知；UI 自动化脆弱 |
| E. 把 crates 当库自建包壳层 | 🟡 工程量大 | 等于复刻 koharu-rpc |

> 注：本机实际情况是 v0.59.1（比 0.61.2 更早、同属 server 世代、GPL-3.0、带完整 REST+MCP），方案 A 的等价物本机已就绪且被本地轮子验证过。
