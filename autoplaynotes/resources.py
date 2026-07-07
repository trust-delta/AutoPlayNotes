"""同梱リソース（assets/）のパス解決。

開発時はリポジトリ直下の assets/、PyInstaller onefile 実行時は
展開先（sys._MEIPASS）の assets/ を参照する。
"""

from __future__ import annotations

import os
import sys


def asset_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "assets", name)


def icon_path() -> str | None:
    path = asset_path("icon.ico")
    return path if os.path.exists(path) else None
