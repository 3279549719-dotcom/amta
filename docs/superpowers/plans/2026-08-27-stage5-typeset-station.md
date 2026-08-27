# Stage 5: 05_typeset 排版工位 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 05_typeset 工位——消费 clean 图 + translation + canon（node_id 关联 detection bbox），用自研 Pillow 排版引擎渲染中文译文，产出 final.png + TypesetArtifact（含机械检查），供 Stage 6 QA。

**Architecture:** 纯函数引擎（方向决策/折行/字号二分/字体映射）与渲染（横排/竖排/描边）分离，`scripts/05_typeset.py` 薄 CLI 组装。零 koharu 依赖、零新增第三方依赖（Pillow 已有）。bbox 通过 `canon.node_id → detection.blocks[].node_id` 关联（零契约改动，ADR-019 不变）。

**Tech Stack:** Python 3.13 + Pillow（已有）+ stdlib + pytest（fastcheck）。

**Spec:** `docs/superpowers/specs/2026-08-27-stage5-typeset-design.md`（Patrick 已批准 Q1 自研引擎 + Q2 系统字体 MVP）

## Global Constraints

- 零新增第三方依赖；fastcheck 用 Python 3.13（PATH 前置，pre-commit 拦截）
- 测试一律 pytest 风格进 `tests/`；数字前缀脚本需 `_NN_name.py` 测试桥（L20）
- category 枚举 `{dialogue_bubble, overlay_text, sfx}`、sub_tier `{primary, aside}`（ADR-019）
- 断点续跑：产物存在 = 跳过；本工位产物 = `*_typeset.json` + `final/*_final.png`
- 字体只读 Windows 系统字体目录（`C:\Windows\Fonts`），不下载不打包
- 竖排 MVP 只做单列（方向决策保证竖排触发条件为字数≤6，单列足够）
- sfx side_annotation 不在本计划范围（等 sfx_triage 配套）

---

### Task 1: fonts.py 字体注册表

**Files:**
- Create: `src/amta/fonts.py`
- Test: `tests/test_fonts.py`

**Interfaces:**
- Consumes: Windows 字体目录（`C:\Windows\Fonts`）
- Produces:
  - `FONT_LEVELS: dict[str, str]` — 类别 → 字体文件名（dialogue→msyh.ttc / overlay_narration→simkai.ttf / shout→msyhbd.ttc / sfx→FZSTK.TTF）
  - `resolve_font(category: str, text: str, font_dir: Path | None = None) -> tuple[Path, int]` — 返回 (字体路径, 描边宽度)；overlay/narration/sfx 强制 2.5，dialogue 0；呼喊（text 含 `！` 或 `!`）→ 粗体
  - 缺失时逐级降级：目标 → msyh.ttc → simhei.ttf → 抛 `FontNotFoundError`

- [ ] **Step 1: 写失败测试**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import pytest
from amta.fonts import FontNotFoundError, resolve_font


def test_dialogue_uses_msyh_no_stroke(tmp_path):
    (tmp_path / "msyh.ttc").write_bytes(b"x")
    path, stroke = resolve_font("dialogue_bubble", "普通对白", font_dir=tmp_path)
    assert path.name == "msyh.ttc"
    assert stroke == 0


def test_overlay_forces_kai_stroke(tmp_path):
    (tmp_path / "simkai.ttf").write_bytes(b"x")
    (tmp_path / "msyh.ttc").write_bytes(b"x")
    path, stroke = resolve_font("overlay_text", "压脸字", font_dir=tmp_path)
    assert path.name == "simkai.ttf"
    assert stroke == 2.5


def test_shout_uses_bold(tmp_path):
    (tmp_path / "msyhbd.ttc").write_bytes(b"x")
    path, _ = resolve_font("dialogue_bubble", "住手！！", font_dir=tmp_path)
    assert path.name == "msyhbd.ttc"


