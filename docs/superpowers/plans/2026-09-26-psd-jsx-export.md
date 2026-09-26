# PSD JSX 导出实施计划（参考 manga-translator-ui 成熟方案）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 manga-translator-ui 验证过的 PSD+JSX 方案替换当前 photoshopapi 直接生成 PSD 的方案。生成的 PSD 在 Photoshop 中打开后包含 1 个干净底图层 + N 个可编辑文字层，文字大小/位置与成品图 1:1 一致。

**Architecture:** 不直接生成 PSD 二进制文件，而是生成 ExtendScript (.jsx) 脚本，调用本机 Photoshop 执行脚本，由 Photoshop 自己打开底图、创建文字层、保存 PSD。文字层用 Point Text（点文本），字体用 PostScript 名称，位置基于 typeset 的 anchor_pos 计算。

**Tech Stack:** Python 3.12, ExtendScript (JSX), Photoshop COM/CLI, PIL（仅用于底图准备）

**为什么换方案：** 当前 photoshopapi 方案经过 7 轮修复仍无法让文字大小位置与成品图一致，根因是 photoshopapi 的 TextLayer 渲染引擎与 typeset 的 PIL 渲染是两套独立路径。manga-translator-ui（2.9k star，生产验证）用 JSX+Photoshop 方案，文字层由 Photoshop 原生创建，100% 兼容。

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `src/amta/typeset/psd_jsx_export.py` | **新建** — JSX 脚本生成 + Photoshop 调用 + PSD 导出 |
| `src/amta/typeset/psd_export.py` | **废弃** — 旧的 photoshopapi 方案，保留但不再调用 |
| `tests/test_psd_jsx_export.py` | **新建** — JSX 生成逻辑的单元测试 |
| `tests/test_psd_export.py` | **删除或标记废弃** — 旧方案测试 |

---

## Task 1: 新建 psd_jsx_export.py — JSX 脚本生成核心

**Files:**
- Create: `src/amta/typeset/psd_jsx_export.py`
- Test: `tests/test_psd_jsx_export.py`

### Step 1: 写字体映射和工具函数

```python
"""PSD JSX 导出 — 生成 ExtendScript 脚本，调用 Photoshop 创建分层 PSD。

参考 manga-translator-ui/manga_translator/utils/photoshop_export.py 的成熟实现。
图层结构（从下到上）：
  1. 干净底图 (clean) — inpaint 产物，锁定
  2. 文字层 × N — 可编辑 Point Text，每个区域一个图层
"""
from __future__ import annotations

import logging
import os
import platform
import re
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 字体文件名 → Photoshop 字体家族名（用于 JSX 中 findFontPostScriptName 查找）
# JSX 会用 5 轮匹配找到 PostScript 名称，这里只需给家族名
_FONT_FAMILY_MAP: dict[str, str] = {
    "msyh.ttc": "Microsoft YaHei",
    "msyhbd.ttc": "Microsoft YaHei",  # 粗体，JSX 中找同家族
    "simkai.ttf": "KaiTi",
    "simhei.ttf": "SimHei",
    "simsun.ttc": "SimSun",
    "FZSTK.TTF": "FZShuTi",
}


def _resolve_font_family(font_family: str) -> str:
    """字体文件名 → PS 字体家族名；未映射的返回文件名（去掉扩展名）。"""
    if font_family in _FONT_FAMILY_MAP:
        return _FONT_FAMILY_MAP[font_family]
    return Path(font_family).stem


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """#RRGGBB → (r, g, b)，值范围 0-255。"""
    hex_color = hex_color.lstrip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def _escape_jsx_string(text: str) -> str:
    """转义 JSX 单引号字符串中的特殊字符。"""
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\\'")
    text = text.replace("\n", "\\r")
    text = text.replace("\r", "\\r")
    text = text.replace("\t", "    ")
    return text


def _escape_jsx_path(path: str) -> str:
    """Windows 路径 → JSX 安全路径（反斜杠转正斜杠，转义单引号）。"""
    if not path:
        return ""
    return path.replace("\\", "/").replace("'", "\\'")
```

### Step 2: 写 JSX 模板（直接照抄 manga-translator-ui，精简版）

