"""採譜アドオン（音源→MIDI・別売・自己完結）を組み立てるビルドツール。

本体（単一 exe）とは別に、basic-pitch による音源採譜を「自前ランタイムごと」同梱した
フォルダを作る。買った人は生成物の `pitch` フォルダを AutoPlayNotes.exe と同じ場所に
解凍するだけで使えるようになる（本体側の隣接 dir ドロップイン検出に対応）。

土台には python-build-standalone（再配置可能な CPython）を使う。venv は絶対パスを
埋め込み別マシンで壊れるため配布に使えない。依存は requirements.lock.txt の正確な
ピンを `--no-deps` でそのまま入れる（basic-pitch が引きずる重い依存を避ける）。
basic-pitch の onnx モデル（nmp.onnx）は wheel 同梱なので種付け不要。

使い方:
  python tools/build_pitch_addon.py --out D:/pitch_build --zip

生成物:
  <out>/pitch/             … アドオン本体（これを配布・zip する）
    python/                … 再配置可能 CPython + 依存 + basic-pitch + nmp.onnx
    run_pitch.py           … 起動ラッパ
    manifest.json          … 本体が読む起動契約
  <out>/pitch.zip          … --zip 指定時

構造は tools/build_omr_addon.py と対。将来は共通部を抽出して1本化してもよい。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import subprocess
import tarfile
import urllib.request
import zipfile

_HERE = os.path.dirname(os.path.abspath(__file__))
_ADDON_SRC = os.path.join(os.path.dirname(_HERE), "pitch-addon")
_LOCK = os.path.join(_ADDON_SRC, "requirements.lock.txt")
_RUN_PITCH = os.path.join(_ADDON_SRC, "run_pitch.py")

_PBS_API = "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
# 再配置可能・pip 同梱の windows amd64 ビルドを選ぶ
_PBS_SUFFIX = "-x86_64-pc-windows-msvc-install_only.tar.gz"
_PBS_PYVER = "cpython-3.12."


def log(msg: str) -> None:
    print(f"[build-pitch-addon] {msg}", flush=True)


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
            # filter="data" で危険なパス/リンクを弾く（Python 3.14 既定変更にも先行対応）
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


def _saved_models_dir(python_exe: str) -> str:
    out = subprocess.check_output([
        python_exe, "-c",
        "import os, basic_pitch; print(os.path.join(os.path.dirname(basic_pitch.__file__), 'saved_models'))",
    ], text=True).strip()
    return out


def verify_model(python_exe: str) -> None:
    """basic-pitch の onnx モデルが wheel 同梱で入っているか確認する。"""
    saved = _saved_models_dir(python_exe)
    onnx = os.path.join(saved, "icassp_2022", "nmp.onnx")
    if not os.path.isfile(onnx):
        raise RuntimeError(
            f"onnx モデルが見つかりません: {onnx}\n"
            "basic-pitch の wheel に saved_models が含まれているか確認してください。"
        )
    log(f"onnx モデル確認: {onnx} ({os.path.getsize(onnx) / 1024:.0f} KB)")


def strip_extra_backends(python_exe: str) -> int:
    """onnx 以外のバックエンド（tf SavedModel / tflite / coreml）を削除する。

    onnxruntime のみで推論するので不要。サイズ削減は僅かだが配布物を綺麗に保つ。
    """
    saved = os.path.join(_saved_models_dir(python_exe), "icassp_2022")
    removed = 0
    targets_files = ("nmp.tflite",)
    targets_dirs = ("nmp", "nmp.mlpackage")
    for name in targets_files:
        path = os.path.join(saved, name)
        if os.path.isfile(path):
            os.remove(path)
            removed += 1
    for name in targets_dirs:
        path = os.path.join(saved, name)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            removed += 1
    log(f"onnx 以外のバックエンドを {removed} 個削除（nmp.onnx のみ残す）")
    return removed


def _prune(addon_dir: str) -> None:
    """配布サイズ削減: __pycache__ を削る。"""
    for root, dirs, _files in os.walk(addon_dir):
        for name in list(dirs):
            if name == "__pycache__":
                shutil.rmtree(os.path.join(root, name), ignore_errors=True)
                dirs.remove(name)


def write_manifest(addon_dir: str, version: str) -> None:
    manifest = {
        "name": "AutoPlayNotes 採譜アドオン (音源→MIDI)",
        "version": version,
        "engine": "basic-pitch 0.4.0 (onnxruntime)",
        "command": ["python/python.exe", "{addon}/run_pitch.py", "{out}", "{audio}"],
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
    addon_dir = os.path.join(out, "pitch")
    if os.path.exists(addon_dir):
        if not args.force:
            raise RuntimeError(f"{addon_dir} が既に存在します（--force で上書き）。")
        shutil.rmtree(addon_dir)
    os.makedirs(addon_dir, exist_ok=True)

    python_exe = ensure_python(addon_dir, args.python_dir, args.pbs_url)
    pip_install(python_exe)
    verify_model(python_exe)
    if not args.keep_extra_models:
        strip_extra_backends(python_exe)
    shutil.copy2(_RUN_PITCH, os.path.join(addon_dir, "run_pitch.py"))
    write_manifest(addon_dir, args.version)
    _prune(addon_dir)

    log(f"アドオン完成: {addon_dir}  ({_dir_size_mb(addon_dir):.0f} MB)")
    if args.zip:
        _zip_dir(addon_dir, os.path.join(out, "pitch.zip"))
    log("完了。生成された pitch フォルダを AutoPlayNotes.exe と同じ場所に置けば動作します。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="採譜アドオン（音源→MIDI）を組み立てる")
    parser.add_argument("--out", required=True, help="ビルド先（この下に pitch/ を作る）")
    parser.add_argument("--version", default="0.1.0", help="manifest に書くアドオン版")
    parser.add_argument("--python-dir", default=None,
                        help="再配置可能 Python を新規 DL せず既存を複製する場合のパス")
    parser.add_argument("--pbs-url", default=None,
                        help="python-build-standalone のアセット URL を直接指定")
    parser.add_argument("--keep-extra-models", action="store_true",
                        help="onnx 以外のバックエンド（tf/tflite/coreml）を残す（既定は削除）")
    parser.add_argument("--zip", action="store_true", help="pitch.zip も作る")
    parser.add_argument("--force", action="store_true", help="既存の pitch/ を上書き")
    args = parser.parse_args()
    try:
        return build(args)
    except (RuntimeError, subprocess.CalledProcessError, OSError) as exc:
        log(f"失敗: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