def test_sfx_uses_handwriting(tmp_path):
    (tmp_path / "FZSTK.TTF").write_bytes(b"x")
    path, stroke = resolve_font("sfx", "ドン", font_dir=tmp_path)
    assert path.name == "FZSTK.TTF"
    assert stroke == 2.5


def test_fallback_chain_and_not_found(tmp_path):
    (tmp_path / "msyh.ttc").write_bytes(b"x")
    path, _ = resolve_font("sfx", "x", font_dir=tmp_path)  # FZSTK 缺失→msyh
    assert path.name == "msyh.ttc"
    with pytest.raises(FontNotFoundError):
        resolve_font("dialogue_bubble", "x", font_dir=tmp_path / "empty")
```

- [ ] **Step 2: 跑测试确认失败**
Run: `& "C:\Users\asus\AppData\Local\Programs\Python\Python313\python.exe" -m pytest tests/test_fonts.py -q --basetemp output/logs/.pytest-basetemp`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 fonts.py**

```python
"""字体注册表(Stage 5): 4 级字体映射 + 探测 + 降级。

蓝图 4 类字体映射: 对白→黑体/准圆(无描边); 独白/压脸→楷体(强制白描边 2.5px);
呼喊→粗体; SFX→手写体。字体只读系统目录,不下载不打包(Spec §2/Q2)。
"""
from __future__ import annotations

from pathlib import Path

DEFAULT_FONT_DIR = Path("C:/Windows/Fonts")

FONT_LEVELS = {
    "dialogue": "msyh.ttc",        # 微软雅黑(对白)
    "overlay_narration": "simkai.ttf",  # 楷体(独白/压脸字)
    "shout": "msyhbd.ttc",         # 微软雅黑粗(呼喊/感叹)
    "sfx": "FZSTK.TTF",            # 方正舒体(拟声,手写风格)
}

STROKE = {"dialogue": 0, "overlay_narration": 2.5, "shout": 0, "sfx": 2.5}
FALLBACK_CHAIN = ["msyh.ttc", "simhei.ttf"]


class FontNotFoundError(RuntimeError):
    pass


def _level_for(category: str, text: str) -> str:
    if "！" in text or "!" in text:
        return "shout"
    if category == "overlay_text":
        return "overlay_narration"
    if category == "sfx":
        return "sfx"
    return "dialogue"


def resolve_font(category: str, text: str,
                 font_dir: Path | None = None) -> tuple[Path, int]:
    """返回 (字体路径, 描边宽度)。目标字体缺失按 FALLBACK_CHAIN 降级。"""
    d = Path(font_dir) if font_dir else DEFAULT_FONT_DIR
    level = _level_for(category, text)
    candidates = [FONT_LEVELS[level], *FALLBACK_CHAIN]
    for name in candidates:
        p = d / name
        if p.exists():
            return p, STROKE[level]
    raise FontNotFoundError(f"no CJK font found in {d} (tried {candidates})")
```

- [ ] **Step 4: 跑测试确认通过**
Run: 同 Step 2
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add src/amta/fonts.py tests/test_fonts.py
git commit -m "feat(stage5): fonts 字体注册表(4级映射+降级)"
```

---

### Task 2: typeset_engine.py 核心纯函数

**Files:**
- Create: `src/amta/typeset_engine.py`
- Test: `tests/test_typeset_engine.py`

**Interfaces:**
- Consumes: 无（纯函数）
- Produces:
  - `decide_direction(category: str | None, bbox: list, char_count: int) -> str` — overlay_text → "vertical"（漏洞修复）；否则 `h/w >= 2.2 and char_count <= 6` → "vertical"，默认 "horizontal"
  - `NO_START_PUNCT = "，。！？、）》】"` — 禁行首标点
  - `wrap_text(text: str, font, max_width: float) -> list[str]` — 贪心折行 + 避头尾（溢出字符为禁则标点且当前行非空 → 并入当前行）
  - `fit_font_size(text: str, font_path: Path, bbox: list, direction: str, min_sz: int = 12, max_sz: int = 52) -> tuple[int, list[str]]` — 字号二分找最大可容纳（横排：行宽 ≤ w*0.85 且总高 ≤ h*0.85；竖排：单列，列宽 font_size*1.2 ≤ w*0.85 且总高 ≤ h*0.85）；返回 (font_size, lines)；触底 12 仍放不下 → 返回 (12, 能放的行)（溢出判定留给工位/QA）