```python
# 完整 JSX 脚本模板
# 关键设计：
# - 用 Point Text（不是 Box Text），不受文本框裁剪
# - 字体用 findFontPostScriptName() 5轮匹配，确保中文能找到
# - DPI 缩放：dpiScale = 72 / doc.resolution，字号转 pt
# - 横排居中对齐，竖排用 Justification.LEFT（对应顶部对齐）
_JSX_TEMPLATE = """
#target photoshop

app.preferences.rulerUnits = Units.PIXELS;
app.preferences.typeUnits = TypeUnits.PIXELS;

var ERROR_FILE_PATH = '{error_file}';

// 字体查找：5轮匹配 PostScript 名称
function findFontPostScriptName(fontName) {{
    if (!fontName) return null;
    var lowerName = fontName.toLowerCase();
    var fonts = app.fonts;
    // 1: PostScript 名精确匹配
    for (var i = 0; i < fonts.length; i++) {{
        if (fonts[i].postScriptName.toLowerCase() === lowerName) return fonts[i].postScriptName;
    }}
    // 2: 字体名精确匹配
    for (var i = 0; i < fonts.length; i++) {{
        if (fonts[i].name.toLowerCase() === lowerName) return fonts[i].postScriptName;
    }}
    // 3: 家族名精确匹配
    for (var i = 0; i < fonts.length; i++) {{
        if (fonts[i].family.toLowerCase() === lowerName) return fonts[i].postScriptName;
    }}
    // 4: 部分匹配
    for (var i = 0; i < fonts.length; i++) {{
        var ps = fonts[i].postScriptName.toLowerCase();
        var nm = fonts[i].name.toLowerCase();
        var fm = fonts[i].family.toLowerCase();
        if (ps.indexOf(lowerName) !== -1 || nm.indexOf(lowerName) !== -1 || fm.indexOf(lowerName) !== -1)
            return fonts[i].postScriptName;
    }}
    return null;
}}

try {{
    // 打开干净底图
    var inputFile = new File('{input_file}');
    if (!inputFile.exists) throw new Error('Input file not found: ' + inputFile.fsName);
    var doc = app.open(inputFile);

    // 转 RGB 模式
    try {{ if (doc.mode != DocumentMode.RGB) doc.changeMode(ChangeMode.RGB); }} catch(e) {{}}

    // 底图层重命名并锁定
    var baseLayer = null;
    try {{ if (doc.backgroundLayer) baseLayer = doc.backgroundLayer; }} catch(e) {{}}
    if (!baseLayer && doc.layers.length > 0) baseLayer = doc.layers[doc.layers.length - 1];
    if (baseLayer) {{
        baseLayer.name = '干净底图 (clean)';
        baseLayer.allLocked = true;
    }}

    {text_layers_code}

    // 保存 PSD
    var psdFile = new File('{output_file}');
    var psdOptions = new PhotoshopSaveOptions();
    psdOptions.embedColorProfile = true;
    psdOptions.alphaChannels = true;
    psdOptions.layers = true;
    psdOptions.spotColors = true;
    doc.saveAs(psdFile, psdOptions, true);
    doc.close(SaveOptions.DONOTSAVECHANGES);

}} catch (e) {{
    var errorMsg = 'ERROR: ' + e.message + '\\nLine: ' + e.line;
    $.writeln(errorMsg);
    try {{
        var errFile = new File(ERROR_FILE_PATH);
        errFile.open('w');
        errFile.write(errorMsg);
        errFile.close();
    }} catch(we) {{}}
}}
"""

# 单个文字层模板 — Point Text
# 属性顺序：方向 → 对齐 → 位置 → 内容 → 大小 → 颜色 → 行间距
_TEXT_LAYER_TEMPLATE = """
    // 文字层 {index}: {name}
    var tl{index} = doc.artLayers.add();
    tl{index}.kind = LayerKind.TEXT;
    tl{index}.name = '{name}';

    var ti{index} = tl{index}.textItem;
    var dpiScale{index} = 72 / doc.resolution;

    // 字体查找
    var fontPS{index} = findFontPostScriptName('{font_family}');
    if (fontPS{index}) {{
        ti{index}.font = fontPS{index};
    }}

    ti{index}.direction = {direction};
    ti{index}.justification = {justification};
    ti{index}.position = [{x}, {y}];
    ti{index}.contents = '{text}';
    ti{index}.size = new UnitValue({font_size} * dpiScale{index}, 'pt');

    var tc{index} = new SolidColor();
    tc{index}.rgb.red = {color_r};
    tc{index}.rgb.green = {color_g};
    tc{index}.rgb.blue = {color_b};
    ti{index}.color = tc{index};

    // 行间距
    var leadingVal{index} = {leading} * dpiScale{index};
    ti{index}.useAutoLeading = false;
    ti{index}.leading = new UnitValue(leadingVal{index}, 'pt');
"""
```

