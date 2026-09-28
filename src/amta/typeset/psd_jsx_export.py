"""PSD JSX 导出 — 生成 ExtendScript 脚本，调用 Photoshop 创建分层 PSD。

参考 manga-translator-ui/manga_translator/utils/photoshop_export.py 的成熟实现。
不直接写 PSD 二进制，而是生成 .jsx 脚本让 Photoshop 原生创建文字层，
100% 兼容 Photoshop，文字可编辑。

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
import threading
import time
from pathlib import Path
from typing import Any, Optional

from amta.stores.artifacts import normalize_rendered_item
logger = logging.getLogger(__name__)
_PHOTOSHOP_LOCK = threading.Lock()

# 字体文件名 → Photoshop 字体家族名
# JSX 中 findFontPostScriptName() 会用 5 轮匹配找到 PostScript 名称
_FONT_FAMILY_MAP: dict[str, str] = {
    "msyh.ttc": "Microsoft YaHei",
    "msyhbd.ttc": "Microsoft YaHei",
    "msyhl.ttc": "Microsoft YaHei",
    "simkai.ttf": "KaiTi",
    "simhei.ttf": "SimHei",
    "simsun.ttc": "SimSun",
    "simfang.ttf": "FangSong",
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
    if len(hex_color) < 6:
        return (0, 0, 0)
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


# ── JSX 模板 ──────────────────────────────────────────────────────────────

_JSX_TEMPLATE = """
#target photoshop

app.preferences.rulerUnits = Units.PIXELS;
app.preferences.typeUnits = TypeUnits.PIXELS;

var ERROR_FILE_PATH = '{error_file}';
var COMPLETION_FILE_PATH = '{completion_file}';

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

// 縦中横（Tate-chu-yoko）：让竖排里的组合标点连字（⁉⁈‼⁇）在格子内横过来并排，
// 由 Photoshop 字体引擎自己负责居中与位置——不叠层、不手算像素。
function applyTateChuYoko(textLayer, charStart, charEnd, fontSize) {{
    try {{
        app.activeDocument.activeLayer = textLayer;
        var idsetd = charIDToTypeID("setd");
        var desc1 = new ActionDescriptor();
        var idnull = charIDToTypeID("null");
        var ref1 = new ActionReference();
        ref1.putEnumerated(charIDToTypeID("TxLr"), charIDToTypeID("Ordn"), charIDToTypeID("Trgt"));
        desc1.putReference(idnull, ref1);
        var idT = charIDToTypeID("T   ");
        var desc2 = new ActionDescriptor();
        var idTxtt = charIDToTypeID("Txtt");
        var list1 = new ActionList();
        var desc3 = new ActionDescriptor();
        desc3.putInteger(charIDToTypeID("From"), charStart);
        desc3.putInteger(charIDToTypeID("T   "), charEnd);
        var idTxtS = charIDToTypeID("TxtS");
        var desc4 = new ActionDescriptor();
        desc4.putBoolean(stringIDToTypeID("styleSheetHasParent"), true);
        var idPxl = charIDToTypeID("#Pxl");
        desc4.putUnitDouble(charIDToTypeID("Sz  "), idPxl, fontSize);
        desc4.putUnitDouble(stringIDToTypeID("impliedFontSize"), idPxl, fontSize);
        var idbd = stringIDToTypeID("baselineDirection");
        desc4.putEnumerated(idbd, idbd, charIDToTypeID("Crs "));
        desc3.putObject(idTxtS, idTxtS, desc4);
        list1.putObject(idTxtt, desc3);
        desc2.putList(idTxtt, list1);
        desc1.putObject(idT, charIDToTypeID("TxLr"), desc2);
        executeAction(idsetd, desc1, DialogModes.NO);
        return true;
    }} catch (e) {{
        $.writeln('WARNING: Failed to apply TateChuYoko: ' + e.message);
        return false;
    }}
}}

