# 后三阶段（Mask / Inpainting / Typesetting）开源项目调研与方案决策

> **日期**：2026-09-01
> **调研人**：Patrick + AI 协作
> **分支**：feat/detect-label-fullrun-p14p18
> **状态**：方案 B 已选定，待实现

---

## 一、调研背景

前三阶段（detect → OCR → translate）已完成重构，采用 station 深模块 + 瘦脚本架构，翻译层默认走 stage3_minimal（2 LLM calls/page, zero tools, zero loops）。

后三阶段（mask 生成 → inpainting 擦除 → typesetting 排版）目前只有基础版：
- Mask：矩形 + pad=4（`scripts/04_inpaint.py:_build_mask()`）
- Inpaint：气泡涂白 + 其他调 koharu lama-manga（`src/amta/inpaint_strategy.py`）
- Typeset：PIL 二分字号 + 贪心折行 + 避头尾（`src/amta/typeset_engine.py`）

存在的问题：
1. 框外字（标题、旁白、SFX）用漫画体效果奇怪
2. 译文太长时字号缩到 12px 仍放不下
3. 矩形 mask 可能擦不干净或擦多了
4. 旋转文字直接画矩形会贴歪

为决定后三阶段的实现方案，调研了四个已 clone 的开源项目的源码。

---

## 二、调研对象

| 项目 | 路径 | Stars（约） | 特点 |
|------|------|------------|------|
| manga-image-translator | `reference/repos/manga-image-translator/` | ~30k | 最完整，自动化程度最高 |
| koharu | `reference/repos/koharu/` | ~3k | Rust 实现，性能最好，AMTA 已用其引擎 |
| comic-translate | `reference/repos/comic-translate/` | ~5k | 中等复杂度，ONNX 友好 |
| BallonsTranslator | `reference/repos/BallonsTranslator/` | ~3k | 排版最专业，但带 GUI，需人工交互 |

所有项目均为完整 shallow clone（文件完整，无 git 历史）。

---

## 三、Mask 生成（Text Segmentation）对比

### 3.1 各项目做法

| 项目 | 做法 | 核心文件 | 代码量 |
|------|------|---------|--------|
| **manga-image-translator** | 两种模式：①`fit_text` 精确模式=连通域分析+CRF精修+多边形匹配+膨胀；②`fill_rect` 简单模式=直接画矩形。输入需要检测器的 raw_mask + 文本行四边形 | `manga_translator/mask_refinement/text_mask_utils.py` | ~200行（精确模式） |
| **comic-translate** | 无独立 mask 模块，直接用检测器输出或简单矩形 | — | 极低 |
| **BallonsTranslator** | 检测器（comic-text-detector）本身输出精确多边形 mask，直接用，不额外精修 | `ballontranslator/modules/textdetector/` | 极低（复用检测器） |
| **koharu** | 两个独立模型：`comic-text-detector-seg`（文本分割）+ `speech-bubble-segmentation`（气泡分割），分别生成 segment mask 和 bubble mask | `pipeline.py` ENGINE_NEEDS | 中（双模型） |

### 3.2 关键发现

1. **除了 manga-image-translator，其他三个项目都直接用检测器的 mask 输出**，不额外做精修。
2. manga-image-translator 的精确模式也需要检测器先给一个 raw_mask 作为基础，不是从零生成。
3. CRF 精修（DenseCRF）是 manga-image-translator 独有的，复杂度高，依赖 pydensecrf 库。
4. AMTA 当前用的 RT-DETR-v2 检测器（ogkalu/comic-text-and-bubble-detector）本身就是做文本/气泡检测的，输出里有 bbox，但当前代码 `_detect_single()` 只保留了 bbox，把 label 和可能的 mask 丢了。

### 3.3 对 AMTA 的启示

- **优先复用检测器的输出**，不重新画矩形。RT-DETR-v2 的 bbox 已经比手工矩形精确。
- **不做 CRF 精修**——复杂度高，收益不确定，且其他三个项目都没做。
- 如果检测器输出了 mask（comic-text-detector 有 segmentation 输出），直接用；没有就用 bbox + 少量膨胀。

---

## 四、Inpainting（擦除）对比

### 4.1 各项目做法

| 项目 | 支持的引擎 | 默认引擎 | 架构 | 特殊能力 |
|------|-----------|---------|------|---------|
| **manga-image-translator** | 6种：AOT/Lama MPE/Lama Large/SD/none/original | AOT | Lama用FFC（快速傅里叶卷积） | 多引擎可切换 |
| **comic-translate** | 4种：AOT/Lama/MI-GAN/base | AOT | Lama支持ONNX+Torch双后端 | CROP/RESIZE两种高清策略（大图省显存） |
| **BallonsTranslator** | 7种：AOT/FFC/Flux/Lama/Patch Match/LLM inpaint/default | default | Lama也是FFC架构 | Patch Match是传统算法（不需要模型） |
| **koharu** | 不自实现，调用外部引擎：lama-manga/flux2-klein/aot-inpainting | lama-manga | 外部服务 | 双mask输入（segment+bubble） |

