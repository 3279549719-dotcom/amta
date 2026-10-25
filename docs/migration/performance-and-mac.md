# 性能证据与 Mac 迁移边界

## 历史阶段计时

以下是仓库已有记录，不是 2026-10-25 重新运行的性能测试，也不是 Mac 性能预测。

来源：2026-09-26 [ADR-036](../decisions/036-short-vocalization-translation-loop.md)。

| 样本 | 检测 | OCR | 翻译 | 修复 | PNG 排版 | 总计 |
|---|---:|---:|---:|---:|---:|---:|
| p64，9 个区域 | 3.61s | 34.91s | 1.01s | 31.59s | 3.17s | 75.03s |
| p52+p43，两页合计 | 8.90s | 43.75s | 2.04s | 92.65s | 2.14s | 149.97s |

总时长含调度开销，与分项和有差额。原始 `round2-p64-evidence.json` 本次未找到；以上是保留的 ADR 记录，不能称为本次重新核验的原始日志。typeset 指 PNG 排版，不是 Photoshop PSD 导出。

更接近当前 CTD 气泡蒙版路线的记录来自 2026-09-27 [ADR-037](../decisions/037-bubble-ctd-mask-lama.md)：第一页 CPU 修复约 105s，其中 CTD 约 76s、LaMa 约 25s；记录称 CTD ONNX session 初始化约 60s。文中后续页 15–25s 和 GPU 5–15s 是**估计**，不得当作实测结论。这说明“inpaint 很慢”包含蒙版与模型初始化成本，不能全部归因于 LaMa 前向计算。

独立试验 [ADR-035](../decisions/035-p62-background-protection-loop.md) 记录 CTD 14.50s，全页 LaMa 60.61–81.28s；620×814 crop LaMa 22.97s，但修复画面未通过，不能只看速度宣布优化成功。

## PSD 的已确认代码路径

PSD 从已有 clean 图和 typeset JSON 构建，不重跑 OCR、翻译或 LaMa。后台请求通过全局锁串行调用 Photoshop，JSX 打开底图、逐项创建可编辑文字层、查找字体、设置样式/竖排、保存 PSD。每 0.5s 检查完成标志；300s 是超时，不是固定延迟。浏览器每 3s 轮询，固定的“启动约 1～3 分钟”文案不是计时证据。

可能耗时的位置是应用启动/脚本交接、逐文字层操作、保存和队列等待；没有分段测量前，不能断定字体扫描或模型是 PSD 慢的原因。

## 2026-10-25 PSD 实测（10-26 完成整理）

同一张 1400×2428 页面、9 个可编辑文字层，使用当前导出代码，仅在生成的临时 JSX 中加入时间标记。第一次开始前 Photoshop 未运行；第一次成功后立刻做第二次。两个 PSD 均成功生成，原始数据见 [psd-timings.json](psd-timings.json)。原图、文字内容、临时 PSD 和 JSX 不上传。

| 分段 | 首次启动 | Photoshop 已运行 |
|---|---:|---:|
| 请求到 JSX 第一条时间标记 | 186.13s | 13.34s |
| 打开底图 | 10.58s | 1.86s |
| 创建与配置 9 个文字层 | 40.75s | 41.28s |
| 保存 PSD | 10.36s | 3.52s |
| 端到端 | **253.42s** | **62.60s** |

分项不覆盖偏好保存/恢复、脚本其余操作、文档关闭、轮询等全部开销，因此不能直接把分项相加当作总计。字体查询耗时包含在文字层段内，两个样本都不足一秒，不能把它当作当前首要瓶颈。

**限制：**当时另一进程正在压缩和校验模型备份，CPU/磁盘有竞争；这是两次带负载观察，不是隔离性能基准，也不能据此宣称所有机器都要等 253 秒。第一条标记之前的时间还包含脚本交接和读取少量应用状态，不足以细分 Photoshop 内部初始化原因。

本次证据支持的结论：冷启动/交接是首次等待的大头；PS 已运行后，逐层创建与配置文字仍占约 41 秒。此路径没有调用 OCR/LaMa，因此购买推理 GPU 不会直接消除这段等待。

优先优化方向：

1. 用户准备导出时复用已经启动的 Photoshop，明确显示启动/建层/保存阶段；两次观测表明避免冷启动值得优先验证，精确收益需无备份负载复测。
2. 对文字层创建和属性赋值单独剖析；比较批量 ActionDescriptor 与当前逐属性 DOM 设置，保持可编辑文字和竖排结果一致。此方案尚未实现或测速，不承诺目标秒数。
3. 长期可评估直接写入含可编辑文字的 PSD，避开启动 PS 的步骤；不能用文字栅格化来偷换用户要求，跨编辑器兼容性必须验收。
4. 字体查询缓存属于次要优化；按本次数据不应先投入大量时间。

本次没有修改生产导出逻辑，也没有声称 PSD 已提速。

## Apple silicon 的支持现状

Mac mini 和 Mac Studio 都是台式电脑，需要搭配显示器和输入设备；MacBook Air/Pro 才是笔记本。

| 环节 | 当前代码在 Apple silicon 上的预期路径 | 必须验证/修改的内容 |
|---|---|---|
| RT-DETR 检测 | 默认 CPU | Core ML 等后端尚未接入，不能因买 Mac 自动获得 GPU 加速 |
| Hayai OCR | 安装的 Hayai 库有 CUDA → MPS → CPU 选择 | 自定义解码和算子必须做真实 MPS 推理验证 |
| 云端翻译/VLM | 网络 API | 密钥、网络、接口可用性；本机 GPU 不直接加速云端处理 |
| CTD 蒙版 | 明确 CPU provider | 初始化成本、Core ML 后端适配与输出一致性 |
| LaMa-Manga | 工位只选 CUDA 或 CPU，因此 Mac 当前选 CPU | 实现 MPS 路由前验证 FFT、复数、插值、显存占用和输出；不能承诺只换 device 即成功 |
| 排版 | Windows 字体目录不存在 | 字体路径/字体名映射、缺字和竖排回归 |
| PSD | Windows 专用启动器 | Mac Photoshop 的脚本调用、完成/错误反馈与可编辑文字检查 |

LaMa 的 FFC 实现包含 `torch.fft.rfftn`、`torch.complex`、`torch.fft.irfftn`。当前代码把推理宽度限制为 1024，且不按设备改变；买更强的 Mac 不会自动解除限制。

不要把“有 Apple GPU”误写成“支持 CUDA”；PyTorch 的 Apple GPU 后端是 MPS/Metal。此次没有 Apple 硬件实测，不能给出 mini/Studio 上的秒数或确定加速倍数。先用目标机器完成同页端到端测试，再按预算、内存和实际吞吐做选择。

官方资料（2026-10-25 查阅）：

- [Apple Mac mini](https://www.apple.com.cn/mac-mini/)
- [Apple Mac Studio](https://www.apple.com.cn/mac-studio/)
- [PyTorch MPS backend](https://docs.pytorch.org/docs/2.14/notes/mps.html)
- [GitHub Release 文件限制](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
