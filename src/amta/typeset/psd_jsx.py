"""JSX 脚本生成 — 纯字符串操作，无 I/O、无 Photoshop 调用。

从 psd_jsx_export.py 拆出。本模块不关心 Photoshop 在哪、怎么调；
只负责把 typeset rendered_items 转成合法的 ExtendScript 脚本。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from amta.stores.artifacts import normalize_rendered_item
from amta.typeset.psd_text_descriptor import TEXT_DEFAULTS, TEXT_LAYER

logger = logging.getLogger(__name__)

# 字体文件名 → Photoshop 字体家族名
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


def resolve_font_family(font_family: str) -> str:
    """字体文件名 → PS 字体家族名；未映射的返回文件名（去掉扩展名）。"""
    if font_family in _FONT_FAMILY_MAP:
        return _FONT_FAMILY_MAP[font_family]
    return Path(font_family).stem


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """#RRGGBB → (r, g, b)，值范围 0-255。"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) < 6:
        return (0, 0, 0)
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
    )


def escape_jsx_string(text: str) -> str:
    """转义 JSX 单引号字符串中的特殊字符。"""
    if not text:
        return ""
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "\\'")
    text = text.replace("\n", "\\r")
    text = text.replace("\r", "\\r")
    text = text.replace("\t", "    ")
    return text


def escape_jsx_path(path: str) -> str:
    """Windows 路径 → JSX 安全路径（反斜杠转正斜杠，转义单引号）。"""
    if not path:
        return ""
    return path.replace("\\", "/").replace("'", "\\'")


# 竖排里连续 >=2 个标点（！？!?）需要并排：直接对真字符段縦中横，
# 让 PS 在竖排格子里横排居中。
_TCY_PUNCT = set("！？!?")


def has_conjoined_punct(text: str) -> bool:
    """文本里是否出现连续 >=2 个 ！？!?（需要縦中横并排）。"""
    run = 0
    for ch in text:
        if ch in _TCY_PUNCT:
            run += 1
            if run >= 2:
                return True
        else:
            run = 0
    return False


def normalize_vertical_punct(text: str) -> str:
    """半角 !/? 补全角（竖排全角更自然）。"""
    return text.replace("!", "！").replace("?", "？")