### Step 3: 写文字层 JSX 生成函数（核心位置计算）

```python
def _generate_text_layer_jsx(index: int, item: dict) -> str:
    """从 typeset rendered_item 生成单个文字层的 JSX 代码。

    位置计算参考 manga-translator-ui：
    - 横排：Point Text position = [中心x, 第一行基线y]，居中对齐
    - 竖排：Point Text position = [第一列中心x, 顶部y]，左对齐(=顶部)
    anchor_pos 是整个文字块的中心点，需要根据行数偏移到第一行/列。
    """
    region_id = item.get("region_id", f"r{index}")
    lines = item.get("lines", [])
    if not lines:
        return ""

    font_size = float(item.get("font_size", 40))
    anchor_x, anchor_y = item.get("anchor_pos", [0, 0])
    is_vertical = item.get("layout_direction", "horizontal") == "vertical"
    font_family = _resolve_font_family(item.get("font_family", "msyh.ttc"))
    color_r, color_g, color_b = _hex_to_rgb(item.get("rendered_color", "#000000"))

    # 文字内容：多行用 \r 连接（PS 换行符）
    raw_text = "\r".join(lines)
    text = _escape_jsx_string(raw_text)
    num_lines = len(lines)

    # 行间距：竖排 1.2，横排 1.15（参考 manga-translator-ui 的 leading_factor）
    leading_factor = 1.2 if is_vertical else 1.15
    leading = font_size * leading_factor

    # 位置计算
    # 横排：anchor 是文字块中心 → position 是第一行基线
    #   y = anchor_y - (num_lines-1)*leading/2 + baseline_offset
    #   baseline_offset ≈ font_size * 0.35（经验值，manga-translator-ui 用这个）
    # 竖排：anchor 是文字块中心 → position 是第一列顶部
    #   列从右向左排，第一列在最右侧
    #   x = anchor_x + (num_lines-1)*leading/2
    #   y = anchor_y - 单列高度/2（单列高度 ≈ font_size * 单行字符数）
    if is_vertical:
        # 竖排：第一列在最右侧
        x = anchor_x + (num_lines - 1) * leading / 2
        # 单列高度估算：取最长行的字符数 * font_size
        max_chars = max(len(line) for line in lines)
        col_height = max_chars * font_size
        y = anchor_y - col_height / 2
        direction = "Direction.VERTICAL"
        justification = "Justification.LEFT"  # 竖排 LEFT = 顶部对齐
    else:
        # 横排：居中对齐
        x = anchor_x
        baseline_offset = font_size * 0.35
        y = anchor_y - (num_lines - 1) * leading / 2 + baseline_offset
        direction = "Direction.HORIZONTAL"
        justification = "Justification.CENTER"

    # 图层名：region_id + 文字前20字
    name_text = re.sub(r"[\r\n]", "", "".join(lines))[:20]
    name = _escape_jsx_string(f"{region_id}: {name_text}")

    return _TEXT_LAYER_TEMPLATE.format(
        index=index,
        name=name,
        font_family=_escape_jsx_string(font_family),
        direction=direction,
        justification=justification,
        x=round(x, 2),
        y=round(y, 2),
        text=text,
        font_size=round(font_size, 2),
        color_r=color_r,
        color_g=color_g,
        color_b=color_b,
        leading=round(leading, 2),
    )
```

### Step 4: 写主导出函数

