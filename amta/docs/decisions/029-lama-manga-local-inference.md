# 029 — Lama-Manga 本地推理 + 整页模式：替代 Koharu HTTP Inpaint

日期：2026-09-04　状态：已采纳（5页验证通过，测试10/10通过，已合并main）

## 决策

1. **Inpaint 引擎从 Koharu HTTP 切换为本地 lama-manga 推理**：不再依赖 Koharu HTTP 服务（消除网络开销和服务依赖），直接在本地用 PyTorch 加载 lama-manga.safetensors 权重推理。
2. **推理模式采用整页推理**：将整页图片缩小到 1024 宽后整页送模型推理，再放大回原尺寸，只替换 mask 区域。不采用裁剪推理（对每个文字框单独裁剪），因为裁剪推理在复杂背景（渐变、网点、阴影）会产生可见的白色方框。
3. **预处理/后处理严格对齐 Koharu 参考实现**：
   - 输入归一化：`[0, 1]`（`/255.0`），不是 `[-1, 1]`
   - 输出激活：模型输出过 `sigmoid`（Koharu 在 final_conv 后显式调用）
   - mask 二值化：`>0 = 1`
   - 混合方式：mask 羽化（Gaussian blur kernel=21）后 alpha 混合
4. **模型结构**：FFC ResNet Generator（n_blocks=18, ngf=64, n_downsampling=3, input_nc=4, output_nc=3），从 BallonsTranslator 复制，989 个权重键 100% 匹配 lama-manga.safetensors。
5. **不采用**：
   - big-lama 模型（通用自然图像模型，完全去不掉漫画文字）
   - 裁剪推理（有白色方框问题）
   - 精修 mask（refine_text_mask，在裁剪图上失效，文字去不掉）
   - Stable Diffusion Inpainting（速度太慢，不适合批量处理）

## 理由

- **速度瓶颈诊断**：A/B 实验确认 Koharu HTTP 开销是主因——Baseline 平均 152.5s/页，其中 HTTP 往返和服务端排队占绝大部分；本地推理可大幅降低。
- **模型不匹配发现**：big-lama（通用自然图像模型）完全去不掉漫画文字——它把漫画文字当成"线条的一部分"，认为不需要修复。必须用 lama-manga（漫画微调模型）。
- **lama-manga 已在本地**：`D:\我的汉化\workflow\koharu_data\models\...\lama-manga.safetensors`（194.9MB），不需要下载。
- **预处理/后处理 bug 修复**：最初本地推理出现严重黑/白噪点（模型输出范围 [-307, 8755]），根因是输入归一化用了 [-1,1] 而非 [0,1]，且输出缺少 sigmoid。对齐 Koharu 源码后修复（详见 L38）。
- **整页推理 vs 裁剪推理**：裁剪推理（padding=64）在复杂背景产生白色方框，整页推理（缩小到1024宽）无方框，质量接近 Baseline（详见 L39）。
- **最终验证结果**（5页×1次，整页推理）：
  - 速度：平均 19.7s/页（page11=17.3s, page12=18.6s, page13=20.1s, page14=20.8s, page15=21.9s）
  - 比 Baseline（152.5s/页）快 **87%**
  - 质量：无噪点、无白色方框、网点背景完美贴合，接近 Baseline
  - 测试：10/10 通过（test_lama_ffc 4/4 + test_local_lama_inpainter_manga 4/4 + test_exp_p1_manga 2/2）

## 备注

- **与 ADR-020 的关系**：ADR-020 定义了 Koharu inpaint 链路（put_mask ×2 → run_pipeline → fetch_inpainted）。本 ADR 是其**替代方案**——不再走 Koharu HTTP，直接本地推理。Koharu inpaint 链路仍可作为 fallback/对照组。
- **detection 漏检问题**：部分竖排文字/拟声词未被 detection 检测到（如 page11"はっ……"、page13"ビッ"），Baseline 也有同样问题，属于 detection 模块而非 inpainting 问题，后续可单独优化 detection 召回率。
- **速度优化空间**：当前用 CPU 推理（PyTorch 不支持 DirectML），如有 GPU 可进一步加速；也可探索 ONNX 导出 + ONNX Runtime 加速。
- **相关经验教训**：L38（模型推理预处理/后处理必须对齐参考实现）、L39（整页推理 vs 裁剪推理）。
- **设计文档**：`docs/superpowers/specs/2026-09-04-inpaint-speed-ab-test.md`（第十二节记录最终结果和决策）。
- **实验报告**：飞书公开链接 https://my.feishu.cn/file/PV2WbA6jroH04dxb0rncTkOznpe
- **commit 记录**：
  - `d39bc76` FFC ResNet 模型定义
  - `5992466` LocalLamaInpainter 支持 lama-manga
  - `debce0b` 修复 build_rect_mask h/w swap bug
  - `e9956b6` 对齐 Koharu 预处理/后处理
  - `9b2513d` 整页推理模式（最终方案）
  - `cefbfc9` 设计文档更新（第十二节）
  - 已合并到 main