### 4.2 关键发现

1. **四个项目的 Lama 模型代码几乎一模一样**——都是 FFCResNetGenerator（快速傅里叶卷积残差网络），manga-image-translator 和 BallonsTranslator 的代码可以直接对照。说明这是行业标准做法。
2. **所有项目的输入契约都一样**：`image + mask → 修复后的图`。没有一个项目让 LLM 参与擦除决策。
3. **comic-translate 的 CROP 策略值得参考**：如果页面很大，按 mask 的连通域裁剪出一个个小区域，逐个修复后贴回原图。省显存、速度快、修复质量更高（模型看到的上下文更聚焦）。
4. **AMTA 现在用的 koharu lama-manga 是对的**——koharu 本身就调这个引擎，专门针对漫画优化。
5. Patch Match（BallonsTranslator）是传统算法，不需要模型，适合简单背景的修复，但复杂纹理效果差。

### 4.3 对 AMTA 的启示

- **保持现有策略**（气泡涂白 + 其他调 lama），这是对的。
- **加一个空转判断**：如果本页没有 inpaint 类区域（全是气泡），跳过 koharu server 启动，直接全页涂白。
- **mask 用检测器的 bbox**，不重新画矩形。
- 如果整页 lama 慢/显存不够，可以学 comic-translate 的 CROP 策略，按区域裁剪修复。

---

## 五、Typesetting（排版）对比

### 5.1 各项目做法

| 项目 | 渲染技术 | 横竖排 | 字号算法 | 特殊能力 |
|------|---------|--------|---------|---------|
| **manga-image-translator** | freetype（直接字形渲染，非PIL） | 支持，完整CJK竖排标点转换表~100项 | 基于原文字号+译文长度比例调整 | **自动扩框**（译文长了自动扩大文本框）、透视变换贴回旋转框、前景/背景色自动从原图取色 |
| **comic-translate** | PIL | 支持 | 未明确 | hyphen_textwrap断字折行 |
| **BallonsTranslator** | Qt QTextDocument（富文本引擎） | 支持，横排/竖排独立模块 | 自适应 | 最专业：字体格式/效果/变形，但**带GUI，需人工交互** |
| **koharu** | Rust（skrifa+harfrust字体塑形） | 支持，WritingMode枚举 | 行优化算法（带惩罚值，类似TeX） | 性能最好，Unicode双向文本，ICU归一化 |

### 5.2 关键发现

1. **manga-image-translator 的排版是四个里面最适合自动化的**，有几个 AMTA 现在没有但很有用的能力：
   - **自动扩框**（`resize_regions_to_font_size()`）：译文比原文长时，自动扩大文本框（横排扩宽、竖排扩高），而不是缩小字号。这解决了"译文太长放不下"的核心问题。
   - **透视变换贴回**（`findHomography + warpPerspective`）：原文的文本框可能是旋转的，把渲染好的文字精确贴回旋转的框里。
   - **自动取色**（`fg_bg_compare()`）：从原图取前景色和背景色，不是写死黑字白底。
   - **freetype 渲染**：比 PIL 渲染质量高，支持更复杂的字体特性。
2. **BallonsTranslator 的排版虽然最专业，但不适合 AMTA**——它是给 GUI 编辑器用的，用户可以手动拖拽、调整每个文本框。AMTA 要的是自动化流水线。
3. **koharu 的排版性能最好，但 AMTA 已经在用 koharu 了**——它的 renderer 是 Rust 写的，如果愿意接 koharu 的渲染 API 可以直接用，但 AMTA 现在是自己用 PIL 写的排版，接 koharu renderer 需要改架构。
4. 所有项目的排版决策（字号、横竖排、折行）全是纯代码/算法，没有一个让 LLM 参与。

### 5.3 对 AMTA 的启示

- AMTA 现在的排版基础（二分字号+贪心折行+避头尾）够用，但缺三个关键能力：
  1. **字体分类**：框内用漫画体、框外用黑体。这个用检测器的 label（text_bubble/text_free）就能解决，零成本。
  2. **自动扩框**：译文长了扩框而不是缩字。可以从 manga-image-translator 抄思路。
  3. **旋转框的透视贴回**：留到后续，优先级低。
- 不做 freetype 渲染（PIL 够用）、不做自动取色（大部分漫画是黑字白底）、不接 koharu renderer（改架构成本高）。

---

## 六、方案对比与决策

### 方案 A：极简维持（当前基础版）
- **Mask**：矩形 + pad=4
- **Inpaint**：气泡涂白 + 其他调 lama
- **Typeset**：PIL 二分字号 + 贪心折行
- **优点**：已经能用，零额外开发
- **缺点**：①框外字用漫画体效果奇怪；②译文长了字号缩太小；③旋转文字贴歪；④矩形 mask 可能擦不干净
- **适合**：先跑通全流程看整体效果