```python
def export_psd_with_jsx(
    clean_image_path: str,
    typeset_data: dict,
    output_psd_path: str,
    script_only: bool = False,
    verbose: bool = False,
) -> Optional[str]:
    """生成 JSX 脚本并调用 Photoshop 创建分层 PSD。

    Args:
        clean_image_path: 干净底图路径（inpaint 产物）
        typeset_data: typeset JSON 数据（含 rendered_items）
        output_psd_path: 输出 PSD 路径
        script_only: 只生成 JSX 脚本，不调用 Photoshop
        verbose: 保留 JSX 脚本到输出目录旁

    Returns:
        成功返回 PSD 路径，失败返回 None（script_only 时返回 JSX 路径）
    """
    temp_dir = tempfile.gettempdir()
    jsx_file = os.path.join(temp_dir, ".amta_psd_script.jsx")
    error_file = os.path.join(temp_dir, ".amta_psd_error.txt")

    # 清理旧错误文件
    if os.path.exists(error_file):
        try:
            os.unlink(error_file)
        except OSError:
            pass

    # 生成文字层代码
    text_layers_code = ""
    rendered_items = typeset_data.get("rendered_items", [])
    logger.info(f"PSD 导出：准备 {len(rendered_items)} 个文字层")
    for i, item in enumerate(rendered_items):
        layer_jsx = _generate_text_layer_jsx(i, item)
        if layer_jsx:
            text_layers_code += layer_jsx

    # 生成完整 JSX
    jsx_script = _JSX_TEMPLATE.format(
        input_file=_escape_jsx_path(clean_image_path),
        output_file=_escape_jsx_path(output_psd_path),
        error_file=_escape_jsx_path(error_file),
        text_layers_code=text_layers_code,
    )

    # 保存 JSX（UTF-8 BOM，确保 Photoshop 正确读取中文）
    os.makedirs(os.path.dirname(output_psd_path) or ".", exist_ok=True)
    with open(jsx_file, "w", encoding="utf-8-sig") as f:
        f.write(jsx_script)
    logger.info(f"JSX 脚本已生成: {jsx_file}")

    # verbose 模式：复制 JSX 到输出目录旁
    saved_script_path = None
    if verbose or script_only:
        debug_jsx = str(Path(output_psd_path).with_suffix(".jsx"))
        with open(debug_jsx, "w", encoding="utf-8") as f:
            f.write(jsx_script)
        saved_script_path = debug_jsx
        logger.info(f"JSX 脚本已保存: {debug_jsx}")

    if script_only:
        logger.info("仅脚本模式：跳过 Photoshop 执行")
        return saved_script_path

    # 查找并调用 Photoshop
    ps_exe = _find_photoshop_executable()
    if not ps_exe:
        logger.error("未找到 Photoshop，无法生成 PSD。可使用 script_only=True 只生成 JSX 脚本。")
        return None

    logger.info(f"使用 Photoshop: {ps_exe}")

    # 记录旧文件时间
    old_mtime = os.path.getmtime(output_psd_path) if os.path.exists(output_psd_path) else 0

    # 启动 Photoshop 执行脚本
    process = subprocess.Popen(
        [ps_exe, "-r", jsx_file],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # 轮询等待 PSD 生成（最多 300 秒）
    timeout = 300
    poll_interval = 0.5
    elapsed = 0.0
    while elapsed < timeout:
        time.sleep(poll_interval)
        elapsed += poll_interval
        if os.path.exists(output_psd_path):
            new_mtime = os.path.getmtime(output_psd_path)
            if new_mtime > old_mtime and os.path.getsize(output_psd_path) > 0:
                time.sleep(0.5)  # 确保写入完成
                break

    # 检查错误
    if os.path.exists(error_file):
        with open(error_file, "r", encoding="utf-8", errors="replace") as f:
            error_msg = f.read()
        logger.error(f"Photoshop 脚本错误: {error_msg}")
        return None

    if os.path.exists(output_psd_path) and os.path.getsize(output_psd_path) > 0:
        logger.info(f"PSD 已生成: {output_psd_path}")
        # 清理临时 JSX（非 verbose 模式）
        if not verbose and os.path.exists(jsx_file):
            try:
                os.unlink(jsx_file)
            except OSError:
                pass
        return output_psd_path

    logger.error(f"PSD 生成失败或超时（{timeout}秒）")
    return None
```

### Step 5: 写 Photoshop 查找函数（照抄 manga-translator-ui）