function findTateChuYokoPositions(text) {{
    var positions = [];
    var tcyChars = ['⁉', '⁈', '‼', '⁇'];
    for (var i = 0; i < text.length; i++) {{
        var ch = text.charAt(i);
        for (var j = 0; j < tcyChars.length; j++) {{
            if (ch === tcyChars[j]) {{ positions.push([i, i + 1]); break; }}
        }}
    }}
    return positions;
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
    var doneFile = new File(COMPLETION_FILE_PATH + '.tmp');
    if (!doneFile.open('w')) throw new Error('Cannot write completion marker');
    doneFile.write('complete');
    doneFile.close();
    if (!doneFile.rename(new File(COMPLETION_FILE_PATH).name)) {{
        throw new Error('Cannot publish completion marker');
    }}

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

    {tcy_code}
"""

# 竖排组合标点 → Unicode 连字（抄 manga-translator-ui 的成熟做法）。
# PS 竖排会把 ！？ 逐字上下堆叠；把它们换成单个连字 ⁉ 后，再用縦中横让 PS
# 自己在格子里横排居中——位置/对齐全交给字体引擎，不叠层、不手算像素。
_VERTICAL_LIGATURE_MAP = (
    ("！？", "⁉"),
    ("？！", "⁈"),
    ("！！", "‼"),
    ("？？", "⁇"),
    ("!?", "⁉"),
    ("?!", "⁈"),
    ("!!", "‼"),
    ("??", "⁇"),
)
_TCY_CHARS = "⁉⁈‼⁇"


def _vertical_ligature(text: str) -> str:
    """把竖排文本里的成对标点组合换成 Unicode 连字（⁉⁈‼⁇）。

    与参考项目一致：先替换成对组合，再把单个半角 !/? 补全角。
    """
    for src, dst in _VERTICAL_LIGATURE_MAP:
        text = text.replace(src, dst)
    text = text.replace("!", "！").replace("?", "？")
    return text


def _generate_text_layer_jsx(index: int, item: dict[str, Any]) -> tuple[list[str], int]:
    """从 typeset rendered_item 生成文字层 JSX。

    位置计算参考 manga-translator-ui：
    - 横排：Point Text position = [中心x, 第一行基线y]，居中对齐
    - 竖排：Point Text position = [第一列中心x, 顶部y]，左对齐(=顶部)
    anchor_pos 是整个文字块的中心点，需要根据行数偏移到第一行/列。

    # 竖排成对标点（！？）换成连字 ⁉ 后由 Photoshop 縦中横并排，位置自动对齐。
    Returns:
        (JSX 片段列表, 本区域消耗的图层数)。
    """
    region_id = item.get("region_id", f"r{index}")
    lines = item.get("lines", [])
    if not lines:
        logger.warning(f"文字层 {index} ({region_id}) 无文字内容，跳过")
        return [], 0

    item = normalize_rendered_item(item)
    font_size = float(item.get("font_size", 40))
    anchor_pos = item.get("anchor_pos", [0, 0])
    anchor_x, anchor_y = float(anchor_pos[0]), float(anchor_pos[1])
    is_vertical = item.get("layout_direction", "vertical") == "vertical"
    font_family = _resolve_font_family(item.get("font_family", "msyh.ttc"))
    color_r, color_g, color_b = _hex_to_rgb(item.get("rendered_color", "#000000"))
    num_lines = len(lines)

    # 行间距（y 方向）= line_step = ascent+descent；横排时它同时就是行距。
    leading_factor = 1.2 if is_vertical else 1.15
    leading = float(item.get("line_step", font_size * leading_factor))

    # ── 竖排 ──
    col_pitch = leading  # 横排不区分列/行间距
    row_pitch = leading
    if is_vertical:
        from amta.typeset.typeset_render import iter_vertical_rows

        # 竖排有两个不同的间距，绝不能混用：
        #   col_pitch = col_step = 字宽（x 方向列间距）
        #   row_pitch = line_step = ascent+descent（y 方向行间距）
        col_pitch = float(item.get("col_step", leading))
        row_pitch = leading

        # 成对标点换成连字 ⁉⁈‼⁇，交给 PS 縦中横横排居中。
        lines_for_text = [_vertical_ligature(col) for col in lines]
        # 列高按"实际渲染行数"算（连字/縦中横各占一行），不能按 len(line) 数字符。
        # 连字是单字符，iter_vertical_rows 自然算一行，与 PNG 一致。
        max_rows = max((len(iter_vertical_rows(c)) for c in lines_for_text), default=1)
        col_height = max_rows * row_pitch
        # 列从右向左排，第一列在最右侧
        x = anchor_x + (num_lines - 1) * col_pitch / 2
        y = anchor_y - col_height / 2
        direction = "Direction.VERTICAL"
        justification = "Justification.LEFT"  # 竖排 LEFT = 顶部对齐
    else:
        lines_for_text = lines
        x = anchor_x
        baseline_offset = font_size * 0.35  # 经验值，manga-translator-ui 用 0.35
        y = anchor_y - (num_lines - 1) * leading / 2 + baseline_offset
        direction = "Direction.HORIZONTAL"
        justification = "Justification.CENTER"

    # VLM layout records actual ink bounds and alignment, not only a center.
    if not is_vertical and "ink_bbox" in item:
        left, top, right, _bottom = item["ink_bbox"]
        align = item["align"]
        x = left if align == "left" else right if align == "right" else (left + right) / 2
        y = top + font_size * 0.8
        justification = {"left": "Justification.LEFT", "right": "Justification.RIGHT",
                         "center": "Justification.CENTER"}[align]

    # 文字内容：多行用 \r 连接（PS 换行符）
    raw_text = "\r".join(lines_for_text)
    text = _escape_jsx_string(raw_text)

    # 图层名：region_id + 文字前20字
    name_text = re.sub(r"[\r\n]", "", "".join(lines))[:20]
    name = _escape_jsx_string(f"{region_id}: {name_text}")

    # 縦中横：本层若含连字，让 PS 扫描自身 contents 并对这些字符横排。
    if is_vertical and any(ch in raw_text for ch in _TCY_CHARS):
        tcy_code = f"""
    var tcyPos{index} = findTateChuYokoPositions(ti{index}.contents);
    for (var ti_{index} = 0; ti_{index} < tcyPos{index}.length; ti_{index}++) {{
        applyTateChuYoko(tl{index}, tcyPos{index}[ti_{index}][0], tcyPos{index}[ti_{index}][1], {font_size});
    }}
"""
    else:
        tcy_code = ""

    logger.debug(
        f"文字层 {index} ({region_id}): "
        f"{'竖排' if is_vertical else '横排'} "
        f"font={font_size} anchor=({anchor_x:.0f},{anchor_y:.0f}) "
        f"pos=({x:.1f},{y:.1f}) lines={num_lines} tcy={'yes' if tcy_code else 'no'}"
    )

    parts: list[str] = [_TEXT_LAYER_TEMPLATE.format(
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
        tcy_code=tcy_code,
    )]

    return parts, 1  # 每个区域一个文字层（縦中横不另开层）


# ── Photoshop 查找 ────────────────────────────────────────────────────────

def _find_photoshop_executable() -> Optional[str]:
    """查找 Photoshop 可执行文件路径。

    查找顺序：环境变量 PHOTOSHOP_PATH → Windows 注册表 → 常见安装路径 → 遍历 Adobe 目录
    """
    # 1. 环境变量
    ps_path = os.getenv("PHOTOSHOP_PATH")
    if ps_path and os.path.exists(ps_path):
        logger.info(f"从环境变量找到 Photoshop: {ps_path}")
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
                                            logger.info(f"从注册表找到 Photoshop: {ps_exe}")
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
        r"C:\Program Files\Adobe\Adobe Photoshop 2021\Photoshop.exe",
    ]
    program_files_x86 = os.getenv("ProgramFiles(x86)")
    if program_files_x86:
        possible_paths += [p.replace(r"C:\Program Files", program_files_x86) for p in possible_paths]

    for path in possible_paths:
        if os.path.exists(path):
            logger.info(f"从常见路径找到 Photoshop: {path}")
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
                            logger.info(f"从 Adobe 目录找到 Photoshop: {ps_exe}")
                            return ps_exe
            except OSError:
                pass

    logger.warning("未找到 Photoshop 安装")
    return None


# ── 主导出函数 ────────────────────────────────────────────────────────────

def export_psd_with_jsx(
    clean_image_path: str,
    typeset_data: dict[str, Any],
    output_psd_path: str,
    script_only: bool = False,
    verbose: bool = False,
    timeout: int = 300,
) -> Optional[str]:
    """生成 JSX 脚本并调用 Photoshop 创建分层 PSD。

    Args:
        clean_image_path: 干净底图路径（inpaint 产物）
        typeset_data: typeset JSON 数据（含 rendered_items 列表）
        output_psd_path: 输出 PSD 路径
        script_only: 只生成 JSX 脚本，不调用 Photoshop
        verbose: 保留 JSX 脚本到输出目录旁
        timeout: 等待 Photoshop 生成 PSD 的超时秒数

    Returns:
        成功返回 PSD 路径；script_only 时返回 JSX 路径；失败返回 None
    """
    if not os.path.isfile(clean_image_path):
        logger.error("Clean image does not exist: %s", clean_image_path)
        return None

    layer_parts: list[str] = []
    idx = 0
    for item in typeset_data.get("rendered_items", []):
        parts, consumed = _generate_text_layer_jsx(idx, item)
        layer_parts.extend(parts)
        idx += consumed
    text_layers_code = "".join(layer_parts)
    output = Path(output_psd_path).resolve()

    def make_script(target: Path, error: Path, completion: Path) -> str:
        return _JSX_TEMPLATE.format(
            input_file=_escape_jsx_path(str(Path(clean_image_path).resolve())),
            output_file=_escape_jsx_path(str(target)),
            error_file=_escape_jsx_path(str(error)),
            completion_file=_escape_jsx_path(str(completion)),
            text_layers_code=text_layers_code,
        )

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        if verbose or script_only:
            # Keep the manual script usable after temporary runtime files disappear.
            saved_script = Path(output_psd_path).with_suffix(".jsx")
            saved_script.write_text(make_script(
                output, output.with_suffix(".error.txt"), output.with_suffix(".complete")
            ), encoding="utf-8-sig")
            if script_only:
                return str(saved_script)

        if timeout <= 0:
            logger.error("Photoshop execution timed out (%s seconds)", timeout)
            return None
        ps_exe = _find_photoshop_executable()
        if not ps_exe:
            logger.error("Photoshop not found; use script_only=True for manual export")
            return None

        # Photoshop has global document state. Serialize GUI calls within this process.
        with _PHOTOSHOP_LOCK, tempfile.TemporaryDirectory(
            prefix=".amta-psd-", dir=output.parent, ignore_cleanup_errors=True
        ) as temp_dir:
            runtime = Path(temp_dir)
            jsx_file = runtime / "export.jsx"
            error_file = runtime / "error.txt"
            completion_file = runtime / "complete.txt"
            staged_output = runtime / "output.psd"
            jsx_file.write_text(make_script(staged_output, error_file, completion_file),
                                encoding="utf-8-sig")
            subprocess.Popen(
                [ps_exe, "-r", str(jsx_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if error_file.exists():
                    logger.error("Photoshop script error: %s", error_file.read_text(
                        encoding="utf-8", errors="replace"))
                    return None
                if completion_file.exists():
                    if (completion_file.read_text(encoding="utf-8") != "complete"
                            or not staged_output.is_file() or staged_output.stat().st_size == 0):
                        logger.error("Photoshop completed without a valid staged PSD")
                        return None
                    # Fresh per-invocation file; atomic publication preserves any old PSD on failure.
                    os.replace(staged_output, output)
                    logger.info("PSD generated: %s", output_psd_path)
                    return output_psd_path
                time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
            logger.error("Photoshop execution timed out (%s seconds)", timeout)
            return None
    except OSError:
        logger.exception("PSD export failed: %s", output_psd_path)
        return None



def export_page_psd(
    artifacts_dir: Path,
    page: str,
    output_path: Path,
    script_only: bool = False,
    verbose: bool = False,
) -> Optional[str]:
    """便捷接口：从 artifacts 目录读取 clean 图和 typeset JSON，导出 PSD。

    与旧 psd_export.export_page_psd 接口保持一致，方便 orchestrator 适配器替换。

    Args:
        artifacts_dir: 工作区 artifacts 目录
        page: 页面名（如 "page_1"）
        output_path: 输出 PSD 路径
        script_only: 只生成 JSX 脚本
        verbose: 保留 JSX 脚本

    Returns:
        成功返回路径，失败返回 None
    """
    from amta.common.paths import read_json

    # 读取 inpaint.json 获取 clean 图路径
    inpaint_path = artifacts_dir / "inpaint" / f"{page}.json"
    if not inpaint_path.exists():
        # 尝试其他路径模式
        inpaint_path = artifacts_dir / f"{page}_inpaint.json"
    if not inpaint_path.exists():
        logger.error(f"找不到 inpaint 产物: {inpaint_path}")
        return None

    inpaint_doc = read_json(inpaint_path)
    clean_image_name = inpaint_doc.get("clean_image", "")
    if not clean_image_name:
        logger.error("inpaint.json 中缺少 clean_image 字段")
        return None

    clean_path = artifacts_dir / clean_image_name
    if not clean_path.exists():
        logger.error(f"干净底图不存在: {clean_path}")
        return None

    # 读取 typeset JSON
    typeset_path = artifacts_dir / "typeset" / f"{page}.json"
    if not typeset_path.exists():
        typeset_path = artifacts_dir / f"{page}_typeset.json"
    if not typeset_path.exists():
        logger.error(f"找不到 typeset 产物: {typeset_path}")
        return None

    typeset_data = read_json(typeset_path)

    return export_psd_with_jsx(
        clean_image_path=str(clean_path),
        typeset_data=typeset_data,
        output_psd_path=str(output_path),
        script_only=script_only,
        verbose=verbose,
    )
