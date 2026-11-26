"""Clipboard for the web UI (pywebview runs without the browser clipboard permission).

Tk is already a pywebview dependency on Windows, so it is the first choice; the Win32 API and
the macOS `pbcopy` are fallbacks. Every path fails soft: the UI only ever uses this for the
"Copy the command" buttons."""
from __future__ import annotations

import os
import subprocess


def copy(text: str) -> bool:
    """Put `text` on the clipboard. True when one of the methods worked."""
    text = str(text or "")
    if not text:
        return False
    if os.name == "nt":
        if _win32(text):
            return True
    else:
        for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "-ib"]):
            try:
                p = subprocess.run(cmd, input=text.encode("utf-8"), timeout=5,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if p.returncode == 0:
                    return True
            except (OSError, subprocess.SubprocessError):
                continue
    return _tk(text)


def _win32(text: str) -> bool:
    try:
        import ctypes
        from ctypes import wintypes
        CF_UNICODETEXT, GMEM_MOVEABLE = 13, 0x0002
        u32, k32 = ctypes.windll.user32, ctypes.windll.kernel32
        k32.GlobalAlloc.restype = wintypes.HGLOBAL
        k32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        k32.GlobalLock.restype = wintypes.LPVOID
        if not u32.OpenClipboard(None):
            return False
        try:
            u32.EmptyClipboard()
            data = text.encode("utf-16-le") + b"\x00\x00"
            handle = k32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not handle:
                return False
            ptr = k32.GlobalLock(handle)
            ctypes.memmove(ptr, data, len(data))
            k32.GlobalUnlock(handle)
            return bool(u32.SetClipboardData(CF_UNICODETEXT, handle))
        finally:
            u32.CloseClipboard()
    except Exception:
        return False


def _tk(text: str) -> bool:
    try:
        import tkinter
        root = tkinter.Tk()
        root.withdraw()
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()
        root.destroy()
        return True
    except Exception:
        return False
