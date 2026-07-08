"""OMR アドオン（別売・自己完結）を組み立てるビルドツール。

本体（単一 exe）とは別に、oemer による自動採譜を「自前ランタイムごと」同梱した
フォルダを作る。買った人は生成物の `omr` フォルダを AutoPlayNotes.exe と同じ場所に
解凍するだけで OMR が使えるようになる（本体側の隣接 dir ドロップイン検出に対応）。

土台には python-build-standalone（再配置可能な CPython）を使う。venv は絶対パスを
埋め込み別マシンで壊れるため配布に使えない。依存は requirements.lock.txt の
正確なピンを `--no-deps` でそのまま入れる（全依存を固定済みなので resolver を
通さず、oemer が宣言する onnxruntime-gpu への引きずられを避ける）。

使い方の例:
  # 既存の checkpoints をコピーして種にする場合
  python tools/build_omr_addon.py --out build/omr-addon \
      --checkpoints-src <oemer をインストール済みの site-packages>/oemer/checkpoints --zip

  # サンプル画像で oemer を 1 回走らせてモデルを取得させる場合（数分かかる）
  python tools/build_omr_addon.py --out build/omr-addon --sample-image sample_staff.png --zip

生成物:
  <out>/omr/               … アドオン本体（これを配布・zip する）
    python/                … 再配置可能 CPython + 依存 + oemer + checkpoints(onnx)
    run_omr.py             … 起動ラッパ
    manifest.json          … 本体が読む起動契約
  <out>/omr.zip            … --zip 指定時
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ADDON_SRC = os.path.join(os.path.dirname(_HERE), "omr-addon")
_LOCK = os.path.join(_ADDON_SRC, "requirements.lock.txt")
_RUN_OMR = os.path.join(_ADDON_SRC, "run_omr.py")

_PBS_API = "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
# 再配置可能・pip 同梱の windows amd64 ビルドを選ぶ
_PBS_SUFFIX = "-x86_64-pc-windows-msvc-install_only.tar.gz"
_PBS_PYVER = "cpython-3.12."


def log(msg: str) -> None:
    print(f"[build-omr-addon] {msg}", flush=True)


def _download(url: str) -> bytes:
    log(f"ダウンロード: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "autoplaynotes-build"})
    with urllib.request.urlopen(req) as resp:  # noqa: S310 (信頼できる公式 URL)
        return resp.read()


def _find_pbs_url() -> str:
    """python-build-standalone の最新から windows amd64 install_only を選ぶ。"""
    data = json.loads(_download(_PBS_API).decode("utf-8"))
    candidates = [
        asset["browser_download_url"]
        for asset in data.get("assets", [])
        if asset["name"].startswith(_PBS_PYVER) and asset["name"].endswith(_PBS_SUFFIX)
    ]
    if not candidates:
        raise RuntimeError(
            "python-build-standalone に該当アセットが見つかりません。"
            "--pbs-url で直接指定してください。"
        )
    # 同一バージョン内で複数出ることは基本ないが、名前順で安定選択
    return sorted(candidates)[-1]


def ensure_python(addon_dir: str, python_dir: str | None, pbs_url: str | None) -> str:
    """addon_dir/python に再配置可能 CPython を用意し python.exe のパスを返す。"""
    dest = os.path.join(addon_dir, "python")
    if python_dir is not None:
        log(f"既存の Python を複製: {python_dir}")
        shutil.copytree(python_dir, dest)
    else:
        url = pbs_url or _find_pbs_url()
        blob = _download(url)
        log("展開中 (python-build-standalone)...")
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            # アーカイブ直下の python/ が addon_dir/python になる。
            # filter="data" で危険なパス/リンクを弾く（Python 3.14 の既定変更にも先行対応）
            tar.extractall(addon_dir, filter="data")
    exe = os.path.join(dest, "python.exe")
    if not os.path.isfile(exe):
        raise RuntimeError(f"python.exe が見つかりません: {exe}")
    return exe


def pip_install(python_exe: str) -> None:
    log("依存をインストール (--no-deps, ロック固定)...")
    subprocess.check_call([
        python_exe, "-m", "pip", "install", "--no-deps", "--no-input",
        "-r", _LOCK,
    ])


def _oemer_checkpoints_dir(python_exe: str) -> str:
    out = subprocess.check_output([
        python_exe, "-c",
        "import os, oemer; print(os.path.join(os.path.dirname(oemer.__file__), 'checkpoints'))",
    ], text=True).strip()
    return out


def seed_checkpoints(python_exe: str, checkpoints_src: str | None,
                     sample_image: str | None) -> None:
    """oemer のモデルを用意する（コピー、または 1 回走らせて取得）。"""
    dest = _oemer_checkpoints_dir(python_exe)
    onnx = os.path.join(dest, "unet_big", "model.onnx")
    if os.path.isfile(onnx):
        log("checkpoints は既に存在")
        return
    if checkpoints_src is not None:
        log(f"checkpoints をコピー: {checkpoints_src} -> {dest}")
        shutil.copytree(checkpoints_src, dest, dirs_exist_ok=True)
        return
    if sample_image is not None:
        log("サンプル画像で oemer を実行してモデルを取得（数分かかります）...")
        tmp_out = os.path.join(os.path.dirname(dest), "_seed_out")
        os.makedirs(tmp_out, exist_ok=True)
        subprocess.check_call([python_exe, _RUN_OMR, "-o", tmp_out, sample_image])
        shutil.rmtree(tmp_out, ignore_errors=True)
        if not os.path.isfile(onnx):
            raise RuntimeError("oemer 実行後も model.onnx が見つかりません。")
        return
    raise RuntimeError(
        "checkpoints がありません。--checkpoints-src か --sample-image を指定してください。"
    )


def strip_tf_weights(python_exe: str) -> int:
    """TensorFlow 用の weights.h5 を削除（onnxruntime 経由なので不要・約 100MB 節約）。"""
    dest = _oemer_checkpoints_dir(python_exe)
    removed = 0
    for root, _dirs, files in os.walk(dest):
        for name in files:
            if name.endswith(".h5"):
                os.remove(os.path.join(root, name))
                removed += 1
    log(f"weights.h5 を {removed} 個削除（onnx のみ残す）")
    return removed


def _prune(addon_dir: str) -> None:
    """配布サイズ削減: __pycache__ とテストデータを削る。"""
    for root, dirs, _files in os.walk(addon_dir):
        for name in list(dirs):
            if name == "__pycache__":
                shutil.rmtree(os.path.join(root, name), ignore_errors=True)
                dirs.remove(name)


def write_manifest(addon_dir: str, version: str) -> None:
    manifest = {
        "name": "AutoPlayNotes OMR アドオン",
        "version": version,
        "engine": "oemer 0.1.8 (onnxruntime)",
        "command": ["python/python.exe", "{addon}/run_omr.py", "-o", "{out}", "{image}"],
    }
    path = os.path.join(addon_dir, "manifest.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=2)
    log(f"manifest.json を書き出し: {path}")


def _zip_dir(addon_dir: str, zip_path: str) -> None:
    log(f"zip 作成: {zip_path}")
    base = os.path.dirname(addon_dir)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _dirs, files in os.walk(addon_dir):
            for name in files:
                full = os.path.join(root, name)
                zf.write(full, os.path.relpath(full, base))


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
    out = os.path.abspath(args.out)
    addon_dir = os.path.join(out, "omr")
    if os.path.exists(addon_dir):
        if not args.force:
            raise RuntimeError(f"{addon_dir} が既に存在します（--force で上書き）。")
        shutil.rmtree(addon_dir)
    os.makedirs(addon_dir, exist_ok=True)

    python_exe = ensure_python(addon_dir, args.python_dir, args.pbs_url)
    pip_install(python_exe)
    seed_checkpoints(python_exe, args.checkpoints_src, args.sample_image)
    if not args.keep_h5:
        strip_tf_weights(python_exe)
    shutil.copy2(_RUN_OMR, os.path.join(addon_dir, "run_omr.py"))
    write_manifest(addon_dir, args.version)
    _prune(addon_dir)

    log(f"アドオン完成: {addon_dir}  ({_dir_size_mb(addon_dir):.0f} MB)")
    if args.zip:
        _zip_dir(addon_dir, os.path.join(out, "omr.zip"))
    log("完了。生成された omr フォルダを AutoPlayNotes.exe と同じ場所に置けば動作します。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="OMR アドオンを組み立てる")
    parser.add_argument("--out", required=True, help="ビルド先（この下に omr/ を作る）")
    parser.add_argument("--version", default="0.1.0", help="manifest に書くアドオン版")
    parser.add_argument("--python-dir", default=None,
                        help="再配置可能 Python を新規 DL せず既存を複製する場合のパス")
    parser.add_argument("--pbs-url", default=None,
                        help="python-build-standalone のアセット URL を直接指定")
    parser.add_argument("--checkpoints-src", default=None,
                        help="oemer の checkpoints フォルダ（seg_net/unet_big を含む）")
    parser.add_argument("--sample-image", default=None,
                        help="モデル未取得時に oemer を 1 回走らせる五線譜画像")
    parser.add_argument("--keep-h5", action="store_true",
                        help="TensorFlow 用 weights.h5 を残す（既定は削除）")
    parser.add_argument("--zip", action="store_true", help="omr.zip も作る")
    parser.add_argument("--force", action="store_true", help="既存の omr/ を上書き")
    args = parser.parse_args()
    try:
        return build(args)
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        log(f"失敗: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
