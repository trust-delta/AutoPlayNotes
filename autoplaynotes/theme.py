"""アプリの外観テーマ（customtkinter ブリッジ + ライト/ダークパレット）。

- setup() を最初の CTk ウィンドウ生成前に一度呼ぶ
  （customtkinter の既定テーマを本アプリのパレットで上書きし、外観モードを設定する）
- set_appearance() でライト/ダークを実行時に切り替える（CTk ウィジェットは自動追従）
- tk.Canvas / tk.Listbox / tk.Menu は customtkinter の対象外なので、
  palette() の色と style_listbox() / apply_menu_defaults() で個別に追従させる
- ウィンドウのタイトルバー色は apply_titlebar() で Windows の DWM に反映する
"""

from __future__ import annotations

import ctypes
import sys
import tkinter as tk

import customtkinter as ctk

# 日本語 UI 向けフォント（customtkinter 既定の Roboto は和文を持たない）
FONT_FAMILY = "Yu Gothic UI"
FONT_MONO = "Consolas"

_PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#eef0f4", "surface": "#ffffff", "surface_alt": "#e3e7ee",
        "text": "#1f2530", "subtle": "#667085", "border": "#cfd5df",
        "accent": "#2f6fed", "accent_active": "#2257c8", "accent_fg": "#ffffff",
        "danger": "#d9433f", "danger_active": "#b8332f",
        "text_bg": "#ffffff", "log_bg": "#f6f7f9",
        # タブ / セグメントの選択色（文字色 text のまま読めるソフトな強調）
        "seg_sel": "#cddcfd", "seg_sel_hover": "#b9cdf7",
        # 五線譜キャンバス
        "staff_bg": "#ffffff", "staff_line": "#3c4352", "staff_grid": "#dcdfe5",
        "note": "#2e7d32", "note_out": "#c62828",
        "note_played": "#64b5f6", "note_active": "#fb8c00", "select": "#1565c0",
    },
    "dark": {
        "bg": "#1a1d26", "surface": "#242833", "surface_alt": "#2e3340",
        "text": "#e7eaf0", "subtle": "#9aa3b2", "border": "#3a4150",
        "accent": "#4f8bff", "accent_active": "#3f74e6", "accent_fg": "#0a0f1a",
        "danger": "#ff6b66", "danger_active": "#e0554f",
        "text_bg": "#1f232d", "log_bg": "#191c24",
        "seg_sel": "#33507e", "seg_sel_hover": "#3c5c91",
        "staff_bg": "#1f232d", "staff_line": "#8b93a5", "staff_grid": "#3a4150",
        "note": "#69c06d", "note_out": "#ff6b66",
        "note_played": "#4fc3f7", "note_active": "#ffb74d", "select": "#7aa8ff",
    },
}

_current = _PALETTES["light"]


def palette() -> dict[str, str]:
    return _current


def pair(name: str) -> tuple[str, str]:
    """customtkinter の (ライト, ダーク) 色ペアを返す。"""
    return (_PALETTES["light"][name], _PALETTES["dark"][name])


# 既定の CTkButton は控えめな色にし、主要操作だけ強調色にする
BTN_ACCENT = {
    "fg_color": pair("accent"), "hover_color": pair("accent_active"),
    "text_color": pair("accent_fg"),
}
BTN_DANGER = {
    "fg_color": pair("danger"), "hover_color": pair("danger_active"),
    "text_color": ("#ffffff", "#ffffff"),
}


