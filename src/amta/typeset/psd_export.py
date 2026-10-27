"""Photoshop 进程管理 — 查找可执行文件、调 JSX、轮询完成。

从 psd_jsx_export.py 拆出。本模块不生成 JSX（那是 psd_jsx.py 的事），
只负责：找 Photoshop → 写临时 JSX → subprocess 调起 → 轮询完成/错误 → 原子发布。
"""
from __future__ import annotations

import logging
import json
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from collections.abc import Callable
from typing import Any, Optional

from amta.typeset.psd_jsx import build_script
from amta.typeset.psd_windows import privilege_problem

logger = logging.getLogger(__name__)
_PHOTOSHOP_LOCK = threading.Lock()


def _monitor_quarantine(runtime: Path, lock: Any) -> None:
    """Retain isolation until JSX reports completion after restoring Photoshop state.

    Never publish late output. With no terminal marker the directory and lock stay
    quarantined for the lifetime of this process; guessing that PS stopped is unsafe.
    """
    while not ((runtime / "complete.txt").exists() or (runtime / "error.txt").exists()):
        time.sleep(0.5)
    shutil.rmtree(runtime, ignore_errors=True)
    lock.release()


def _start_quarantine_monitor(runtime: Path, lock: Any) -> None:
    threading.Thread(target=_monitor_quarantine, args=(runtime, lock),
                     name="psd-quarantine", daemon=True).start()


def _read_progress(path: Path, offset: int, emit: Callable[[dict[str, Any]], None]) -> int:
    """Only consume complete JSONL records; a writer may be halfway through a line."""
    try:
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read()
    except OSError:
        return offset
    end = data.rfind(b"\n") + 1
    for line in data[:end].splitlines():
        try:
            event = json.loads(line.decode("utf-8-sig"))
            if isinstance(event, dict):
                emit(event)
        except (ValueError, UnicodeError):
            logger.debug("Ignoring malformed PSD progress record")
    return offset + end


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
    *,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> Optional[str]:
    """生成 JSX 脚本并调用 Photoshop 创建分层 PSD。

    Returns: 成功返回 PSD 路径；script_only 时返回 JSX 路径；失败返回 None。
    """
    def emit(event: dict[str, Any]) -> None:
        if progress_callback:
            try:
                progress_callback(event)
            except Exception:  # noqa: BLE001
                logger.exception("PSD progress observer failed")

    if not os.path.isfile(clean_image_path):
        logger.error("Clean image does not exist: %s", clean_image_path)
        emit({"stage": "error"})
        return None

    output = Path(output_psd_path).resolve()

    def make_script(target: Path, error: Path, completion: Path,
                    progress: Path | None = None, cancel: Path | None = None,
                    clean_copy: Path | None = None) -> str:
        return build_script(str(clean_copy) if clean_copy else clean_image_path,
                            str(target), str(error), str(completion), typeset_data,
                            progress_path=str(progress) if progress else "",
                            cancel_path=str(cancel) if cancel else "",
                            legacy=os.getenv("AMTA_PSD_LEGACY", "") == "1")

    runtime = None
    lock = _PHOTOSHOP_LOCK
    acquired = launched = terminal = False
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
            emit({"stage": "error"})
            return None
        ps_exe = find_photoshop_executable()
        if not ps_exe:
            logger.error("Photoshop not found; use script_only=True for manual export")
            emit({"stage": "error"})
            return None

        problem = privilege_problem()
        if problem:
            logger.error(problem)
            emit({"stage": "error", "error": problem})
            return None

        emit({"stage": "queued"})
        acquired = lock.acquire(timeout=timeout)
        if not acquired:
            logger.error("Photoshop export queue timed out (%s seconds)", timeout)
            emit({"stage": "error"})
            return None
        runtime = Path(tempfile.mkdtemp(prefix=".amta-psd-", dir=output.parent))
        jsx_file = runtime / "export.jsx"
        error_file = runtime / "error.txt"
        completion_file = runtime / "complete.txt"
        progress_file = runtime / "progress.jsonl"
        staged_output = runtime / "output.psd"
        # app.open can return an already-open document for the same path. A unique
        # copy ensures the exporter never modifies/closes the user's clean image.
        clean_copy = runtime / ("input" + Path(clean_image_path).suffix)
        shutil.copyfile(clean_image_path, clean_copy)
        jsx_file.write_text(make_script(staged_output, error_file, completion_file,
                                       progress_file, runtime / "cancel", clean_copy), encoding="utf-8-sig")
        emit({"stage": "waiting_photoshop"})
        subprocess.Popen([ps_exe, "-r", str(jsx_file)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
        launched = True
        deadline = time.monotonic() + timeout
        offset = 0
        while time.monotonic() < deadline:
            offset = _read_progress(progress_file, offset, emit)
            if error_file.exists():
                terminal = True
                logger.error("Photoshop script error: %s", error_file.read_text(
                    encoding="utf-8", errors="replace"))
                emit({"stage": "error"})
                return None
            if completion_file.exists():
                terminal = True
                if (completion_file.read_text(encoding="utf-8") != "complete"
                        or not staged_output.is_file() or staged_output.stat().st_size == 0):
                    logger.error("Photoshop completed without a valid staged PSD")
                    emit({"stage": "error"})
                    return None
                os.replace(staged_output, output)
                logger.info("PSD generated: %s", output_psd_path)
                emit({"stage": "done"})
                return output_psd_path
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        logger.error("Photoshop execution timed out (%s seconds)", timeout)
        emit({"stage": "error"})
        return None
    except OSError:
        logger.exception("PSD export failed: %s", output_psd_path)
        emit({"stage": "error"})
        return None
    finally:
        if acquired:
            if runtime is not None and launched and not terminal:
                try:
                    (runtime / "cancel").touch()
                except OSError:
                    logger.exception("Unable to signal PSD cancellation; retaining isolation")
                _start_quarantine_monitor(runtime, lock)
            else:
                if runtime is not None:
                    shutil.rmtree(runtime, ignore_errors=True)
                lock.release()
