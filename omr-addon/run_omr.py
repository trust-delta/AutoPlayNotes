"""AutoPlayNotes OMR アドオンの起動ラッパ。

本体は manifest.json の command に従い
`python/python.exe run_omr.py -o <出力先> <画像>` の形でこのスクリプトを起動する。
oemer のコンソールスクリプト（oemer.exe）は pip がインストール時の絶対パスを
埋め込むため再配置に弱い。そこでモジュール関数 `oemer.ete.main` を直接呼び、
フォルダごと別マシンへ移しても動くようにする。

oemer のログには非 ASCII が混ざり、Windows 既定の cp932 では書き出しに失敗して
クラッシュすることがあるため、標準出力を UTF-8 に固定する。
"""

from __future__ import annotations

import sys


def _force_utf8() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


def main() -> int:
    _force_utf8()
    # 引数（-o <out> <image>）は oemer 側の argparse がそのまま解釈する
    from oemer.ete import main as oemer_main

    oemer_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