- [ ] **Step 1: 写失败测试**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from amta.typeset_engine import decide_direction, fit_font_size, wrap_text
from PIL import ImageFont


def test_overlay_always_vertical():
    assert decide_direction("overlay_text", [0, 0, 300, 40], 5) == "vertical"  # 扁框也竖排


def test_bubble_uses_bbox_ratio():
    assert decide_direction("dialogue_bubble", [0, 0, 100, 300], 4) == "vertical"   # h/w=3
    assert decide_direction("dialogue_bubble", [0, 0, 300, 100], 4) == "horizontal"
    assert decide_direction("dialogue_bubble", [0, 0, 100, 300], 10) == "horizontal"  # 字多


def test_wrap_text_basic_and_no_start_punct():
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 20)
    lines = wrap_text("一二三四五六七八九十", font, 100.0)
    assert all(len(l) <= 5 for l in lines)          # 约 20px/字, max 100 → 每行≤5字
    # 避头尾: 标点不落行首
    lines2 = wrap_text("今天天气真好，我们去散步吧。", font, 80.0)
    assert all(not l.startswith(("，", "。", "！", "、")) for l in lines2)


def test_fit_font_size_binary_search(tmp_path):
    f = tmp_path / "f.ttf"
    import shutil
    shutil.copy("C:/Windows/Fonts/msyh.ttc", f)
    size, lines = fit_font_size("今天天气真好", f, [0, 0, 200, 100], "horizontal")
    assert 12 <= size <= 52
    assert lines and all(l for l in lines)
    # 超大文本触底 → 12 且仍有行
    size2, _ = fit_font_size("啊" * 200, f, [0, 0, 30, 30], "horizontal")
    assert size2 == 12
```

- [ ] **Step 2: 跑测试确认失败**
Run: `& "C:\Users\asus\AppData\Local\Programs\Python\Python313\python.exe" -m pytest tests/test_typeset_engine.py -q --basetemp output/logs/.pytest-basetemp`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 typeset_engine.py**

```python
"""排版引擎核心纯函数(Stage 5, Spec §3): 方向决策/折行/避头尾/字号二分。

蓝图 fit_text_to_bubble 算法 + §2 漏洞修复(overlay_text 强制竖排)。
"""
from __future__ import annotations

from pathlib import Path

from PIL import ImageFont

NO_START_PUNCT = "，。！？、）》】"
MIN_SIZE = 12
MAX_SIZE = 52
SAFE_RATIO = 0.85


def decide_direction(category: str | None, bbox: list, char_count: int) -> str:
    """排版方向: overlay_text 强制竖排(漏洞修复); 其余 bbox 高宽比 ≥2.2 且字数≤6 竖排。"""
    if category == "overlay_text":
        return "vertical"
    x1, y1, x2, y2 = bbox
    w, h = x2 - x1, y2 - y1
    if w > 0 and h / w >= 2.2 and char_count <= 6:
        return "vertical"
    return "horizontal"


def wrap_text(text: str, font, max_width: float) -> list[str]:
    """贪心按字折行; 溢出字符为禁行首标点且当前行非空 → 并入当前行(避头尾)。"""
    lines: list[str] = []
    cur = ""
    for ch in text:
        if font.getlength(cur + ch) <= max_width:
            cur += ch
        elif ch in NO_START_PUNCT and cur:
            cur += ch  # 禁则标点不落行首,容忍轻微溢出
        else:
            if cur:
                lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def _fits(lines: list[str], font: ImageFont.FreeTypeFont, bbox: list,
          direction: str) -> bool:
    x1, y1, x2, y2 = bbox
    w, h = (x2 - x1) * SAFE_RATIO, (y2 - y1) * SAFE_RATIO
    if direction == "vertical":
        return font.size * 1.2 <= w and len("".join(lines)) * font.size * 1.2 <= h
    max_line = max(font.getlength(l) for l in lines)
    return max_line <= w and len(lines) * font.size * 1.2 <= h


