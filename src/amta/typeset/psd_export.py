"""Photoshop 进程管理 — 查找可执行文件、调 JSX、轮询完成。

从 psd_jsx_export.py 拆出。本模块不生成 JSX（那是 psd_jsx.py 的事），
只负责：找 Photoshop → 写临时 JSX → subprocess 调起 → 轮询完成/错误 → 原子发布。
"""
from __future__ import annotations

import logging
import os
import platform
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Optional

from amta.typeset.psd_jsx import build_script

logger = logging.getLogger(__name__)
_PHOTOSHOP_LOCK = threading.Lock()


def find_photoshop_executable() -> Optional[str]:
    """查找 Photoshop 可执行文件路径。"""
    ps_path = os.getenv("PHOTOSHOP_PATH")
    if ps_path and os.path.exists(ps_path):
        return ps_path

    if platform.system() != "Windows":
        logger.warning("PSD 导出仅支持 Windows（需要 Photoshop）")
        return None

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

    possible_paths = [
        r"C:\Program Files\Adobe\Adobe Photoshop 2025\Photoshop.exe",
        r"C:\Program Files\Adobe\Adobe Photoshop 2024\Photoshop.exe",
        r"C:\Program Files\Adobe\Adobe Photoshop 2023\Photoshop.exe",
        r"C:\Program Files\Adobe\Adobe Photoshop 2022\Photoshop.exe",
        r"C:\Program Files\Adobe\Adobe Photoshop 2021\Photoshop.exe",
    ]
    pf_x86 = os.getenv("ProgramFiles(x86)")
    if pf_x86:
        possible_paths += [p.replace(r"C:\Program Files", pf_x86) for p in possible_paths]
    for path in possible_paths:
        if os.path.exists(path):
            return path

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


def export_psd_with_jsx(
    clean_image_path: str,
    typeset_data: dict[str, Any],
    output_psd_path: str,
    script_only: bool = False,
    verbose: bool = False,
    timeout: int = 300,
) -> Optional[str]:
    """生成 JSX 脚本并调用 Photoshop 创建分层 PSD。

    Returns: 成功返回 PSD 路径；script_only 时返回 JSX 路径；失败返回 None。
    """
    if not os.path.isfile(clean_image_path):
        logger.error("Clean image does not exist: %s", clean_image_path)
        return None

    output = Path(output_psd_path).resolve()

    def make_script(target: Path, error: Path, completion: Path) -> str:
        return build_script(clean_image_path, str(target), str(error), str(completion), typeset_data)

    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        if verbose or script_only:
            saved_script = Path(output_psd_path).with_suffix(".jsx")
            saved_script.write_text(make_script(
                output, output.with_suffix(".error.txt"), output.with_suffix(".complete")
            ), encoding="utf-8-sig")
            if script_only:
                return str(saved_script)

        if timeout <= 0:
            return None
        ps_exe = find_photoshop_executable()
        if not ps_exe:
            logger.error("Photoshop not found; use script_only=True for manual export")
            return None

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
                    os.replace(staged_output, output)
                    logger.info("PSD generated: %s", output_psd_path)
                    return output_psd_path
                time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
            logger.error("Photoshop execution timed out (%s seconds)", timeout)
            return None
    except OSError:
        logger.exception("PSD export failed: %s", output_psd_path)
        return None
