"""五線譜画像の OMR（光学楽譜認識）連携。

外部ツール oemer (MIT License) がインストールされていれば、
画像 → MusicXML → Score の流れをアプリ内で完結させる。
oemer は深層学習モデルを使う重い依存のため任意導入とし
（pip install oemer）、無くてもアプリ本体や MusicXML 取り込みは動く。

認識には CPU で数分かかることがある。結果は下書き品質なので、
取り込み後に五線譜エディタで修正する前提の設計。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from typing import Callable

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class OmrError(RuntimeError):
    """OMR の実行に失敗したときの例外。"""


def is_available() -> bool:
    """oemer コマンドが使えるか。"""
    return shutil.which("oemer") is not None


def transcribe(
    image_path: str,
    output_dir: str | None = None,
    on_progress: Callable[[str], None] | None = None,
    timeout: float = 1800.0,
) -> str:
    """五線譜画像を oemer で MusicXML に変換し、生成されたファイルのパスを返す。

    output_dir 省略時は画像と同じフォルダに出力する（ユーザーの手元に残す）。
    on_progress には oemer の進捗ログが 1 行ずつ渡される。
    """
    if not is_available():
        raise OmrError(
            "五線譜の読み取りには oemer が必要です。"
            "Python 環境で 'pip install oemer' を実行してください。"
        )
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(image_path)) or "."
    os.makedirs(output_dir, exist_ok=True)

    started = time.monotonic()
    wall_started = time.time()  # ファイル mtime との比較用
    before = _musicxml_set(output_dir)
    try:
        proc = subprocess.Popen(
            ["oemer", "-o", output_dir, image_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATE_NO_WINDOW,
        )
    except OSError as exc:
        raise OmrError(f"oemer を起動できません: {exc}") from exc

    tail: list[str] = []
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            tail.append(line)
            if len(tail) > 20:
                tail.pop(0)
            if on_progress is not None:
                on_progress(line)
            if time.monotonic() - started > timeout:
                proc.kill()
                raise OmrError("五線譜の認識がタイムアウトしました。")
        proc.wait(timeout=60)
    finally:
        proc.stdout.close()

    if proc.returncode != 0:
        detail = " / ".join(tail[-3:])
        raise OmrError(f"五線譜の認識に失敗しました。{detail[:300]}")

    created = _musicxml_set(output_dir) - before
    if created:
        newest = max(created, key=lambda p: os.path.getmtime(p))
        return newest
    # 上書き出力された場合に備え、想定ファイル名も確認する
    stem = os.path.splitext(os.path.basename(image_path))[0]
    expected = os.path.join(output_dir, f"{stem}.musicxml")
    if os.path.exists(expected) and os.path.getmtime(expected) >= wall_started - 1:
        return expected
    raise OmrError("oemer は終了しましたが、MusicXML が見つかりませんでした。")


def _musicxml_set(directory: str) -> set[str]:
    try:
        return {
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if name.lower().endswith(".musicxml")
        }
    except OSError:
        return set()
