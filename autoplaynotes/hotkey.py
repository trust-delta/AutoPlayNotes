"""グローバルホットキー（ゲームにフォーカスがあっても効く）。

RegisterHotKey は登録スレッドのメッセージキューに WM_HOTKEY を送るため、
専用スレッドで登録とメッセージループを回し、コールバックを呼ぶ。
"""

from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012

# よく使うキー名 -> 仮想キーコード
VK: dict[str, int] = {
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73,
    "F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77,
    "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
    "ESC": 0x1B, "SPACE": 0x20, "HOME": 0x24, "END": 0x23,
    "INSERT": 0x2D, "DELETE": 0x2E, "PAUSE": 0x13,
}

_user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
_user32.RegisterHotKey.restype = wintypes.BOOL
_user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
_user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
_user32.GetMessageW.restype = ctypes.c_int
_user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p)
_user32.PostThreadMessageW.restype = wintypes.BOOL
_kernel32.GetCurrentThreadId.restype = wintypes.DWORD


class HotkeyManager:
    """グローバルホットキーを管理する。"""

    def __init__(self) -> None:
        self._bindings: list[tuple[int, int, Callable[[], None]]] = []
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._ready = threading.Event()
        self._failed: list[str] = []

    def register(self, key: str, callback: Callable[[], None], mods: int = MOD_NOREPEAT) -> None:
        """キー名（例: 'F9'）にコールバックを割り当てる。start() 前に呼ぶこと。"""
        vk = VK.get(key.upper())
        if vk is None:
            raise ValueError(f"ホットキーに未対応のキーです: {key}")
        self._bindings.append((vk, mods, callback))

    @property
    def failed(self) -> list[str]:
        """登録に失敗したホットキー（他アプリと競合など）。"""
        return list(self._failed)

    def start(self) -> None:
        if not self._bindings:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._ready.wait(2.0)

    def _run(self) -> None:
        self._thread_id = _kernel32.GetCurrentThreadId()
        callbacks: dict[int, Callable[[], None]] = {}
        for i, (vk, mods, callback) in enumerate(self._bindings, start=1):
            if _user32.RegisterHotKey(None, i, mods, vk):
                callbacks[i] = callback
            else:
                self._failed.append(f"vk=0x{vk:02X}")
        self._ready.set()

        msg = wintypes.MSG()
        while True:
            result = _user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result in (0, -1):
                break
            if msg.message == WM_HOTKEY:
                callback = callbacks.get(int(msg.wParam))
                if callback is not None:
                    try:
                        callback()
                    except Exception:
                        pass

        for hotkey_id in callbacks:
            _user32.UnregisterHotKey(None, hotkey_id)

    def stop(self) -> None:
        if self._thread_id is not None:
            _user32.PostThreadMessageW(self._thread_id, WM_QUIT, None, None)
            self._thread_id = None
