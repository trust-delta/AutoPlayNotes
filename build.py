"""AutoPlayNotes を単一 exe にビルドする（PyInstaller）。

  python -m pip install -r requirements-dev.txt
  python build.py

生成物: dist/AutoPlayNotes.exe（Python のインストール不要で起動できる単一ファイル）
"""

from __future__ import annotations

import subprocess
import sys


def main() -> int:
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--onefile",          # 単一 exe
        "--windowed",         # コンソール無し（GUI アプリ）
        "--name", "AutoPlayNotes",
        "--hidden-import", "mido",  # MIDI は遅延 import のため明示
        "main.py",
    ]
    print("実行:", " ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
