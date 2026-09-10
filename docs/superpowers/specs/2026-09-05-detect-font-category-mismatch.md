# 已知问题：检测分类体系与字体分类体系断层

**日期**: 2026-09-05
**状态**: 待处理（留待下次迭代）
**严重度**: 高 — 影响排版质量，字体选择全部退化到默认值

## 问题描述

Orchestrator 全阶段端到端跑通后（pages 11-15 验证），发现 **Detect 阶段的分类输出与 Typeset 阶段的字体注册表完全不匹配**，导致所有文字排版时都退化到默认字体（微软雅黑），设计文档中规划的4级字体映射（对白/独白/呼喊/SFX）实际从未生效。

## 实际数据证据

### Detect 阶段输出

`detection.json` 中 `bubble_type` 只有两种值：

```
text_bubble  — 气泡内文字
text_free    — 气泡外自由文字
```

### OCR (canon) 阶段输出

`canon.json` 中：
- `category` 字段：**全部为 `None`**（OCR 不产生分类）
- `bubble_type` 字段：继承自 detect，同样只有 `text_bubble` / `text_free`

### 字体模块期望的分类

`src/amta/fonts.py` 的 `_level_for()` 函数期望以下 category：

| category 值 | 字体级别 | 实际字体 | 描边 |
|-------------|---------|---------|------|
| `overlay_text` | overlay_narration | 楷体 (simkai.ttf) | 2.5px 白描边 |
| `sfx` | sfx | 方正舒体 (FZSTK.TTF) | 2.5px |
| 含 `！`/`!` | shout | 微软雅黑粗体 (msyhbd.ttc) | 无 |
| 其他（默认） | dialogue | 微软雅黑 (msyh.ttc) | 无 |

### 实际发生的事

`typeset_station.py` 调用 `resolve_font(category or "dialogue_bubble", text)`：
1. `category` 全是 `None` → 全部走默认值 `"dialogue_bubble"`
2. `"dialogue_bubble"` 不匹配 `"overlay_text"` → 不用楷体
3. `"dialogue_bubble"` 不匹配 `"sfx"` → 不用方正舒体
4. 只有带感叹号的文字触发 `"shout"` → 微软雅黑粗体

**结果：5页验证中，楷体和方正舒体一次都没被调用过。** 旁白、SFX、角色名全部用微软雅黑渲染。

## 根因分析

两层断层：

### 断层1：检测分类太粗

RT-DETR 检测器只训练了 `text_bubble` / `text_free` 两个类别，没有区分：
- 对白气泡 vs 旁白框 vs 内心独白
- SFX（拟声词）vs 角色名标签 vs 自由文本
- 呼喊/强调 vs 普通对话

`text_free` 是一个大杂烩，里面混着 SFX、旁白、角色名、页码等，全部被当成同一种处理。

### 断层2：OCR 不识别字体风格

原文中的字体视觉信息（手写体、楷体、粗体、艺术字等）在 OCR 阶段全部丢失。OCR 只输出文字内容，不输出字体风格标签。翻译后无法根据原文风格选择对应字体。

## 影响

- 排版质量退化：所有文字统一微软雅黑，缺乏原文的字体层次感
- 独白/压脸字没有楷体和白描边，视觉上和对白无区别
- SFX 没有手写体，拟声词效果丢失
- `text_free` 区域（包括 SFX、角色名）甚至可能不被 inpaint（检测器虽然检到了，但 inpaint 只处理有 mask 的区域）

## 可能的解决方向（待评估）

### 方向A：VLM 细分类（推荐）

在 OCR 之后、翻译之前插入一个 VLM 分类步骤，对每个区域做细分类：
- 输入：原图 + bbox 裁剪
- 输出：`dialogue` / `narration` / `sfx` / `character_name` / `shout` 等
- 写入 canon.json 的 `category` 字段
- 优点：准确率高，能识别字体风格
- 缺点：增加一次 VLM 调用，耗时增加

### 方向B：规则推断

基于位置、形状、文字特征做规则分类：
- 竖排长框 → 旁白
- 大字/艺术字 → SFX
- 气泡内 → 对白
- 含感叹号 → 呼喊
- 优点：零额外耗时
- 缺点：准确率有限，边界情况多

### 方向C：检测器重训练

重新训练 RT-DETR，增加细分类别（dialogue_bubble / narration_box / sfx / character_name）。
- 优点：检测阶段直接输出细分类
- 缺点：需要标注数据，训练成本高

### 方向D：字体风格 OCR

升级 OCR 模型，使其同时输出文字内容和字体风格标签。
- 优点：一步到位
- 缺点：当前 OCR 引擎（hayai/baberu）不支持，需要自研或换模型

## 相关文件

- `src/amta/fonts.py` — 字体注册表（4级映射 + 降级链）
- `src/amta/typeset_station.py` — 排版工位，调用 resolve_font
- `src/amta/detect_station.py` — 检测工位，RT-DETR 只输出 text_bubble/text_free
- `src/amta/orchestrator/registry.py` — 管线注册，当前无 filter/classify 阶段

## 验证方式

修复后重新跑 pages 11-15 端到端，检查：
1. `canon.json` 中 `category` 字段不再全是 None
2. `typeset.json` 中 `rendered_items` 的 `font_family` 出现 simkai.ttf / FZSTK.TTF / msyhbd.ttc
3. 视觉上旁白有楷体+白描边，SFX 有手写体