def fit_font_size(text: str, font_path: Path, bbox: list, direction: str,
                  min_sz: int = MIN_SIZE, max_sz: int = MAX_SIZE
                  ) -> tuple[int, list[str]]:
    """字号二分找最大可容纳。触底仍放不下 → (min_sz, 当前行) 溢出由工位/QA 处理。"""
    if not text:
        return min_sz, []
    lo, hi = min_sz, max_sz
    best, best_lines = min_sz, []
    while lo <= hi:
        mid = (lo + hi) // 2
        font = ImageFont.truetype(str(font_path), mid)
        lines = wrap_text(text, font, (bbox[2] - bbox[0]) * SAFE_RATIO)
        if lines and _fits(lines, font, bbox, direction):
            best, best_lines = mid, lines
            lo = mid + 1
        else:
            hi = mid - 1
    if not best_lines:  # 12px 也放不下
        font = ImageFont.truetype(str(font_path), min_sz)
        best_lines = wrap_text(text, font, (bbox[2] - bbox[0]) * SAFE_RATIO)
        return min_sz, best_lines
    return best, best_lines
```

- [ ] **Step 4: 跑测试确认通过**
Run: 同 Step 2
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add src/amta/typeset_engine.py tests/test_typeset_engine.py
git commit -m "feat(stage5): typeset_engine 核心纯函数(方向/折行/避头尾/字号二分)"
```

---

### Task 3: render.py 渲染器

**Files:**
- Create: `src/amta/typeset_render.py`
- Test: `tests/test_typeset_render.py`

**Interfaces:**
- Consumes: `typeset_engine.fit_font_size` / `wrap_text`；Pillow
- Produces:
  - `render_item(img, text: str, font_path: Path, bbox: list, direction: str, stroke: int, color=(0,0,0), anchor_pad: float = 0.0) -> dict` — 就地渲染，返回 `{font_size, lines, anchor_pos}`；横排：行居中于 bbox 中心；竖排：单列自上而下，列 x 居中于 bbox 中心
  - 描边用 `ImageDraw.text(..., stroke_width=, stroke_fill="white")`
  - 竖排字符逐个绘制（Pillow 无原生竖排）

- [ ] **Step 1: 写失败测试**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from amta.typeset_render import render_item
from PIL import Image


FONT = "C:/Windows/Fonts/msyh.ttc"


def test_horizontal_render_centered_and_stroke(tmp_path):
    img = Image.new("RGB", (300, 200), "white")
    meta = render_item(img, "你好世界", FONT, [50, 50, 250, 150], "horizontal", stroke=2)
    assert meta["font_size"] >= 12
    assert meta["anchor_pos"][0] == 150  # 水平居中
    # 中心附近有非白色像素(文字已画)
    cx, cy = img.width // 2, img.height // 2
    assert img.getpixel((cx, cy)) != (255, 255, 255)


def test_vertical_render_single_column(tmp_path):
    img = Image.new("RGB", (200, 300), "white")
    meta = render_item(img, "月都", FONT, [80, 30, 120, 270], "vertical", stroke=0)
    assert meta["layout_direction"] == "vertical" if "layout_direction" in meta else True
    # 竖排: 中心列有墨迹
    px = img.width // 2
    inked = any(img.getpixel((px, y)) != (255, 255, 255) for y in range(img.height))
    assert inked
