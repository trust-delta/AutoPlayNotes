# OMR アドオン（自動採譜・別売）

五線譜の画像や PDF を **自動で譜面に起こす**（OMR＝光学楽譜認識）機能を、
本体（単一 exe）とは別の「自己完結フォルダ」として配布するためのソースです。

本体は軽量な依存だけで動かし、深層学習モデルを要する自動採譜だけを
アドオンに切り出しています。買った人は生成された `omr` フォルダを
**`AutoPlayNotes.exe` と同じ場所に解凍するだけ**で OMR が使えるようになります
（本体が隣接する `omr/` フォルダを自動検出します）。

## 仕組み（本体との接続）

本体は `omr/manifest.json` の `command` に従ってアドオンを別プロセスで起動します。

```json
{
  "command": ["python/python.exe", "{addon}/run_omr.py", "-o", "{out}", "{image}"]
}
```

- `{addon}` … アドオンフォルダの絶対パス
- `{image}` … 入力画像 / PDF から起こした一時 PNG
- `{out}` … MusicXML の出力先

`run_omr.py` は同梱の再配置可能 Python で `oemer` を呼び、MusicXML を書き出します。
本体はそれを取り込んで五線譜エディタで編集できます。エンジンを差し替えても
本体側は無変更（manifest の契約だけで疎結合）。

開発時は本体リポジトリ直下に `omr/` を置くか、環境変数
`AUTOPLAYNOTES_OMR_ADDON` でアドオンフォルダを直接指定できます。
アドオンが無い場合、本体は `pip install oemer` した開発環境の `oemer` に
フォールバックします。

## 中身

| ファイル | 役割 |
| --- | --- |
| `run_omr.py` | 起動ラッパ（`oemer.ete.main` を呼ぶ。コンソールスクリプトは絶対パス埋め込みで再配置に弱いため使わない） |
| `requirements.lock.txt` | 実機で E2E 成功した依存の正確なピン |
| `manifest.json` | ビルド時に生成（配布物にのみ含まれる） |
| `python/` | ビルド時に用意する再配置可能 CPython + 依存 + モデル |

## ビルド方法

`tools/build_omr_addon.py` が組み立てます。土台は
[python-build-standalone](https://github.com/astral-sh/python-build-standalone)
（再配置可能 CPython）。venv は絶対パスを埋め込み別マシンで壊れるため使いません。

```bash
# 既に oemer を入れた環境の checkpoints を種にする（速い）
python tools/build_omr_addon.py --out build/omr-addon \
    --checkpoints-src <site-packages>/oemer/checkpoints --zip

# もしくはサンプル画像で oemer を 1 回走らせてモデルを取得（数分）
python tools/build_omr_addon.py --out build/omr-addon \
    --sample-image sample_staff.png --zip
```

生成物 `build/omr-addon/omr/`（および `omr.zip`）を配布します。
ビルド成果物は exe と同様 git には入れません（`.gitignore` 済み）。

## 依存の注意（ハマりどころ）

素の `pip install oemer` は現在の最新依存と非互換になりがちです。実機で
動いた組み合わせを `requirements.lock.txt` に固定しており、ビルドは
`pip install --no-deps` でこの一覧をそのまま入れます（全依存を固定済みなので
resolver を通さず、oemer が宣言する `onnxruntime-gpu` に引きずられない）。

- Python 3.12 / Windows amd64
- `oemer==0.1.8`, `numpy==1.26.4`, `scipy==1.13.1`,
  `opencv-python-headless==4.9.0.80`, `onnxruntime==1.19.2`（CPU 版で動作）
- モデルは `oemer` パッケージ内 `checkpoints/{seg_net,unet_big}` に置かれ、
  推論には `model.onnx` のみ使用。TensorFlow 用 `weights.h5`（約 100MB）は
  ビルド時に削除する（`--keep-h5` で残せる）。
- CPU 推論は画像 1 枚あたり数分。

## ライセンス

`oemer` は MIT。同梱する CPython・各依存はそれぞれのライセンスに従います。
アドオンの売り物は「面倒な依存とモデルを固めた利便性」であり、認識ロジック
そのものは OSS です。