### 方案 B：中等改进（选定 ✅）
- **Mask**：复用检测器的 bbox 输出，不重新画矩形
- **Inpaint**：保持现有策略（涂白+lama），加"全页无 inpaint 区域则跳过 lama"判断
- **Typeset**：
  - 字体分类：用检测器的 label（text_bubble=框内→漫画体，text_free=框外→黑体）
  - 自动扩框：译文长了自动扩大 bbox（抄 manga-image-translator 的 `resize_regions_to_font_size` 思路）
  - 保持现有的二分字号+贪心折行
- **优点**：①解决字体分类问题（零成本，检测器已分好）；②解决译文太长问题（自动扩框而非缩字）；③开发量适中，核心逻辑可从 manga-image-translator 抄
- **缺点**：①自动扩框可能导致文本框重叠（需处理交集）；②旋转框的透视贴回还没做（留到后续）
- **适合**：当前阶段——已有基础版，想显著提升效果但不想搞太复杂

### 方案 C：全面专业（抄 manga-image-translator + koharu）
- **Mask**：检测器 mask + CRF 精修
- **Inpaint**：多引擎切换 + CROP 策略
- **Typeset**：freetype 渲染 + 自动扩框 + 透视贴回 + 自动取色，或直接接 koharu Rust renderer
- **优点**：效果最好，接近专业汉化组水平
- **缺点**：①开发量巨大（CRF精修~200行、freetype排版复杂、透视变换需调参）；②很多能力可能用不上；③维护成本高
- **适合**：长期目标，等基础流程稳定后再逐步升级

### 决策：方案 B，分两步落地

**第一步（零成本，立刻能做）**：
1. 把 RT-DETR-v2 检测器的 label（text_bubble/text_free）从检测结果里保留下来，一路传到排版阶段
2. 排版阶段读 label：text_bubble 用现有漫画体，text_free 用黑体/宋体
3. inpaint 阶段加"全页无 inpaint 区域则跳过 lama"判断

**第二步（中等开发，解决译文太长）**：
1. 抄 manga-image-translator 的 `resize_regions_to_font_size` 思路：译文比原文长时，自动扩大 bbox（横排扩宽、竖排扩高），而不是缩小字号
2. 加简单的重叠检测：如果扩框后和其他框重叠，回退到缩小字号

**方案 C 的能力（CRF精修、freetype、透视贴回、自动取色）先不做**，等方案 B 跑通、看了实际效果再决定要不要升级。

---

## 七、关键源码引用

### Mask 生成
- manga-image-translator 精确 mask：`reference/repos/manga-image-translator/manga_translator/mask_refinement/text_mask_utils.py`（`complete_mask()` 函数，连通域+CRF+多边形）
- manga-image-translator mask 入口：`reference/repos/manga-image-translator/manga_translator/mask_refinement/__init__.py`（`dispatch()` 函数，fit_text/fill_rect 两种模式）

### Inpainting
- manga-image-translator Lama FFC 架构：`reference/repos/manga-image-translator/manga_translator/inpainting/inpainting_lama.py`（`FFCResNetGenerator` 类）
- manga-image-translator inpaint 入口：`reference/repos/manga-image-translator/manga_translator/inpainting/__init__.py`（`INPAINTERS` 字典，6种引擎）
- comic-translate CROP/RESIZE 策略：`reference/repos/comic-translate/modules/inpainting/base.py`（`InpaintModel.__call__()`，HDStrategy.CROP/RESIZE）
- comic-translate Lama ONNX 后端：`reference/repos/comic-translate/modules/inpainting/lama.py`（`LaMa` 类，onnx/torch 双后端）
- BallonsTranslator Lama FFC：`reference/repos/BallonsTranslator/ballontranslator/modules/inpaint/lama.py`（`FFCResNetGenerator`，与 mit 同源）

### Typesetting
- manga-image-translator 自动扩框：`reference/repos/manga-image-translator/manga_translator/rendering/__init__.py`（`resize_regions_to_font_size()` 函数）
- manga-image-translator 渲染入口：`reference/repos/manga-image-translator/manga_translator/rendering/__init__.py`（`dispatch()` → `render()`，透视变换贴回）
- manga-image-translator CJK 竖排标点：`reference/repos/manga-image-translator/manga_translator/rendering/text_render.py`（`CJK_H2V`/`CJK_V2H` 字典，~100项）
- koharu Rust 布局引擎：`reference/repos/koharu/crates/koharu-renderer/src/layout.rs`（`WritingMode` 枚举、行优化算法）
- BallonsTranslator 排版引擎：`reference/repos/BallonsTranslator/ballontranslator/ui/text_engine/layout.py`（基于 Qt QTextDocument）

---

## 八、待办

- [ ] 方案 B 第一步：检测器 label 传递 + 字体分类 + inpaint 空转判断（见实现计划）
- [ ] 方案 B 第二步：自动扩框 + 重叠检测回退
- [ ] 跑 5-10 页完整流水线，验证方案 B 效果
- [ ] 根据效果决定是否升级到方案 C 的部分能力