_JSX_TEMPLATE = """
#target photoshop

var ERROR_FILE_PATH = '{error_file}';
var COMPLETION_FILE_PATH = '{completion_file}';
var PROGRESS_FILE_PATH = '{progress_file}';
var CANCEL_FILE_PATH = '{cancel_file}';
var oldRulerUnits = app.preferences.rulerUnits;
var oldTypeUnits = app.preferences.typeUnits;
var oldDialogs = app.displayDialogs;
var oldDocument = app.documents.length ? app.activeDocument : null;
var doc = null;
var exportError = null;

function checkCancelled() {{
    if (CANCEL_FILE_PATH && new File(CANCEL_FILE_PATH).exists) throw new Error('Export cancelled after timeout');
}}

function reportProgress(stage, done) {{
    if (!PROGRESS_FILE_PATH) return;
    var f = new File(PROGRESS_FILE_PATH);
    if (f.open('a')) {{
        f.writeln('{{"stage":"' + stage + '","layers_done":' + done + ',"layers_total":{layer_count}}}');
        f.close();
    }}
}}

function findFontPostScriptName(fontName) {{
    if (!fontName) return null;
    var lowerName = fontName.toLowerCase();
    var fonts = app.fonts;
    for (var i = 0; i < fonts.length; i++) {{
        if (fonts[i].postScriptName.toLowerCase() === lowerName) return fonts[i].postScriptName;
    }}
    for (var i = 0; i < fonts.length; i++) {{
        if (fonts[i].name.toLowerCase() === lowerName) return fonts[i].postScriptName;
    }}
    for (var i = 0; i < fonts.length; i++) {{
        if (fonts[i].family.toLowerCase() === lowerName) return fonts[i].postScriptName;
    }}
    for (var i = 0; i < fonts.length; i++) {{
        var ps = fonts[i].postScriptName.toLowerCase();
        var nm = fonts[i].name.toLowerCase();
        var fm = fonts[i].family.toLowerCase();
        if (ps.indexOf(lowerName) !== -1 || nm.indexOf(lowerName) !== -1 || fm.indexOf(lowerName) !== -1)
            return fonts[i].postScriptName;
    }}
    return null;
}}

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

function isPunctCharForTcy(ch) {{
    return ch === '！' || ch === '？' || ch === '!' || ch === '?';
}}

function findTateChuYokoPositions(text) {{
    var positions = [];
    var i = 0;
    while (i < text.length) {{
        if (isPunctCharForTcy(text.charAt(i))) {{
            var start = i;
            while (i < text.length && isPunctCharForTcy(text.charAt(i))) i++;
            if (i - start >= 2) positions.push([start, i]);
        }} else {{
            i++;
        }}
    }}
    return positions;
}}

try {{
    checkCancelled();
    app.preferences.rulerUnits = Units.PIXELS;
    app.preferences.typeUnits = TypeUnits.PIXELS;
    app.displayDialogs = DialogModes.NO;
    var inputFile = new File('{input_file}');
    if (!inputFile.exists) throw new Error('Input file not found: ' + inputFile.fsName);
    reportProgress('opening', 0);
    doc = app.open(inputFile);
    try {{ if (doc.mode != DocumentMode.RGB) doc.changeMode(ChangeMode.RGB); }} catch(e) {{}}
    var baseLayer = null;
    try {{ if (doc.backgroundLayer) baseLayer = doc.backgroundLayer; }} catch(e) {{}}
    if (!baseLayer && doc.layers.length > 0) baseLayer = doc.layers[doc.layers.length - 1];
    if (baseLayer) {{
        baseLayer.name = '干净底图 (clean)';
        baseLayer.allLocked = true;
    }}
    {text_layers_code}
    checkCancelled();
    reportProgress('saving', {layer_count});
    var psdFile = new File('{output_file}');
    var psdOptions = new PhotoshopSaveOptions();
    psdOptions.embedColorProfile = true;
    psdOptions.alphaChannels = true;
    psdOptions.layers = true;
    psdOptions.spotColors = true;
    doc.saveAs(psdFile, psdOptions, true);
}} catch (e) {{
    exportError = 'ERROR: ' + e.message + '\\nLine: ' + e.line;
}} finally {{
    if (doc) {{ try {{ doc.close(SaveOptions.DONOTSAVECHANGES); }} catch(closeError) {{
        exportError = exportError || ('Close failed: ' + closeError.message);
    }} }}
    try {{ app.preferences.rulerUnits = oldRulerUnits; }} catch (rulerError) {{
        exportError = exportError || ('Restore units failed: ' + rulerError.message);
    }}
    try {{ app.preferences.typeUnits = oldTypeUnits; }} catch (typeError) {{
        exportError = exportError || ('Restore type units failed: ' + typeError.message);
    }}
    try {{ app.displayDialogs = oldDialogs; }} catch (dialogError) {{
        exportError = exportError || ('Restore dialogs failed: ' + dialogError.message);
    }}
    if (oldDocument) {{ try {{ app.activeDocument = oldDocument; }} catch(restoreError) {{}} }}
}}
try {{
    if (exportError) throw new Error(exportError);
    checkCancelled();
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
        var errFile = new File(ERROR_FILE_PATH + '.tmp');
        if (!errFile.open('w')) throw new Error('Cannot write error marker');
        errFile.write(errorMsg);
        errFile.close();
        errFile.rename(new File(ERROR_FILE_PATH).name);
    }} catch(we) {{}}
}}
"""

_TEXT_LAYER_TEMPLATE = """
    // 文字层 {index}: {name}
    var tl{index} = doc.artLayers.add();
    tl{index}.kind = LayerKind.TEXT;
    tl{index}.name = '{name}';

    var ti{index} = tl{index}.textItem;
    var dpiScale{index} = 72 / doc.resolution;

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

    var leadingVal{index} = {leading} * dpiScale{index};
    ti{index}.useAutoLeading = false;
    ti{index}.leading = new UnitValue(leadingVal{index}, 'pt');

    {tcy_code}
"""


