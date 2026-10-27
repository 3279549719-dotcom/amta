"""Read-only Windows privilege preflight; never elevates or closes Photoshop."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


def photoshop_pid() -> int | None:
    if os.name != "nt":
        return None
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user.FindWindowW.restype = wintypes.HWND
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    window = user.FindWindowW("Photoshop", None)
    if not window:
        return None
    pid = wintypes.DWORD()
    user.GetWindowThreadProcessId(window, ctypes.byref(pid))
    return pid.value or None


def is_elevated(pid: int) -> bool | None:
    if os.name != "nt":
        return None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    security = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    security.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID,
                                            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    process = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        return None
    token = wintypes.HANDLE()
    try:
        if not security.OpenProcessToken(process, 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
            return None
        elevated, size = wintypes.DWORD(), wintypes.DWORD()
        if not security.GetTokenInformation(token, 20, ctypes.byref(elevated),
                                            ctypes.sizeof(elevated), ctypes.byref(size)):  # TokenElevation
            return None
        return bool(elevated.value)
    finally:
        if token:
            kernel.CloseHandle(token)
        kernel.CloseHandle(process)


def privilege_problem() -> str | None:
    pid = photoshop_pid()
    if pid and is_elevated(os.getpid()) is False and is_elevated(pid) is True:
        return "Photoshop 正以管理员权限运行，而工作台不是。请保存并关闭 Photoshop，再以普通权限打开后重试。"
    return None