```python
def _find_photoshop_executable() -> Optional[str]:
    """查找 Photoshop 可执行文件路径。

    查找顺序：环境变量 PHOTOSHOP_PATH → Windows 注册表 → 常见安装路径
    """
    # 1. 环境变量
    ps_path = os.getenv("PHOTOSHOP_PATH")
    if ps_path and os.path.exists(ps_path):
        return ps_path

    if platform.system() != "Windows":
        logger.warning("PSD 导出仅支持 Windows（需要 Photoshop）")
        return None

    # 2. 注册表
    try:
        import winreg
        registry_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Adobe\Photoshop"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Adobe\Photoshop"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Adobe\Photoshop"),
        ]
        for hkey, subkey in registry_paths:
            try:
                with winreg.OpenKey(hkey, subkey) as key:
                    versions = []
                    i = 0
                    while True:
                        try:
                            versions.append(winreg.EnumKey(key, i))
                            i += 1
                        except OSError:
                            break
                    versions.sort(reverse=True)
                    for version in versions:
                        try:
                            with winreg.OpenKey(hkey, f"{subkey}\\{version}") as vk:
                                for val_name in ["ApplicationPath", "InstallPath", "Path"]:
                                    try:
                                        install_path, _ = winreg.QueryValueEx(vk, val_name)
                                        ps_exe = os.path.join(install_path, "Photoshop.exe")
                                        if os.path.exists(ps_exe):
                                            return ps_exe
                                    except FileNotFoundError:
                                        continue
                        except OSError:
                            continue
            except FileNotFoundError:
                continue
    except ImportError:
        pass

    # 3. 常见路径
    possible_paths = [
        r"C:\Program Files\Adobe\Adobe Photoshop 2025\Photoshop.exe",
        r"C:\Program Files\Adobe\Adobe Photoshop 2024\Photoshop.exe",
        r"C:\Program Files\Adobe\Adobe Photoshop 2023\Photoshop.exe",
        r"C:\Program Files\Adobe\Adobe Photoshop 2022\Photoshop.exe",
    ]
    program_files_x86 = os.getenv("ProgramFiles(x86)")
    if program_files_x86:
        possible_paths += [p.replace(r"C:\Program Files", program_files_x86) for p in possible_paths]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    # 4. 遍历 Adobe 目录
    for pf_var in ["ProgramFiles", "ProgramFiles(x86)"]:
        pf = os.getenv(pf_var)
        if not pf:
            continue
        adobe_dir = os.path.join(pf, "Adobe")
        if os.path.exists(adobe_dir):
            try:
                for folder in sorted(os.listdir(adobe_dir), reverse=True):
                    if "Photoshop" in folder:
                        ps_exe = os.path.join(adobe_dir, folder, "Photoshop.exe")
                        if os.path.exists(ps_exe):
                            return ps_exe
            except OSError:
                pass

    return None
```

### Step 6: 写单元测试