def generate_text_layer_jsx(index: int, item: dict[str, Any], *, batched: bool = False) -> tuple[list[str], int]:
    """从 typeset rendered_item 生成文字层 JSX。

    Returns: (JSX 片段列表, 本区域消耗的图层数)。
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
    font_family = resolve_font_family(item.get("font_family", "msyh.ttc"))
    color_r, color_g, color_b = hex_to_rgb(item.get("rendered_color", "#000000"))
    num_lines = len(lines)

    leading_factor = 1.2 if is_vertical else 1.15
    leading = float(item.get("line_step", font_size * leading_factor))

    col_pitch = leading
    row_pitch = leading
    if is_vertical:
        from amta.typeset.typeset_render import iter_vertical_rows
        col_pitch = float(item.get("col_step", leading))
        row_pitch = leading
        lines_for_text = [normalize_vertical_punct(col) for col in lines]
        max_rows = max((len(iter_vertical_rows(c)) for c in lines_for_text), default=1)
        col_height = max_rows * row_pitch
        x = anchor_x + (num_lines - 1) * col_pitch / 2
        y = anchor_y - col_height / 2
        direction = "Direction.VERTICAL"
        justification = "Justification.LEFT"
    else:
        lines_for_text = lines
        x = anchor_x
        baseline_offset = font_size * 0.35
        y = anchor_y - (num_lines - 1) * leading / 2 + baseline_offset
        direction = "Direction.HORIZONTAL"
        justification = "Justification.CENTER"

    if not is_vertical and "ink_bbox" in item:
        left, top, right, _bottom = item["ink_bbox"]
        align = item["align"]
        x = left if align == "left" else right if align == "right" else (left + right) / 2
        y = top + font_size * 0.8
        justification = {"left": "Justification.LEFT", "right": "Justification.RIGHT",
                         "center": "Justification.CENTER"}[align]

    raw_text = "\r".join(lines_for_text)
    text = escape_jsx_string(raw_text)

    name_text = re.sub(r"[\r\n]", "", "".join(lines))[:20]
    name = escape_jsx_string(f"{region_id}: {name_text}")

    if is_vertical and has_conjoined_punct(raw_text):
        tcy_code = f"""
    var tcyPos{index} = findTateChuYokoPositions(ti{index}.contents);
    for (var ti_{index} = 0; ti_{index} < tcyPos{index}.length; ti_{index}++) {{
        applyTateChuYoko(tl{index}, tcyPos{index}[ti_{index}][0], tcyPos{index}[ti_{index}][1], {font_size});
    }}
"""
    else:
        tcy_code = ""

    template = TEXT_LAYER if batched else _TEXT_LAYER_TEMPLATE
    parts: list[str] = [template.format(
        index=index, name=name,
        font_family=escape_jsx_string(font_family),
        direction=direction, justification=justification,
        x=round(x, 2), y=round(y, 2), text=text,
        font_size=round(font_size, 2),
        color_r=color_r, color_g=color_g, color_b=color_b,
        leading=round(leading, 2), tcy_code=tcy_code,
    )]
    return parts, 1


def build_script(clean_image_path: str, output_psd_path: str,
                 error_path: str, completion_path: str,
                 typeset_data: dict[str, Any], *, progress_path: str = "", cancel_path: str = "",
                 legacy: bool = False) -> str:
    """组装完整 JSX 脚本：底图 + 文字层 + 保存。"""
    layer_parts: list[str] = []
    idx = 0
    for item in typeset_data.get("rendered_items", []):
        parts, consumed = generate_text_layer_jsx(idx, item, batched=not legacy)
        if consumed:
            layer_parts.append(f"checkCancelled(); reportProgress('layers', {idx});")
        layer_parts.extend(parts)
        idx += consumed
        if consumed:
            layer_parts.append(f"reportProgress('layers', {idx});")
    text_layers_code = "".join(layer_parts)
    if idx and not legacy:
        text_layers_code = TEXT_DEFAULTS + text_layers_code

    return _JSX_TEMPLATE.format(
        input_file=escape_jsx_path(str(Path(clean_image_path).resolve())),
        output_file=escape_jsx_path(str(Path(output_psd_path).resolve())),
        error_file=escape_jsx_path(error_path),
        completion_file=escape_jsx_path(completion_path),
        progress_file=escape_jsx_path(progress_path),
        cancel_file=escape_jsx_path(cancel_path),
        layer_count=idx,
        text_layers_code=text_layers_code,
    )
