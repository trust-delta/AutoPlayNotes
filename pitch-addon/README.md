# AutoPlayNotes 採譜アドオン（音源 → MIDI）ソース

AutoPlayNotes 本体（単一 exe）とは別に、**音声ファイルから MIDI を自動採譜**する
機能を「自前ランタイムごと」同梱した配布フォルダを組み立てるためのソース一式。
認識エンジンにはオープンソースの [basic-pitch](https://github.com/spotify/basic-pitch)
（Spotify・Apache-2.0）を利用する。

買った人は生成物の `pitch` フォルダを `AutoPlayNotes.exe` と同じ場所に解凍するだけで、
本体の「📥 取り込み → 音源（音声ファイル）から」が使えるようになる（隣接 dir
ドロップイン検出）。

## 構成
- `requirements.lock.txt` … 実機 E2E 成功時の完全ピン（`build_pitch_addon.py` が
  再配置可能 Python へ `--no-deps` でそのまま入れる）。
- `run_pitch.py` … 起動ラッパ。`predict_and_save` を直接呼び、stdout を UTF-8 固定。
- 生成物の `manifest.json` … 本体が読む起動契約
  （`["python/python.exe", "{addon}/run_pitch.py", "{out}", "{audio}"]`）。

## ビルド
```
python tools/build_pitch_addon.py --out <ビルド先> --zip
```
- 土台は python-build-standalone（再配置可能 CPython 3.12・Windows amd64）。
- basic-pitch の onnx モデル（`nmp.onnx`, 約 0.2MB）は wheel 同梱なので種付け不要。
- tensorflow / coreml / tflite バックエンドは入れない（onnxruntime のみ）。

## 動作メモ
- 認識は CPU。ドライなソロピアノ音源が最も精度が出る（recall 高・precision は素材依存）。
- 結果は**下書き品質**。取り込み後に本体の五線譜エディタ／トレースで修正する前提。
- basic-pitch は素の pip では依存解決が難しい（tensorflow 系）。本ロックは
  `basic-pitch` を `--no-deps` で入れ、onnxruntime と手動依存で固めた実績構成。