def _patch_ctk_theme() -> None:
    """customtkinter の組込テーマを本アプリのパレットで上書きする。"""
    t = ctk.ThemeManager.theme
    t["CTk"]["fg_color"] = list(pair("bg"))
    t["CTkToplevel"]["fg_color"] = list(pair("bg"))
    t["CTkFrame"].update(
        fg_color=list(pair("surface")), top_fg_color=list(pair("surface_alt")),
        border_color=list(pair("border")),
    )
    t["CTkButton"].update(
        fg_color=list(pair("surface_alt")), hover_color=list(pair("border")),
        border_color=list(pair("border")), text_color=list(pair("text")),
        text_color_disabled=list(pair("subtle")),
    )
    t["CTkLabel"]["text_color"] = list(pair("text"))
    t["CTkEntry"].update(
        fg_color=list(pair("text_bg")), border_color=list(pair("border")),
        text_color=list(pair("text")), placeholder_text_color=list(pair("subtle")),
    )
    t["CTkCheckBox"].update(
        fg_color=list(pair("accent")), hover_color=list(pair("accent_active")),
        checkmark_color=list(pair("accent_fg")), border_color=list(pair("subtle")),
        text_color=list(pair("text")), text_color_disabled=list(pair("subtle")),
    )
    t["CTkRadioButton"].update(
        fg_color=list(pair("accent")), hover_color=list(pair("accent_active")),
        border_color=list(pair("subtle")), text_color=list(pair("text")),
        text_color_disabled=list(pair("subtle")),
    )
    t["CTkSwitch"].update(
        fg_color=list(pair("border")), progress_color=list(pair("accent")),
        text_color=list(pair("text")), text_color_disabled=list(pair("subtle")),
    )
    t["CTkOptionMenu"].update(
        fg_color=list(pair("surface_alt")), button_color=list(pair("border")),
        button_hover_color=list(pair("subtle")), text_color=list(pair("text")),
        text_color_disabled=list(pair("subtle")),
    )
    t["CTkComboBox"].update(
        fg_color=list(pair("text_bg")), border_color=list(pair("border")),
        button_color=list(pair("border")), button_hover_color=list(pair("subtle")),
        text_color=list(pair("text")), text_color_disabled=list(pair("subtle")),
    )
    t["CTkScrollbar"].update(
        button_color=list(pair("border")), button_hover_color=list(pair("subtle")),
    )
    t["CTkSegmentedButton"].update(
        fg_color=list(pair("surface_alt")),
        selected_color=list(pair("seg_sel")), selected_hover_color=list(pair("seg_sel_hover")),
        unselected_color=list(pair("surface_alt")), unselected_hover_color=list(pair("border")),
        text_color=list(pair("text")), text_color_disabled=list(pair("subtle")),
    )
    t["CTkTextbox"].update(
        fg_color=list(pair("text_bg")), border_color=list(pair("border")),
        text_color=list(pair("text")),
        scrollbar_button_color=list(pair("border")),
        scrollbar_button_hover_color=list(pair("subtle")),
    )
    t["CTkProgressBar"].update(
        fg_color=list(pair("surface_alt")), progress_color=list(pair("accent")),
        border_color=list(pair("border")),
    )
    t["CTkSlider"].update(
        fg_color=list(pair("surface_alt")), progress_color=list(pair("accent")),
        button_color=list(pair("accent")), button_hover_color=list(pair("accent_active")),
    )
    t["CTkScrollableFrame"]["label_fg_color"] = list(pair("surface_alt"))
    t["DropdownMenu"].update(
        fg_color=list(pair("surface")), hover_color=list(pair("surface_alt")),
        text_color=list(pair("text")),
    )
    t["CTkFont"].update(family=FONT_FAMILY, size=13)


def setup(dark: bool) -> None:
    """最初のウィンドウ生成前に一度呼ぶ。"""
    global _current
    ctk.set_default_color_theme("blue")
    _patch_ctk_theme()
    _current = _PALETTES["dark" if dark else "light"]
    ctk.set_appearance_mode("dark" if dark else "light")


def set_appearance(dark: bool) -> None:
    """ライト/ダークを切り替える（CTk ウィジェットは自動で追従）。"""
    global _current
    _current = _PALETTES["dark" if dark else "light"]
    ctk.set_appearance_mode("dark" if dark else "light")


def is_dark() -> bool:
    return _current is _PALETTES["dark"]


def apply_menu_defaults(root: tk.Misc) -> None:
    """tk.Menu（ドロップダウン等）の既定色をパレットに合わせる。"""
    p = _current
    root.option_add("*Menu.background", p["surface"])
    root.option_add("*Menu.foreground", p["text"])
    root.option_add("*Menu.activeBackground", p["accent"])
    root.option_add("*Menu.activeForeground", p["accent_fg"])
    root.option_add("*Menu.relief", "flat")


def style_listbox(widget: tk.Listbox) -> None:
    p = _current
    widget.configure(
        background=p["text_bg"], foreground=p["text"],
        selectbackground=p["accent"], selectforeground=p["accent_fg"],
        highlightthickness=0, relief="flat", borderwidth=0,
        font=(FONT_FAMILY, 12), activestyle="none",
    )


def apply_titlebar(window: tk.Misc) -> None:
    """Windows のタイトルバーを外観モードに合わせる（失敗しても無視）。

    ウィンドウがマップされる前は HWND が取れないため、少し間隔を空けて
    数回試行する（Toplevel は生成直後に呼ばれることが多い）。
    """
    if sys.platform != "win32":
        return

    def _apply() -> bool:
        try:
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            if not hwnd:
                return False
            value = ctypes.c_int(1 if is_dark() else 0)
            # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
            )
            return True
        except Exception:
            return True  # 失敗（未対応 OS 等）は再試行しない

    def _attempt(delays: tuple[int, ...]) -> None:
        if _apply() or not delays:
            return
        try:
            window.after(delays[0], lambda: _attempt(delays[1:]))
        except Exception:
            pass

    _attempt((100, 300, 800))
