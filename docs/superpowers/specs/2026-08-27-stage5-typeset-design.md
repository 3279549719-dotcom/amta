# Stage 5: Typesetting 引擎 设计文档

> **日期**：2026-08-27
> **决策**：Patrick 拍板 Q1——**自研 Pillow 排版引擎**（弃 koharu-renderer），Q2 默认系统字体跑 MVP（字体注册表预留可插拔，后续可加汉化字体）
> **依据**：stage4-6 blue master.html（Gemini 蓝图 Stage 5）+ 2026-08-27-stage46-guidance-spec.md（§2 竖排漏洞）+ ADR-019 契约

## 1. 目标

`05_typeset` 工位：消费 clean 图 + translation.json + detection bbox，在气泡/文字区域内渲染中文译文，产出 final.png + TypesetArtifact（JSON，供 Stage 6 QA 消费）。

零新增第三方依赖（Pillow 已有）。纯算法，CPU 单页 <0.1s。

## 2. 输入契约（消费）

| 输入 | 来源 | 关键字段 |
|---|---|---|
| `artifacts/clean/<page>_clean.png` | 04_inpaint | — |
| `artifacts/<page>_translation.json` | 03_translate | `translations: {region_id: text}` |
| `artifacts/<page>_canon.json` | 02_ocr | `[{region_id, bbox?, category?, sub_tier?}]` |
| `artifacts/<page>_detection.json` | 01_detect | `regions[].bbox` + `regions[].category` + `image_meta` |

> ⚠️ 契约缺口：canon 目前**没有 bbox**（02_ocr 只透传 category/sub_tier）。bbox 在 detection.json 的 `regions[].child_lines[].bbox`（展平后 = `blocks[].bbox`）。
>
> **对齐方案（零契约改动）**：canon 条目已带 `node_id`（02_ocr 写入）→ 05 用 `canon.node_id` 关联 `detection.blocks[].node_id` 取 bbox。空 OCR 跳过的条目天然对齐（node_id 是检测器 UUID，无顺序依赖）。fallback：node_id 缺失/找不到 → 该 region 跳过渲染并记 warning。

## 3. 核心算法（蓝图 + 漏洞修复）

### 3.1 方向决策（含 §2 漏洞修复）

```python
def decide_direction(category: str, bbox: list, char_count: int) -> str:
    if category == "overlay_text":
        return "vertical"      # 压脸/框外字：无视 bbox 高宽比，强制竖排（漏洞修复）
    h, w = bbox[3]-bbox[1], bbox[2]-bbox[0]
    if h / w >= 2.2 and char_count <= 6:
        return "vertical"
    return "horizontal"
```

### 3.2 椭圆内切折行 + 字号二分（蓝图 fit_text_to_bubble）

- 安全区：`safe_w = w * 0.85`，`safe_h = h * 0.85`
- 字号二分：`[12, 52]` 区间找最大能容纳的 font_size
- 折行：按字宽累加切行，行宽 ≤ safe_w
- 避头尾：行首禁止 `，。！？、）》` 等（悬挂标点规则，MVP 版：禁止行首，行尾正常）

### 3.3 渲染

- 横排：逐行居中绘制，anchor 于 bbox 中心
- 竖排：字符逐列自上而下，列宽 = font_size，从右往左列序（漫画习惯）；MVP 只做单列竖排（字数≤6 场景）
- 描边：`stroke_width=2.5, stroke_fill=white`（独白/overlay 强制；对白可选 0）
- 字体映射 4 级（fonts.py 注册表）：
  - dialogue_bubble 对白 → `msyh.ttc`（微软雅黑，无描边或细描边）
  - overlay_text / narration → `simkai.ttf`（楷体，强制白描边 2.5px）
  - 呼喊（text 含 `！`/`!!` 等）→ `msyhbd.ttc`（雅黑粗）
  - sfx（side_annotation 暂缓）→ `FZSTK.TTF`（手写体风格）
- fallback：字体文件缺失 → 逐级降级到 msyh → 报 warning 不中断

### 3.4 锚点（anchor_pos）

- 默认：bbox 几何中心
- overlay_text：bbox 中心（原文字区域中心，MVP 够用；精调留后续）

## 4. 输出契约（生产）

`artifacts/<page>_typeset.json`：

```json
{
  "work_id": "touhou-single-wing",
  "page": "10",
  "rendered_items": [
    {
      "region_id": "page_10_u00",
      "layout_direction": "horizontal",
      "font_family": "msyh.ttc",
      "font_size": 24,
      "line_height": 28,
      "stroke_width": 2.5,
      "stroke_color": "#FFFFFF",
      "text_color": "#000000",
      "anchor_pos": [249, 350],
      "lines": ["冷、冷静点…", "才不是在担心八意大人"]
    }
  ],
  "checks": {
    "rendered": 9,
    "translated": 9,
    "coverage_complete": true,
    "overflow": []
  },
  "generated_at": "..."
}
```

- `final.png` = clean 图上叠加渲染结果 → `artifacts/final/<page>_final.png`
- 机械检查（内置于工位）：rendered 数 == translated 数（漏渲染告警）；溢出区域列表（字号触底 <12px 仍放不下 → 记 overflow，交 Stage 6 反压）

## 5. 测试策略

- 纯函数单测（无图）：方向决策 / 折行 / 避头尾 / 字号二分 / 字体映射 fallback
- 渲染单测（Pillow 小图）：横排居中、竖排单列、描边像素抽查（边缘有白色像素）、文字不越界（渲染 bbox 检查）
- 工位级测试（monkeypatch 输入产物）：端到端小图跑通 + 产物结构校验
- live 冒烟：等 rerun 完成后在真实 11-20 clean 图上跑

## 6. 范围外（YAGNI）

- sfx side_annotation 旁注布局（等 sfx_triage 实现后配套）
- 多列竖排、任意多边形内切、字体下载/打包
- koharu-renderer 集成（已否决）

## 7. 风险

- **bbox 对齐**：canon 无 bbox → 用 node_id 关联 detection.blocks（零契约改动；node_id 缺失则跳过+warning）
- 竖排渲染质量：单列竖排是 MVP 简化，长文本竖排（>6 字）按方向决策不会触发，安全
- 中文字体度量：Pillow 用 getlength 计算，不同字体宽度不同，字号二分以实际测量为准
