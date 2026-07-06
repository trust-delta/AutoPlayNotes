"""Windows SendInput によるスキャンコード方式のキー送出。

多くのゲームは DirectInput / Raw Input で物理スキャンコードを読むため、
仮想キーコードではなく KEYEVENTF_SCANCODE を使って送出する。
これによりゲーム内楽器にもキー入力が届きやすくなる。
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Iterable

# --- Win32 定数 ---------------------------------------------------------------
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
INPUT_KEYBOARD = 1
MAPVK_VK_TO_VSC = 0

# ULONG_PTR はポインタ幅（64bit 環境では 8 バイト）
if ctypes.sizeof(ctypes.c_void_p) == 8:
    ULONG_PTR = ctypes.c_ulonglong
else:
    ULONG_PTR = ctypes.c_ulong

_user32 = ctypes.WinDLL("user32", use_last_error=True)


# --- INPUT 構造体定義 ---------------------------------------------------------
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


_user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
_user32.SendInput.restype = wintypes.UINT
_user32.VkKeyScanW.argtypes = (wintypes.WCHAR,)
_user32.VkKeyScanW.restype = wintypes.SHORT
_user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
_user32.MapVirtualKeyW.restype = wintypes.UINT


# 拡張キー（矢印・Ins/Del など）用の仮想キーコード表。
# ゲーム内楽器は英数字キーが大半だが、特殊キーも割り当てられるようにする。
_NAMED_VK: dict[str, tuple[int, bool]] = {
    "SPACE": (0x20, False),
    "ENTER": (0x0D, False),
    "TAB": (0x09, False),
    "UP": (0x26, True),
    "DOWN": (0x28, True),
    "LEFT": (0x25, True),
    "RIGHT": (0x27, True),
    "F1": (0x70, False),
    "F2": (0x71, False),
    "F3": (0x72, False),
    "F4": (0x73, False),
    "F5": (0x74, False),
    "F6": (0x75, False),
    "F7": (0x76, False),
    "F8": (0x77, False),
}


class UnknownKeyError(ValueError):
    """キー名からスキャンコードを解決できない場合。"""


def _resolve_scancode(key: str) -> tuple[int, bool]:
    """キー名を (スキャンコード, 拡張キーか) に解決する。"""
    name = key.strip()
    if not name:
        raise UnknownKeyError("空のキーは指定できません")

    upper = name.upper()
    if upper in _NAMED_VK:
        vk, extended = _NAMED_VK[upper]
        scan = _user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
        if scan == 0:
            raise UnknownKeyError(f"キー '{key}' のスキャンコードを取得できません")
        return scan, extended

    if len(name) != 1:
        raise UnknownKeyError(f"未対応のキー名です: '{key}'")

    res = _user32.VkKeyScanW(name)
    if res == -1:
        raise UnknownKeyError(f"現在のキーボード配列で '{key}' を入力できません")
    vk = res & 0xFF
    scan = _user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)
    if scan == 0:
        raise UnknownKeyError(f"キー '{key}' のスキャンコードを取得できません")
    return scan, False


def _make_input(scan: int, extended: bool, key_up: bool) -> INPUT:
    flags = KEYEVENTF_SCANCODE
    if extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    if key_up:
        flags |= KEYEVENTF_KEYUP
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return inp


def _send(inputs: list[INPUT]) -> None:
    if not inputs:
        return
    count = len(inputs)
    array = (INPUT * count)(*inputs)
    sent = _user32.SendInput(count, array, ctypes.sizeof(INPUT))
    if sent != count:
        raise ctypes.WinError(ctypes.get_last_error())


class KeySender:
    """キー押下 / 解放を送出し、押しっぱなしのキーを追跡する。"""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[int, bool]] = {}
        self._down: set[str] = set()

    def _scan(self, key: str) -> tuple[int, bool]:
        cached = self._cache.get(key)
        if cached is None:
            cached = _resolve_scancode(key)
            self._cache[key] = cached
        return cached

    def validate(self, keys: Iterable[str]) -> None:
        """割り当て前の検証用。解決できないキーがあれば例外を送出する。"""
        for k in keys:
            self._scan(k)

    def down(self, keys: Iterable[str]) -> None:
        inputs: list[INPUT] = []
        for k in keys:
            scan, extended = self._scan(k)
            inputs.append(_make_input(scan, extended, key_up=False))
            self._down.add(k)
        _send(inputs)

    def up(self, keys: Iterable[str]) -> None:
        inputs: list[INPUT] = []
        for k in keys:
            scan, extended = self._scan(k)
            inputs.append(_make_input(scan, extended, key_up=True))
            self._down.discard(k)
        _send(inputs)

    def tap(self, keys: Iterable[str], hold_seconds: float = 0.03) -> None:
        keys = list(keys)
        self.down(keys)
        time.sleep(hold_seconds)
        self.up(keys)

    def release_all(self) -> None:
        if self._down:
            self.up(list(self._down))