```python
# tests/test_psd_jsx_export.py
import json
from pathlib import Path

import pytest

from amta.typeset.psd_jsx_export import (
    _escape_jsx_path,
    _escape_jsx_string,
    _generate_text_layer_jsx,
    _hex_to_rgb,
    _resolve_font_family,
)


class TestEscapeFunctions:
    def test_escape_jsx_string_basic(self):
        assert _escape_jsx_string("hello") == "hello"

    def test_escape_jsx_string_single_quote(self):
        assert _escape_jsx_string("it's") == "it\\'s"

    def test_escape_jsx_string_newline(self):
        assert _escape_jsx_string("line1\nline2") == "line1\\rline2"

    def test_escape_jsx_path_windows(self):
        assert _escape_jsx_path(r"C:\test\file.png") == "C:/test/file.png"


class TestFontResolution:
    def test_known_font(self):
        assert _resolve_font_family("msyh.ttc") == "Microsoft YaHei"

    def test_unknown_font(self):
        assert _resolve_font_family("myfont.ttf") == "myfont"


class TestColorConversion:
    def test_black(self):
        assert _hex_to_rgb("#000000") == (0, 0, 0)

    def test_white(self):
        assert _hex_to_rgb("#FFFFFF") == (255, 255, 255)


class TestTextLayerJsx:
    def _make_item(self, **kwargs):
        item = {
            "region_id": "r00",
            "lines": ["测试文字"],
            "font_size": 52,
            "anchor_pos": [1000, 500],
            "layout_direction": "horizontal",
            "font_family": "msyh.ttc",
            "rendered_color": "#000000",
        }
        item.update(kwargs)
        return item

    def test_horizontal_layer_generates_code(self):
        jsx = _generate_text_layer_jsx(0, self._make_item())
        assert "Direction.HORIZONTAL" in jsx
        assert "Justification.CENTER" in jsx
        assert "测试文字" in jsx
        assert "Microsoft YaHei" in jsx

    def test_vertical_layer_generates_code(self):
        jsx = _generate_text_layer_jsx(1, self._make_item(layout_direction="vertical"))
        assert "Direction.VERTICAL" in jsx
        assert "Justification.LEFT" in jsx

    def test_multiline_text(self):
        jsx = _generate_text_layer_jsx(0, self._make_item(lines=["第一行", "第二行"]))
        assert "第一行\\r第二行" in jsx

    def test_empty_lines_returns_empty(self):
        assert _generate_text_layer_jsx(0, self._make_item(lines=[])) == ""

    def test_position_horizontal_centered(self):
        """横排居中：x = anchor_x，y 包含基线偏移"""
        jsx = _generate_text_layer_jsx(0, self._make_item(anchor_pos=[1000, 500], font_size=52))
        assert "1000" in jsx  # x 不变
        # y 应该 ≈ 500 + 52*0.35 = 518.2（单行时 offset=0）

    def test_position_vertical_offset(self):
        """竖排多列：x 向右偏移，y 向上偏移"""
        jsx = _generate_text_layer_jsx(
            0, self._make_item(layout_direction="vertical", lines=["abc", "def"], anchor_pos=[1000, 500], font_size=40)
        )
        # x = 1000 + (2-1)*48/2 = 1024
        assert "1024" in jsx
```

- [ ] **Step 7: 运行测试确认通过**

Run: `uv run python -m pytest tests/test_psd_jsx_export.py -v`
Expected: 8 tests PASS

- [ ] **Step 8: Commit**

```bash
git add src/amta/typeset/psd_jsx_export.py tests/test_psd_jsx_export.py
git commit -m "feat(typeset): add PSD JSX export module (manga-translator-ui style)"
```

---

## Task 2: 真实 PSD 生成验证 — 用 psd-verify 工作区测试

**Files:**
- Modify: 无（只运行脚本验证）

### Step 1: 写临时验证脚本

```python
# scripts/probes/verify_psd_jsx.py
"""验证 PSD JSX 导出：用 psd-verify 工作区的真实数据生成 PSD。"""
import json
import sys
from pathlib import Path

# 将项目根加入 path
sys.path.insert(0, str(Path(__file__).parent.parent))

from amta.typeset.psd_jsx_export import export_psd_with_jsx

WORKSPACE = Path(r"E:\manga translator agent\workspace\psd-verify")
CLEAN_IMG = WORKSPACE / "artifacts" / "inpaint" / "page_1.png"  # 或实际路径
TYPESET_JSON = WORKSPACE / "artifacts" / "typeset" / "page_1.json"
OUTPUT_PSD = WORKSPACE / "artifacts" / "psd" / "page_1_jsx.psd"

# 找到干净底图（可能在不同路径）
candidates = list(WORKSPACE.rglob("*clean*")) + list(WORKSPACE.rglob("*inpaint*"))
print("候选底图:", candidates)

with open(TYPESET_JSON, "r", encoding="utf-8") as f:
    typeset_data = json.load(f)

result = export_psd_with_jsx(
    clean_image_path=str(CLEAN_IMG),
    typeset_data=typeset_data,
    output_psd_path=str(OUTPUT_PSD),
    verbose=True,  # 保留 JSX 方便调试
)
print(f"结果: {result}")
```

### Step 2: 先只生成 JSX 脚本（不调用 Photoshop），检查脚本内容

Run: `uv run python scripts/probes/verify_psd_jsx.py`（先把 script_only=True）
Expected: 生成 `page_1_jsx.jsx`，手动检查：
- 4 个文字层都在
- 字体名是 "Microsoft YaHei"
- 位置坐标合理（横排 x≈anchor_x，竖排 x 有偏移）
- 文字内容正确，换行用 \r

### Step 3: 调用 Photoshop 生成 PSD

修改脚本为 `script_only=False`，运行。
Expected: Photoshop 启动，执行脚本，生成 `page_1_jsx.psd`

