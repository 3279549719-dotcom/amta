# 交接：Paratext 管线精简与合并（2026-09-22）

> 本文是 `handoff-2026-09-21-vlm-direct-ocr.md` 的续篇，覆盖从"VLM 布局规划器"到"精简为贪婪本地换行"的完整简化过程，以及最终合并到 main 的状态。

## 最终结论

**Paratext（副文本：封面/后记/版权页/人物介绍页等横排大片文字页）管线已验证可行并合并到 main。** 9 页实验页（月天新地 1/38/39/55/63/67 + 单翼停留之地 1/5/40）全部跑通，inpaint 和 typeset 质量合格。

管线是 **opt-in** 的：默认 `run_pipeline.py` 走生产管线（hayai OCR），特殊页通过 `scripts/probes/probe_paratext.py` 入口运行，运行时 monkey-patch 替换 ocr/translate/typeset 三个站。不影响普通页。

## 最终架构（5 步，1 次 VLM 调用）

```
detect（现有 RT 检测器）
  ↓
VLM 一次调用（paratext_layout.py / read_layout）：
  转写日文 + 观察排版风格（direction/align/font/font_size_ratio/color/stroke）
  ↓
translate（现有，JSON 数组输入修复）
  ↓
inpaint（现有 LaMa / 直接填色）
  ↓
本地渲染（paratext_render.py）：
  贪婪换行（kinsoku + Latin token 保护）+ 按 VLM 观察到的风格画字
```

VLM 只做它擅长的（看和理解），本地代码只做它擅长的（测量和画）。没有重试，没有评审，没有本地启发式修正。

## 这轮删掉了什么（Bitter Lesson 实践）

| 删掉的东西 | 为什么删 |
|---|---|
| `paratext_plan.py`（~350 行） | VLM 精确指定 `break_after` 字符索引 + 3 次重试 + `_prefer_structural_breaks` + `_source_ink_ratio`/`_source_horizontal_alignment` 本地启发式。换行是机械任务，本地贪婪换行更简单可靠，VLM 数手指数不准 |
| `probe_paratext_review.py`（~71 行） | 独立 VLM 评审不改变输出，还会幻觉误报（如 p40 把正确的"上海爱丽丝幻乐团"标为错误） |
| `probe_paratext_revise.py`（~71 行） | 修订工具，实验中从未使用 |
| `probe_vlm_direct_ocr.py` / `probe_vlm_postscript.py` | 第一代实验脚本，已被 paratext 管线取代 |
| `_probe_translate_debug/retry/split.py` | 调试脚本，交接文档明确标注可删 |
| `_cached_inputs_match` 双层缓存 | read_layout 和 translate 各自有签名缓存，额外加一层 artifact_cache 指纹是冗余 |

渲染子系统从 ~464 行（plan + render）降到 ~130 行（render  alone），**减了 72%**。

## 顺手修的通用 bug

**`translate.py` JSON 数组输入修复**（`467e945` + `b17fff6`）：`_build_content` 从 `"\n".join(blocks)` 改为 `json.dumps(blocks, ensure_ascii=False)`。VLM 转写的多换行文本块（后记段落）用裸 `\n` 拼接时，LLM 分不清块内换行和块间分隔，会输出错误条数导致整批作废。JSON 数组里块内换行是转义的 `\n`，边界由数据结构定死。这是通用修复，不依赖 VLM 实验——hayai 时代每块单行所以没暴露，但契约漏洞一直存在。

## 关键文件

| 文件 | 作用 |
|---|---|
| `scripts/probes/paratext_layout.py` | VLM 视觉读取：转写 + 排版风格观察（含 font_size_ratio/color/stroke） |
| `scripts/probes/paratext_render.py` | 本地渲染：贪婪换行 + 按风格画字（横排/竖排都支持） |
| `scripts/probes/probe_paratext.py` | 实验入口：monkey-patch ocr/translate/typeset，调用 run_pipeline |
| `tests/test_paratext_experiment.py` | 19 个测试：validate_regions / exclusive_crop / wrap_horizontal / layout_text / render_text |

## 跑法

```powershell
$env:PYTHONPATH="src;."
uv run python scripts/probes/probe_paratext.py `
    --work-id exp-paratext-getten `
    --src-dir "D:\我的汉化\汉化作品\东方\月天新地_单页" `
    --start-page 1 --end-page 1 `
    --stages ocr,translate,typeset
```

detect 和 inpaint 需要先跑（用默认管线），paratext 入口只替换 ocr/translate/typeset。

## 实验产物

- 工作区：`workspace/exp-paratext-getten/`（月天新地 6 页）、`workspace/exp-paratext-single/`（单翼停留之地 3 页）
- 9 页成品图已上传飞书公开链接（见对话记录）
- 评审报告 HTML：`output/paratext-getten-final.html`、`output/paratext-single-final.html`（评审步骤已从管线删除，报告是旧产物）

## 已知限制与下一步

1. **翻译质量问题**：4 页有翻译瑕疵（双关语"うどよん"翻成"乌冬四"、"合同"误译成"合集"等），全是 DeepSeek 翻译模型的问题，不是管线问题。可通过术语库或翻译 prompt 优化
2. **描边（stroke）仅支持白色竖排**：横排描边已支持任意颜色，竖排渲染器只支持白色描边（`_render_vertical` 的限制）。封面标题如果需要彩色描边，需要扩展竖排渲染器
3. **自动路由**：目前需要手动指定哪些页走 paratext 管线。未来可在 detect 后判断这页是否横排为主，自动选路径
4. **接进正式管线**：目前是 `scripts/probes/` 下的实验脚本，通过 monkey-patch 注册。如果稳定，可考虑做成正式的 station 变体或配置开关

## 合并状态

- 实验分支：`exp/vlm-direct-ocr`（已合并到 main，可保留可删）
- main 最新：`a1a2088` Merge branch 'exp/vlm-direct-ocr'
- 测试：23 个全过（翻译站 3 + 翻译输入契约 1 + paratext 19）
- lint：ruff + pyright 全过
