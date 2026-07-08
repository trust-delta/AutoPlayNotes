"""AutoPlayNotes 採譜アドオン（音源 → MIDI）の起動ラッパ。

本体は manifest.json の command に従い
`python/python.exe run_pitch.py <出力先> <音声ファイル>` の形でこのスクリプトを起動する。
basic-pitch のコンソールスクリプト（basic-pitch.exe）は pip がインストール時の
絶対パスを埋め込むため再配置に弱い。そこで Python API `predict_and_save` を直接呼び、
フォルダごと別マシンへ移しても動くようにする。バックエンドは onnxruntime（同梱 nmp.onnx）。

basic-pitch のログには絵文字・非 ASCII が混ざり、Windows 既定の cp932 では書き出しに
失敗してクラッシュすることがあるため、標準出力を UTF-8 に固定する。
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
    if len(sys.argv) < 3:
        print("usage: run_pitch.py <output_dir> <audio>", flush=True)
        return 2
    out_dir, audio = sys.argv[1], sys.argv[2]

    # basic-pitch の onnx モデルを明示。predict_and_save は
    # <out_dir>/<stem>_basic_pitch.mid を書き出す。
    from basic_pitch.inference import predict_and_save
    from basic_pitch import ICASSP_2022_MODEL_PATH

    print(f"predicting: {audio}", flush=True)
    predict_and_save(
        [audio],            # audio_path_list
        out_dir,            # output_directory
        True,               # save_midi
        False,              # sonify_midi
        False,              # save_model_outputs
        False,              # save_notes
        ICASSP_2022_MODEL_PATH,  # model_or_model_path（onnx）
    )
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
