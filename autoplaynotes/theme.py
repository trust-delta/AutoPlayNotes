"""アプリの配色テーマ（ライト/ダーク）。追加依存なし（ttk.Style + clam）。

apply_theme() で ttk ウィジェットのスタイルとパレットを設定する。
tk.Text / tk.Listbox / tk.Canvas は ttk 対象外なので、style_text()/style_listbox()
で個別に色付けする。現在のパレットは palette() で取得できる。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

_PALETTES: dict[str, dict[str, str]] = {
    "light": {
        "bg": "#eef0f4", "surface": "#ffffff", "surface_alt": "#e3e7ee",
        "text": "#1f2530", "subtle": "#667085", "border": "#cfd5df",
        "accent": "#2f6fed", "accent_active": "#2257c8", "accent_fg": "#ffffff",
        "danger": "#d9433f", "danger_active": "#b8332f",
        "text_bg": "#ffffff", "log_bg": "#f6f7f9",
    },
    "dark": {
        "bg": "#1a1d26", "surface": "#242833", "surface_alt": "#2e3340",
        "text": "#e7eaf0", "subtle": "#9aa3b2", "border": "#3a4150",
        "accent": "#4f8bff", "accent_active": "#3f74e6", "accent_fg": "#0a0f1a",
        "danger": "#ff6b66", "danger_active": "#e0554f",
        "text_bg": "#1f232d", "log_bg": "#191c24",
    },
}

_current = _PALETTES["light"]


def palette() -> dict[str, str]:
    return _current


def apply_theme(root: tk.Misc, dark: bool) -> dict[str, str]:
    global _current
    p = _PALETTES["dark" if dark else "light"]
    _current = p

    base_font = ("Segoe UI", 10)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    style.configure(".", background=p["bg"], foreground=p["text"], font=base_font,
                    bordercolor=p["border"], focuscolor=p["bg"])
    style.configure("TFrame", background=p["bg"])
    style.configure("TLabel", background=p["bg"], foreground=p["text"])
    style.configure("Sub.TLabel", background=p["bg"], foreground=p["subtle"])
    style.configure("Header.TLabel", background=p["bg"], foreground=p["text"],
                    font=("Segoe UI", 16, "bold"))
    style.configure("Status.TLabel", background=p["surface_alt"], foreground=p["subtle"],
                    padding=(8, 4))
    style.configure("TLabelframe", background=p["bg"], bordercolor=p["border"])
    style.configure("TLabelframe.Label", background=p["bg"], foreground=p["subtle"])

    style.configure("TButton", background=p["surface_alt"], foreground=p["text"],
                    bordercolor=p["border"], relief="flat", padding=(10, 5))
    style.map("TButton",
              background=[("pressed", p["border"]), ("active", p["border"])],
              foreground=[("disabled", p["subtle"])])
    style.configure("Accent.TButton", background=p["accent"], foreground=p["accent_fg"])
    style.map("Accent.TButton", background=[("pressed", p["accent_active"]), ("active", p["accent_active"])])
    style.configure("Danger.TButton", background=p["danger"], foreground="#ffffff")
    style.map("Danger.TButton", background=[("pressed", p["danger_active"]), ("active", p["danger_active"])])

    style.configure("TMenubutton", background=p["surface_alt"], foreground=p["text"],
                    bordercolor=p["border"], relief="flat", padding=(8, 4), arrowcolor=p["text"])
    style.map("TMenubutton", background=[("active", p["border"])])

    style.configure("TEntry", fieldbackground=p["text_bg"], foreground=p["text"],
                    bordercolor=p["border"], insertcolor=p["text"])
    style.configure("TSpinbox", fieldbackground=p["text_bg"], foreground=p["text"],
                    bordercolor=p["border"], arrowcolor=p["text"], insertcolor=p["text"])
    style.map("TEntry", fieldbackground=[("readonly", p["surface_alt"])])

    style.configure("TCheckbutton", background=p["bg"], foreground=p["text"])
    style.map("TCheckbutton", background=[("active", p["bg"])])
    style.configure("TRadiobutton", background=p["bg"], foreground=p["text"])
    style.map("TRadiobutton", background=[("active", p["bg"])])

    for orient in ("Horizontal", "Vertical"):
        style.configure(f"{orient}.TScrollbar", background=p["surface_alt"],
                        troughcolor=p["bg"], bordercolor=p["bg"], arrowcolor=p["text"])
        style.map(f"{orient}.TScrollbar", background=[("active", p["border"])])

    style.configure("TSeparator", background=p["border"])

    style.configure("TNotebook", background=p["bg"], bordercolor=p["border"], tabmargins=(4, 4, 4, 0))
    style.configure("TNotebook.Tab", background=p["surface_alt"], foreground=p["subtle"],
                    padding=(16, 7), bordercolor=p["border"])
    style.map("TNotebook.Tab",
              background=[("selected", p["surface"]), ("active", p["border"])],
              foreground=[("selected", p["text"])])

    # tk.Menu（OptionMenu のドロップダウン等）の既定色
    root.option_add("*Menu.background", p["surface"])
    root.option_add("*Menu.foreground", p["text"])
    root.option_add("*Menu.activeBackground", p["accent"])
    root.option_add("*Menu.activeForeground", p["accent_fg"])
    root.option_add("*Menu.relief", "flat")

    try:
        root.configure(bg=p["bg"])
    except tk.TclError:
        pass
    return p


def style_text(widget: tk.Text, log: bool = False) -> None:
    p = _current
    widget.configure(
        background=p["log_bg"] if log else p["text_bg"], foreground=p["text"],
        insertbackground=p["text"], selectbackground=p["accent"], selectforeground=p["accent_fg"],
        highlightthickness=0, relief="flat", borderwidth=8,
    )


def style_listbox(widget: tk.Listbox) -> None:
    p = _current
    widget.configure(
        background=p["text_bg"], foreground=p["text"],
        selectbackground=p["accent"], selectforeground=p["accent_fg"],
        highlightthickness=0, relief="flat", borderwidth=0,
    )
