"""五線譜画像の OMR（光学楽譜認識）連携。

自動採譜（画像 → MusicXML → Score）は重い深層学習依存を要するため、
本体（BOOTH 配布の単一 exe）には同梱せず、**別売の自己完結アドオン**として
切り出す方針。アドオンは自前のランタイム（埋め込み Python 等）とモデルを
丸ごと同梱したフォルダで、AutoPlayNotes.exe と同じ場所の「omr」ディレクトリに
解凍するだけで使えるようにする（隣接 dir ドロップイン）。

本モジュールは「エンジンをどこから起動するか」を解決する層。
優先順位は 1) 隣接アドオン（manifest.json 記載のコマンド）→
2) 開発環境の PATH 上 oemer（`pip install oemer`）→ 3) 未導入。
本体はこの層越しに subprocess でエンジンを叩くだけなので、将来
アドオンの中身（凍結 exe / 埋め込み Python / 別エンジン）を差し替えても
本体側は変更不要。

認識には CPU で数分かかることがある。結果は下書き品質なので、
取り込み後に五線譜エディタで修正する前提の設計。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# 本体 exe と隣接して置くアドオンフォルダ名（この直下に manifest.json）
ADDON_DIRNAME = "omr"
# アドオンの場所を明示指定するための環境変数（フォルダを直接指す）
ADDON_ENV = "AUTOPLAYNOTES_OMR_ADDON"
# 開発環境で PATH 上の oemer を叩くときの既定コマンド（{out}/{image} を後で埋める）
_PATH_COMMAND = ("oemer", "-o", "{out}", "{image}")


class OmrError(RuntimeError):
    """OMR の実行に失敗したときの例外。"""


@dataclass(frozen=True)
class OmrEngine:
    """解決済みの OMR エンジン起動情報。

    command は argv テンプレート。`{image}`（入力画像）と `{out}`（出力先
    フォルダ）を実行時に置換する。source=="addon" のとき command[0] が
    相対パスなら base_dir 基準で絶対化する。env の値では `{addon}` を
    base_dir に置換できる（同梱モデルの場所を渡す等）。
    """

    source: str            # "addon" | "path"
    command: tuple[str, ...]
    base_dir: str = ""     # アドオンフォルダ（source=="addon" のとき）
    env: dict[str, str] = field(default_factory=dict)
    name: str = "OMR エンジン"


def install_hint() -> str:
    """アドオン未導入時にユーザーへ見せる導入案内。"""
    return (
        "五線譜画像の自動読み取り（OMR）には別売のアドオンが必要です。\n"
        f"購入したアドオンの「{ADDON_DIRNAME}」フォルダを、AutoPlayNotes.exe と\n"
        "同じ場所に置いてから、もう一度お試しください。\n\n"
        "（開発者向け: Python 環境に pip install oemer でも動作します）"
    )


def _addon_dirs() -> list[str]:
    """アドオンフォルダの探索候補を優先順に返す（重複除去・絶対パス）。"""
    candidates: list[str] = []
    override = os.environ.get(ADDON_ENV)
    if override:
        candidates.append(override)  # 環境変数はアドオンフォルダを直接指す
    if getattr(sys, "frozen", False):
        # 配布形態: AutoPlayNotes.exe と同じ場所の隣接フォルダ
        candidates.append(os.path.join(os.path.dirname(sys.executable), ADDON_DIRNAME))
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(os.path.dirname(here), ADDON_DIRNAME))  # 開発時=リポジトリ直下
    candidates.append(os.path.join(os.getcwd(), ADDON_DIRNAME))

    seen: set[str] = set()
    result: list[str] = []
    for path in candidates:
        absolute = os.path.abspath(path)
        if absolute not in seen:
            seen.add(absolute)
            result.append(absolute)
    return result


def _load_addon(base_dir: str) -> OmrEngine | None:
    """アドオンフォルダの manifest.json を読み、起動情報を作る（不正なら None）。"""
    manifest = os.path.join(base_dir, "manifest.json")
    if not os.path.isfile(manifest):
        return None
    try:
        with open(manifest, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    command = data.get("command")
    if (
        not isinstance(command, list)
        or not command
        or not all(isinstance(token, str) for token in command)
    ):
        return None
    raw_env = data.get("env")
    env = {
        str(key): str(value)
        for key, value in raw_env.items()
    } if isinstance(raw_env, dict) else {}
    name = data.get("name") if isinstance(data.get("name"), str) else "OMR アドオン"
    return OmrEngine(
        source="addon",
        command=tuple(command),
        base_dir=base_dir,
        env=env,
        name=name,
    )


def resolve_engine() -> OmrEngine | None:
    """利用可能な OMR エンジンを優先順に解決する（無ければ None）。"""
    for base_dir in _addon_dirs():
        engine = _load_addon(base_dir)
        if engine is not None:
            return engine
    if shutil.which("oemer") is not None:
        return OmrEngine(source="path", command=_PATH_COMMAND, name="oemer (PATH)")
    return None


def is_available() -> bool:
    """OMR エンジン（アドオン or 開発用 oemer）が使えるか。"""
    return resolve_engine() is not None


def _fill(token: str, mapping: dict[str, str]) -> str:
    for key, value in mapping.items():
        token = token.replace("{" + key + "}", value)
    return token


def _build_command(
    engine: OmrEngine, image_path: str, output_dir: str
) -> tuple[list[str], dict[str, str] | None]:
    """エンジンの argv とサブプロセス環境を実値で組み立てる。"""
    mapping = {"image": image_path, "out": output_dir}
    argv: list[str] = []
    for index, token in enumerate(engine.command):
        filled = _fill(token, mapping)
        if index == 0 and engine.source == "addon" and not os.path.isabs(filled):
            filled = os.path.join(engine.base_dir, filled)
        argv.append(filled)

    run_env: dict[str, str] | None = None
    if engine.env:
        run_env = dict(os.environ)
        for key, value in engine.env.items():
            run_env[key] = _fill(value, {"addon": engine.base_dir})
    return argv, run_env


def transcribe(
    image_path: str,
    output_dir: str | None = None,
    on_progress: Callable[[str], None] | None = None,
    timeout: float = 1800.0,
) -> str:
    """五線譜画像を OMR エンジンで MusicXML に変換し、生成ファイルのパスを返す。

    output_dir 省略時は画像と同じフォルダに出力する（ユーザーの手元に残す）。
    on_progress にはエンジンの進捗ログが 1 行ずつ渡される。
    """
    engine = resolve_engine()
    if engine is None:
        raise OmrError(install_hint())
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(image_path)) or "."
    os.makedirs(output_dir, exist_ok=True)

    argv, run_env = _build_command(engine, image_path, output_dir)

    started = time.monotonic()
    wall_started = time.time()  # ファイル mtime との比較用
    before = _musicxml_set(output_dir)
    try:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATE_NO_WINDOW,
            env=run_env,
        )
    except OSError as exc:
        raise OmrError(f"OMR エンジンを起動できません: {exc}") from exc

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
    raise OmrError("OMR エンジンは終了しましたが、MusicXML が見つかりませんでした。")


def _musicxml_set(directory: str) -> set[str]:
    try:
        return {
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if name.lower().endswith(".musicxml")
        }
    except OSError:
        return set()
