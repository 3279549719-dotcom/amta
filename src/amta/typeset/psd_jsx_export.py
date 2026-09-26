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
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

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


def _generate_text_layer_jsx(index: int, item: dict[str, Any]) -> str:
    """从 typeset rendered_item 生成单个文字层的 JSX 代码。

    位置计算参考 manga-translator-ui：
    - 横排：Point Text position = [中心x, 第一行基线y]，居中对齐
    - 竖排：Point Text position = [第一列中心x, 顶部y]，左对齐(=顶部)
    anchor_pos 是整个文字块的中心点，需要根据行数偏移到第一行/列。
    """
    region_id = item.get("region_id", f"r{index}")
    lines = item.get("lines", [])
    if not lines:
        logger.warning(f"文字层 {index} ({region_id}) 无文字内容，跳过")
        return ""

    font_size = float(item.get("font_size", 40))
    anchor_pos = item.get("anchor_pos", [0, 0])
    anchor_x, anchor_y = float(anchor_pos[0]), float(anchor_pos[1])
    is_vertical = item.get("layout_direction", "horizontal") == "vertical"
    font_family = _resolve_font_family(item.get("font_family", "msyh.ttc"))
    color_r, color_g, color_b = _hex_to_rgb(item.get("rendered_color", "#000000"))

    # 文字内容：多行用 \r 连接（PS 换行符）
    raw_text = "\r".join(lines)
    text = _escape_jsx_string(raw_text)
    num_lines = len(lines)

    # 行间距系数
    leading_factor = 1.2 if is_vertical else 1.15
    leading = font_size * leading_factor

    # 位置计算
    if is_vertical:
        # 竖排：列从右向左排，第一列在最右侧
        # x = 中心 + (列数-1)*行间距/2
        x = anchor_x + (num_lines - 1) * leading / 2
        # y = 第一列顶部 = 中心 - 单列高度/2
        # 单列高度估算：最长行的字符数 * font_size
        max_chars = max(len(line) for line in lines)
        col_height = max_chars * font_size
        y = anchor_y - col_height / 2
        direction = "Direction.VERTICAL"
        justification = "Justification.LEFT"  # 竖排 LEFT = 顶部对齐
    else:
        # 横排：居中对齐
        # x = 中心
        x = anchor_x
        # y = 第一行基线 = 中心 - (行数-1)*行间距/2 + 基线偏移
        baseline_offset = font_size * 0.35  # 经验值，manga-translator-ui 用 0.35
        y = anchor_y - (num_lines - 1) * leading / 2 + baseline_offset
        direction = "Direction.HORIZONTAL"
        justification = "Justification.CENTER"

    # 图层名：region_id + 文字前20字
    name_text = re.sub(r"[\r\n]", "", "".join(lines))[:20]
    name = _escape_jsx_string(f"{region_id}: {name_text}")

    logger.debug(
        f"文字层 {index} ({region_id}): "
        f"{'竖排' if is_vertical else '横排'} "
        f"font={font_size} anchor=({anchor_x:.0f},{anchor_y:.0f}) "
        f"pos=({x:.1f},{y:.1f}) lines={num_lines}"
    )

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
    temp_dir = tempfile.gettempdir()
    jsx_file = os.path.join(temp_dir, ".amta_psd_script.jsx")
    error_file = os.path.join(temp_dir, ".amta_psd_error.txt")

    # 清理旧错误文件
    if os.path.exists(error_file):
        try:
            os.unlink(error_file)
        except OSError:
            pass

    # 检查底图
    if not os.path.exists(clean_image_path):
        logger.error(f"干净底图不存在: {clean_image_path}")
        return None

    # 生成文字层代码
    text_layers_code = ""
    rendered_items = typeset_data.get("rendered_items", [])
    logger.info(f"PSD 导出：准备 {len(rendered_items)} 个文字层")
    for i, item in enumerate(rendered_items):
        layer_jsx = _generate_text_layer_jsx(i, item)
        if layer_jsx:
            text_layers_code += layer_jsx

    if not text_layers_code:
        logger.warning("没有可导出的文字层")
        return None

    # 生成完整 JSX
    jsx_script = _JSX_TEMPLATE.format(
        input_file=_escape_jsx_path(clean_image_path),
        output_file=_escape_jsx_path(output_psd_path),
        error_file=_escape_jsx_path(error_file),
        text_layers_code=text_layers_code,
    )

    # 确保输出目录存在
    output_dir = os.path.dirname(output_psd_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    # 保存 JSX（UTF-8 BOM，确保 Photoshop 正确读取中文）
    with open(jsx_file, "w", encoding="utf-8-sig") as f:
        f.write(jsx_script)
    logger.info(f"JSX 脚本已生成: {jsx_file}")

    # verbose / script_only 模式：复制 JSX 到输出目录旁
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
        logger.error(
            "未找到 Photoshop，无法生成 PSD。"
            "可使用 script_only=True 只生成 JSX 脚本后手动在 Photoshop 中运行。"
        )
        return None

    logger.info(f"使用 Photoshop: {ps_exe}")

    # 记录旧文件时间
    old_mtime = os.path.getmtime(output_psd_path) if os.path.exists(output_psd_path) else 0

    # 启动 Photoshop 执行脚本（不等待进程退出，只轮询 PSD 文件生成）
    subprocess.Popen(
        [ps_exe, "-r", jsx_file],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 轮询等待 PSD 生成
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

    # 检查脚本错误
    if os.path.exists(error_file):
        try:
            with open(error_file, "r", encoding="utf-8", errors="replace") as f:
                error_msg = f.read()
            logger.error(f"Photoshop 脚本错误: {error_msg}")
        except OSError:
            pass
        return None

    # 检查结果
    if os.path.exists(output_psd_path) and os.path.getsize(output_psd_path) > 0:
        file_size = os.path.getsize(output_psd_path) / 1024 / 1024
        logger.info(f"PSD 已生成: {output_psd_path} ({file_size:.1f} MB)")
        # 清理临时 JSX（非 verbose 模式）
        if not verbose and os.path.exists(jsx_file):
            try:
                os.unlink(jsx_file)
            except OSError:
                pass
        return output_psd_path

    if elapsed >= timeout:
        logger.error(f"Photoshop 执行超时（{timeout}秒），PSD 文件未生成")
    else:
        logger.error("PSD 文件生成失败")
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
