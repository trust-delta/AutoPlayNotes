"""AutoPlayNotes 起動エントリポイント。

    python main.py

Windows 専用（SendInput / RegisterHotKey を使用）。
"""

from __future__ import annotations

import sys


def main() -> int:
    if sys.platform != "win32":
        print("このアプリは Windows 専用です。", file=sys.stderr)
        return 1
    from autoplaynotes.gui import run

    run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