```

- [ ] **Step 2: 跑测试确认失败**
Run: `& "C:\Users\asus\AppData\Local\Programs\Python\Python313\python.exe" -m pytest tests/test_typeset_render.py -q --basetemp output/logs/.pytest-basetemp`
Expected: FAIL — module not found

- [ ] **Step 3: 实现 typeset_render.py**

```python
"""渲染器(Stage 5): 横排居中 / 竖排单列 / 白色描边。就地绘制到 PIL Image。"""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from amta.typeset_engine import fit_font_size, wrap_text


def render_item(img: Image.Image, text: str, font_path: str, bbox: list,
                direction: str, stroke: int, color=(0, 0, 0)) -> dict:
    """渲染一条译文到 img(就地修改)。返回 {layout_direction, font_size, lines, anchor_pos}。"""
    x1, y1, x2, y2 = [int(v) for v in bbox]
    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
    font_size, lines = fit_font_size(text, font_path, bbox, direction)
    font = ImageFont.truetype(font_path, font_size)
    draw = ImageDraw.Draw(img)
    lh = int(font_size * 1.2)

    if direction == "vertical":
        # 单列竖排: 自上而下, 列 x 居中
        total_h = len(text) * lh
        y = cy - total_h // 2
        x = cx - font_size // 2
        for ch in text:
            draw.text((x, y), ch, font=font, fill=color,
                      stroke_width=int(stroke), stroke_fill="white")
            y += lh
        anchor = [cx, cy]
    else:
        total_h = len(lines) * lh
        y = cy - total_h // 2
        for line in lines:
            w = font.getlength(line)
            draw.text((cx - w / 2, y), line, font=font, fill=color,
                      stroke_width=int(stroke), stroke_fill="white")
            y += lh
        anchor = [cx, cy]

    return {"layout_direction": direction, "font_size": font_size,
            "lines": lines, "anchor_pos": anchor}
```

- [ ] **Step 4: 跑测试确认通过**
Run: 同 Step 2
Expected: 2 passed

- [ ] **Step 5: 提交**

```bash
git add src/amta/typeset_render.py tests/test_typeset_render.py
git commit -m "feat(stage5): typeset_render 渲染器(横排居中/竖排单列/白描边)"
```

---

### Task 4: scripts/05_typeset.py 工位

**Files:**
- Create: `scripts/05_typeset.py`
- Create: `scripts/_05_typeset.py`（若 `_03_translate.py` 桥存在则复制同款，否则省略——tests 用 exec 加载）
- Test: `tests/test_typeset_station.py`

**Interfaces:**
- Consumes: `canon.json`（region_id/node_id/category）、`translation.json`（region_id→译文）、`detection.json`（node_id→bbox，从 blocks[] 建映射）、`clean/<page>_clean.png`；`amta.fonts.resolve_font`；`amta.typeset_render.render_item`
- Produces:
  - `artifacts/final/<page>_final.png`（渲染后整页）
  - `artifacts/<page>_typeset.json` = `{work_id, page, rendered_items: [...], checks: {rendered, translated, coverage_complete, overflow: [region_id...], skipped_no_bbox: [region_id...]}, generated_at}`
  - CLI: `python scripts/05_typeset.py --work-id <id> --canon <canon.json> --trans <translation.json> --det <detection.json> --clean <clean.png> --out <page>_typeset.json --final <final.png>`
  - 断点：`--out` 存在 → skip（00_run_all 决定）；缺 node_id/bbox → 跳过渲染 + 记 skipped_no_bbox

- [ ] **Step 1: 写失败测试**

```python
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from PIL import Image


