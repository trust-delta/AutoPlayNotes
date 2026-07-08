"""複数の採譜エンジン（omr/ 五線譜画像・pitch/ 音源・将来 video/ 動画）を
1 つの配布 zip「採譜アドオン」にまとめる。

本体は exe 隣接の omr/ pitch/ 等を各々独立に検出するため、各エンジンフォルダを
アーカイブ直下に入れた 1 つの zip を作れば「採譜アドオン（画像＋音源＋…）」として
1 商品で配布できる。買った人は解凍して出てくる各フォルダを AutoPlayNotes.exe と
同じ場所に置くだけ。将来 3b（動画）アドオンも `--engine` を足すだけで同梱できる。

使い方:
  python tools/bundle_transcribe_addon.py \
      --engine D:/omr_build/omr --engine D:/pitch_build/pitch \
      --out D:/transcribe_addon.zip
"""

from __future__ import annotations

import argparse
import os
import zipfile


def log(msg: str) -> None:
    print(f"[bundle-transcribe] {msg}", flush=True)


def _dir_size_mb(path: str) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total / (1024 * 1024)


def build(args: argparse.Namespace) -> int:
    engines = [os.path.abspath(e) for e in args.engine]
    for engine in engines:
        if not os.path.isdir(engine):
            raise SystemExit(f"フォルダがありません: {engine}")
        if not os.path.isfile(os.path.join(engine, "manifest.json")):
            raise SystemExit(f"manifest.json が無い（アドオンではない?）: {engine}")

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    names = [os.path.basename(e.rstrip("/\\")) for e in engines]
    total_src = sum(_dir_size_mb(e) for e in engines)
    log(f"まとめる: {names}  (展開後 約 {total_src:.0f} MB)")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for engine, top in zip(engines, names):
            for root, _dirs, files in os.walk(engine):
                for name in files:
                    full = os.path.join(root, name)
                    # アーカイブ直下に <top>/... で入れる（exe 隣接に解凍される想定）
                    arc = os.path.join(top, os.path.relpath(full, engine))
                    zf.write(full, arc)
            log(f"  追加: {top}/ ({_dir_size_mb(engine):.0f} MB)")

    log(f"完成: {out}  ({os.path.getsize(out) / (1024 * 1024):.0f} MB)")
    log("買った人は zip 内の各フォルダを AutoPlayNotes.exe と同じ場所に置けば動作します。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="採譜アドオンを 1 つの zip にまとめる")
    parser.add_argument("--engine", action="append", required=True,
                        help="同梱するアドオンフォルダ（omr/ pitch/ 等）。複数指定可")
    parser.add_argument("--out", required=True, help="出力 zip パス")
    return build(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