### Step 4: 视觉验证 — 和成品图对比

用 Photoshop 打开生成的 PSD，截图对比：
- 底图是否正确显示
- 4 个文字层是否都在图层面板
- 文字大小是否和成品图一致
- 文字位置是否和成品图一致
- 竖排文字方向是否正确

如果位置有偏差，调整 `_generate_text_layer_jsx` 中的 baseline_offset 和 leading_factor。

- [ ] **Step 5: Commit 验证脚本**

```bash
git add scripts/probes/verify_psd_jsx.py
git commit -m "chore: add PSD JSX verification probe"
```

---

## Task 3: 集成到 typeset 阶段 — orchestrator 调用

**Files:**
- Modify: `src/amta/orchestrator/` 中调用 typeset 的文件（需先定位）
- Modify: `src/amta/typeset/__init__.py`（导出新函数）

### Step 1: 定位 typeset 完成后的产物保存位置

Run: `uv run python scripts/peek.py` 查看 stage registry
Expected: 找到 typeset stage 的输出处理逻辑

### Step 2: 在 typeset stage 完成后可选调用 PSD 导出

在 typeset stage 的 `run()` 方法末尾，添加：

```python
# PSD 导出（可选，默认关闭）
if self.config.get("export_psd", False):
    from amta.typeset.psd_jsx_export import export_psd_with_jsx
    clean_path = ...  # inpaint 产物路径
    psd_path = work_dir / "psd" / f"{page_id}.psd"
    export_psd_with_jsx(
        clean_image_path=str(clean_path),
        typeset_data=typeset_result,
        output_psd_path=str(psd_path),
    )
```

### Step 3: 添加配置项

在配置 schema 中添加 `export_psd: bool = False` 和 `psd_script_only: bool = False`。

- [ ] **Step 4: 运行完整 pipeline 测试**

Run: `uv run python scripts/run_pipeline.py --work-id psd-verify --stages typeset --export-psd`
Expected: typeset 完成后自动生成 PSD

- [ ] **Step 5: Commit**

```bash
git add src/amta/orchestrator/ src/amta/typeset/__init__.py
git commit -m "feat(orchestrator): integrate PSD JSX export into typeset stage"
```

---

## Task 4: 清理旧代码和最终验证

**Files:**
- Modify: `tests/test_psd_export.py`（标记废弃或删除）
- Modify: `src/amta/typeset/psd_export.py`（添加废弃警告）

### Step 1: 旧模块添加废弃警告

在 `psd_export.py` 顶部添加：
```python
import warnings
warnings.warn(
    "psd_export (photoshopapi) is deprecated. Use psd_jsx_export instead.",
    DeprecationWarning,
    stacklevel=2,
)
```

### Step 2: 运行完整测试套件

Run: `uv run python -m pytest -q`
Expected: 所有测试通过

### Step 3: 运行项目检查

Run: `npm run check`
Expected: lint, type, root checks 全部通过

### Step 4: 最终 PSD 验证

用 psd-verify 工作区生成最终 PSD，在 Photoshop 中确认：
- [ ] 干净底图层正常显示
- [ ] N 个文字层都在图层面板
- [ ] 文字大小与成品图一致
- [ ] 文字位置与成品图一致
- [ ] 竖排文字方向正确
- [ ] 文字可编辑（双击可改）

- [ ] **Step 5: Commit 和 finish**

```bash
git add -A
git commit -m "chore: deprecate old psd_export, finalize JSX export"
npm run finish -- "PSD JSX export: clean base + editable text layers via Photoshop"
```

---

## 关键决策点（需要用户确认）

1. **是否需要 Photoshop？** 此方案必须安装 Photoshop。如果用户需要在无 Photoshop 环境导出，需保留旧的像素图层方案作为 fallback。
2. **位置精度**：Point Text 的位置计算基于经验值（baseline_offset=0.35*font_size），首次生成后可能需要微调。计划中 Task 2 包含视觉验证和调整步骤。
3. **旧代码处理**：旧的 `psd_export.py`（photoshopapi 方案）是删除还是保留为 deprecated？建议保留为 deprecated，不删除。
4. **分支策略**：建议从 main 新建 `feat/psd-jsx-export` 分支，因为当前 `codex/psd-export` 分支积累了大量旧方案的尝试性修改。