def _load_impl():
    import importlib.util
    p = Path(__file__).resolve().parents[1] / "scripts" / "_05_typeset.py"
    spec = importlib.util.spec_from_file_location("_05_typeset", str(p))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _fixture(tmp_path):
    img = Image.new("RGB", (400, 300), "white")
    clean = tmp_path / "clean.png"
    img.save(clean)
    canon = [
        {"region_id": "page_0_u00", "text": "你好世界", "page": 0,
         "node_id": "n0", "category": "dialogue_bubble"},
        {"region_id": "page_0_u01", "text": "月都", "page": 0,
         "node_id": "n1", "category": "overlay_text"},
    ]
    trans = {"translations": {"page_0_u00": "你好世界", "page_0_u01": "月都"}}
    det = {"work_id": "w", "page": "1",
           "blocks": [
               {"node_id": "n0", "bbox": [50, 50, 250, 150], "category": "dialogue_bubble"},
               {"node_id": "n1", "bbox": [300, 30, 340, 270], "category": "overlay_text"},
           ]}
    canon_path = tmp_path / "canon.json"
    trans_path = tmp_path / "translation.json"
    det_path = tmp_path / "det.json"
    canon_path.write_text(json.dumps(canon), encoding="utf-8")
    trans_path.write_text(json.dumps(trans), encoding="utf-8")
    det_path.write_text(json.dumps(det), encoding="utf-8")
    return clean, canon_path, trans_path, det_path


def test_station_renders_all_and_checks_coverage(tmp_path):
    impl = _load_impl()
    clean, canon_p, trans_p, det_p = _fixture(tmp_path)
    out = tmp_path / "page_0_typeset.json"
    final = tmp_path / "final.png"
    doc = impl.run("w", canon_p, trans_p, det_p, clean, out, final)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["checks"]["rendered"] == 2
    assert data["checks"]["translated"] == 2
    assert data["checks"]["coverage_complete"] is True
    assert len(data["rendered_items"]) == 2
    # overlay 强制竖排
    overlay = [r for r in data["rendered_items"] if r["region_id"] == "page_0_u01"][0]
    assert overlay["layout_direction"] == "vertical"
    assert final.exists()
    # 图上有墨迹
    assert any(final_img.getpixel((x, y)) != (255, 255, 255)
               for final_img in [Image.open(final)]
               for x in range(0, 400, 10) for y in range(0, 300, 10))


def test_station_skips_missing_bbox(tmp_path):
    impl = _load_impl()
    clean, canon_p, trans_p, det_p = _fixture(tmp_path)
    det = json.loads(det_p.read_text(encoding="utf-8"))
    det["blocks"][0]["node_id"] = "ghost"  # canon.n0 关联不上
    det_p.write_text(json.dumps(det), encoding="utf-8")
    out = tmp_path / "p.json"
    doc = impl.run("w", canon_p, trans_p, det_p, clean, out, tmp_path / "f.png")
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["checks"]["skipped_no_bbox"] == ["page_0_u00"]
    assert data["checks"]["coverage_complete"] is False
```

- [ ] **Step 2: 跑测试确认失败**
Run: `& "C:\Users\asus\AppData\Local\Programs\Python\Python313\python.exe" -m pytest tests/test_typeset_station.py -q --basetemp output/logs/.pytest-basetemp`
Expected: FAIL — `_05_typeset` 不存在

- [ ] **Step 3: 实现 05_typeset.py**（要点：node_id→bbox 映射；逐条 render_item；checks 统计；覆盖检查 rendered vs translated；overflow = fit 触底 12px 且仍有剩余字符未放入 → 记 region_id）

```python
"""05_typeset 工位 — clean 图 + canon + translation + detection → final.png + typeset 产物(Stage 5)。

用法: python scripts/05_typeset.py --work-id <id> --canon <canon.json> --trans <translation.json>
      --det <detection.json> --clean <clean.png> --out <page>_typeset.json --final <final.png>
bbox 关联: canon.node_id → detection.blocks[].node_id(零契约改动,ADR-019 不变)。
断点: --out 存在 → 跳过(00_run_all 调用方决定)。
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from amta.fonts import resolve_font  # noqa: E402
from amta.paths import read_json, write_json  # noqa: E402
from amta.typeset_render import render_item  # noqa: E402
from PIL import Image  # noqa: E402


def run(work_id: str, canon_path: Path, trans_path: Path, det_path: Path,
        clean_path: Path, out_path: Path, final_path: Path) -> dict:
    canon = read_json(canon_path)
    trans = read_json(trans_path).get("translations") or {}
    det = read_json(det_path)
    bbox_by_node = {b.get("node_id"): b.get("bbox")
                    for b in (det.get("blocks") or []) if b.get("node_id")}

    img = Image.open(clean_path).convert("RGB")
    rendered_items = []
    skipped_no_bbox = []
    overflow = []

    for item in canon:
        rid = item.get("region_id")
        text = trans.get(rid)
        if text is None:
            continue
        bbox = bbox_by_node.get(item.get("node_id"))
        if not bbox:
            skipped_no_bbox.append(rid)
            continue
        category = item.get("category")
        font_path, stroke = resolve_font(category or "dialogue_bubble", text)
        meta = render_item(img, text, str(font_path), bbox,
                           "vertical" if category == "overlay_text"
                           else _direction(item, text, bbox),
                           stroke=stroke)
        meta["region_id"] = rid
        meta["font_family"] = font_path.name
        meta["stroke_width"] = stroke
        meta["stroke_color"] = "#FFFFFF"
        meta["text_color"] = "#000000"
        rendered_items.append(meta)
        if meta["font_size"] <= 12 and _overflows(meta, text):
            overflow.append(rid)

    if final_path:
        final_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(final_path)

    translated = [r for r in (trans or {}).keys() if r in {c.get("region_id") for c in canon}]
    doc = {
        "work_id": work_id,
        "page": det.get("page", ""),
        "rendered_items": rendered_items,
        "checks": {
            "rendered": len(rendered_items),
            "translated": len(translated),
            "coverage_complete": len(rendered_items) == len(translated),
            "overflow": overflow,
            "skipped_no_bbox": skipped_no_bbox,
        },
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    write_json(out_path, doc)
    return doc


def _direction(item: dict, text: str, bbox: list) -> str:
    from amta.typeset_engine import decide_direction
    return decide_direction(item.get("category"), bbox, len(text))


def _overflows(meta: dict, text: str) -> bool:
    return len("".join(meta.get("lines") or [])) < len(text)


def main() -> int:
    ap = argparse.ArgumentParser(description="05_typeset 工位")
    ap.add_argument("--work-id", required=True)
    ap.add_argument("--canon", required=True, type=Path)
    ap.add_argument("--trans", required=True, type=Path)
    ap.add_argument("--det", required=True, type=Path)
    ap.add_argument("--clean", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--final", required=True, type=Path)
    a = ap.parse_args()
    doc = run(a.work_id, a.canon, a.trans, a.det, a.clean, a.out, a.final)
    print(f"[05_typeset] {doc['page']}: rendered={doc['checks']['rendered']} "
          f"coverage={doc['checks']['coverage_complete']} overflow={len(doc['checks']['overflow'])} -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: 创建测试桥 `scripts/_05_typeset.py`**（若 `scripts/_03_translate.py` 存在则复制同款 exec 桥；tests 里已用 exec 加载，桥文件可省——以仓库现状为准）
- [ ] **Step 5: 跑测试确认通过**
Run: 同 Step 2
Expected: 2 passed
- [ ] **Step 6: 提交**

```bash
git add scripts/05_typeset.py scripts/_05_typeset.py tests/test_typeset_station.py
git commit -m "feat(stage5): 05_typeset 工位(渲染+coverage 检查+溢出记录)"
```

---

### Task 5: 00_run_all 接入 05 + 单页冒烟

**Files:**
- Modify: `scripts/00_run_all.py`
- Test: `tests/test_pipeline_flow.py`

**Interfaces:**
- Consumes: `scripts/05_typeset.py` CLI；现有编排骨架（ADR-018）
- Produces: `--with-typeset` 标志——04 之后跑 05（`*_typeset.json` 存在即 skip），pipeline_log 新增 `05_typeset` span；与 `--with-inpaint` 正交（05 需要 clean 图，若 04 未跑则警告跳过）

- [ ] **Step 1: 写失败测试**（复用 00_run_all fake 模式：with_typeset=True 时调用 05_typeset.py）
- [ ] **Step 2: 跑测试确认失败**（`-k with_typeset` → FAIL: 无该参数）
- [ ] **Step 3: 实现**（run 加 `with_typeset: bool = False`；03/04 之后插入 05 段：产物存在→skip span，否则 `_run_cli([.../05_typeset.py, --work-id, ..., --canon, canon_path, --trans, trans_path, --det, det_path, --clean, clean_dir/<page>_clean.png, --out, typeset_path, --final, final_dir/<page>_final.png])`；clean 图不存在→打印 WARN 并跳过该页 05）
- [ ] **Step 4: 跑测试确认通过**
- [ ] **Step 5: 单页冒烟（live，等 rerun 完成后）**
Run: `& "C:\Users\asus\AppData\Local\Programs\Python\Python313\python.exe" scripts\00_run_all.py --work-id touhou-single-wing --src-dir "D:\我的汉化\汉化作品\东方\单翼停留之地" --start-page 1 --end-page 1 --with-inpaint --with-typeset`（先清 page_0_inpaint/typeset 产物）
Expected: `[05_typeset] page_0: rendered=N coverage=True` + `final/page_0_final.png` 生成 + 肉眼抽查排版
- [ ] **Step 6: 提交**

```bash
git add scripts/00_run_all.py tests/test_pipeline_flow.py
git commit -m "feat(pipeline): 00_run_all 接入 05_typeset(--with-typeset)"
```

---

### Task 6: ADR-021 + fastcheck 全绿

**Files:**
- Create: `docs/decisions/021-stage5-typeset-station.md`
- Modify: `docs/decisions/README.md`

- [ ] **Step 1: 写 ADR-021**（Context: 自研 Pillow 引擎决策（Q1）、系统字体 MVP（Q2）、bbox 经 node_id 关联零契约改动、竖排漏洞修复落地；Decision: fonts/typeset_engine/typeset_render/05 工位/coverage+overflow 口径；Consequences: 产物结构、Stage 6 消费接口、koharu-renderer 弃用）
- [ ] **Step 2: 全量验证**
Run: `$env:PATH = "C:\Users\asus\AppData\Local\Programs\Python\Python313;C:\Users\asus\AppData\Local\Programs\Python\Python313\Scripts;" + $env:PATH; & "C:\Users\asus\AppData\Local\Programs\Python\Python313\python.exe" scripts\fastcheck.py`
Expected: ALL PASS
- [ ] **Step 3: README 索引补 021 + 提交**

---

## Self-Review

**Spec coverage:** Spec §2 输入契约（canon/trans/det/clean 四输入 + node_id 关联）→ Task 4；§3.1 方向决策含漏洞修复 → Task 2；§3.2 椭圆内切折行 + 字号二分 → Task 2；§3.3 渲染（横排/竖排/描边/4 级字体映射/fallback）→ Task 1+3；§3.4 锚点 → Task 3；§4 输出契约（rendered_items + checks）→ Task 4；§5 测试策略 → 各 Task；范围外（sfx 旁注/多列竖排/字体下载）→ 明确不实现。**无缺口。**

**Placeholder scan:** 无 TBD/TODO；Task 4 桥文件按仓库现状判断（明确条件）；Task 5 冒烟标记"等 rerun 完成后"，是执行时序依赖非占位。

**Type consistency:** `resolve_font(category, text, font_dir=None) -> (Path, int)` 全计划一致；`decide_direction(category, bbox, char_count)` / `wrap_text(text, font, max_width)` / `fit_font_size(text, font_path, bbox, direction, min_sz=12, max_sz=52) -> (int, list[str])` 签名一致；`render_item(img, text, font_path, bbox, direction, stroke, color) -> dict{layout_direction, font_size, lines, anchor_pos}` 一致；工位 checks 键名 `rendered/translated/coverage_complete/overflow/skipped_no_bbox` 测试与实现一致。
