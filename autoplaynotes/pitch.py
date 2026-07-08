"""音源（音声ファイル）→ MIDI の自動採譜（AMT）連携。

音声からの採譜（basic-pitch など）は重い依存を要するため、OMR（`omr.py`）と
同様に本体（BOOTH 配布の単一 exe）には同梱せず、**別売の自己完結アドオン**として
切り出す方針。アドオンは自前のランタイム（埋め込み Python 等）とモデルを丸ごと
同梱したフォルダで、AutoPlayNotes.exe と同じ場所の「pitch」ディレクトリに解凍する
だけで使えるようにする（隣接 dir ドロップイン）。

本モジュールは「エンジンをどこから起動するか」を解決する層。優先順位は
1) 隣接アドオン（manifest.json 記載のコマンド）→ 2) 開発環境の PATH 上
`basic-pitch`（`pip install basic-pitch`）→ 3) 未導入。本体はこの層越しに
subprocess でエンジンを叩き、生成された **MIDI ファイルのパス**を返すだけ。
返した MIDI は既存の MIDI 取り込み経路（`midi_parser` → Score → 練習/自動演奏）へ
そのまま流し込めるので、「音源 → MIDI → 楽譜 → 練習」が一気通貫でつながる。

結果は下書き品質（recall 高・precision は素材のクリーンさ依存）なので、取り込み後に
五線譜エディタ／トレースで修正する前提の設計。

※ `omr.py` と解決層のロジックがほぼ共通。将来 3b（落ちノーツ動画）アドオンを
足す時点で、共通部分を `addon.py` へ抽出してリファクタする想定（それまでは
検証済みの `omr.py` に手を入れないため、意図的に並行実装している）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Callable

_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# 本体 exe と隣接して置くアドオンフォルダ名（この直下に manifest.json）
ADDON_DIRNAME = "pitch"
# アドオンの場所を明示指定するための環境変数（フォルダを直接指す）
ADDON_ENV = "AUTOPLAYNOTES_PITCH_ADDON"
# 開発環境で PATH 上の basic-pitch を叩くときの既定コマンド
# （basic-pitch CLI は `basic-pitch <出力先フォルダ> <音声ファイル>`）
_PATH_COMMAND = ("basic-pitch", "{out}", "{audio}")

# 対応する音声拡張子（ファイル選択・判定用）
AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".aiff", ".aif")


class PitchError(RuntimeError):
    """音源採譜の実行に失敗したときの例外。"""


@dataclass(frozen=True)
class PitchEngine:
    """解決済みの採譜エンジン起動情報。

    command は argv テンプレート。`{audio}`（入力音声）・`{out}`（出力先
    フォルダ）・`{addon}`（アドオンフォルダ=base_dir）を実行時に置換する。
    source=="addon" のとき command[0] が相対パスなら base_dir 基準で絶対化する。
    env の値でも `{addon}` を base_dir に置換できる（同梱モデルの場所を渡す等）。
    """

    source: str            # "addon" | "path"
    command: tuple[str, ...]
    base_dir: str = ""     # アドオンフォルダ（source=="addon" のとき）
    env: dict[str, str] = field(default_factory=dict)
    name: str = "採譜エンジン"


def is_audio_path(path: str) -> bool:
    """音声ファイルの拡張子か。"""
    return os.path.splitext(path)[1].lower() in AUDIO_EXTENSIONS


def install_hint() -> str:
    """アドオン未導入時にユーザーへ見せる導入案内。"""
    return (
        "音源（音声ファイル）からの自動採譜には別売のアドオンが必要です。\n"
        f"購入したアドオンの「{ADDON_DIRNAME}」フォルダを、AutoPlayNotes.exe と\n"
        "同じ場所に置いてから、もう一度お試しください。\n\n"
        "（開発者向け: Python 環境に pip install basic-pitch でも動作します）"
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


def _load_addon(base_dir: str) -> PitchEngine | None:
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
    name = data.get("name") if isinstance(data.get("name"), str) else "採譜アドオン"
    return PitchEngine(
        source="addon",
        command=tuple(command),
        base_dir=base_dir,
        env=env,
        name=name,
    )


def resolve_engine() -> PitchEngine | None:
    """利用可能な採譜エンジンを優先順に解決する（無ければ None）。"""
    for base_dir in _addon_dirs():
        engine = _load_addon(base_dir)
        if engine is not None:
            return engine
    if shutil.which("basic-pitch") is not None:
        return PitchEngine(source="path", command=_PATH_COMMAND, name="basic-pitch (PATH)")
    return None


def is_available() -> bool:
    """採譜エンジン（アドオン or 開発用 basic-pitch）が使えるか。"""
    return resolve_engine() is not None


def _fill(token: str, mapping: dict[str, str]) -> str:
    for key, value in mapping.items():
        token = token.replace("{" + key + "}", value)
    return token


def _build_command(
    engine: PitchEngine, audio_path: str, output_dir: str
) -> tuple[list[str], dict[str, str] | None]:
    """エンジンの argv とサブプロセス環境を実値で組み立てる。"""
    mapping = {"audio": audio_path, "out": output_dir, "addon": engine.base_dir}
    argv: list[str] = []
    for index, token in enumerate(engine.command):
        filled = _fill(token, mapping)
        if index == 0 and engine.source == "addon" and not os.path.isabs(filled):
            # 実行ファイルは OS ネイティブ区切りに正規化（CreateProcess 対策）
            filled = os.path.normpath(os.path.join(engine.base_dir, filled))
        argv.append(filled)

    run_env: dict[str, str] | None = None
    if engine.env:
        run_env = dict(os.environ)
        for key, value in engine.env.items():
            run_env[key] = _fill(value, {"addon": engine.base_dir})
    return argv, run_env


def transcribe(
    audio_path: str,
    output_dir: str | None = None,
    on_progress: Callable[[str], None] | None = None,
    timeout: float = 1800.0,
) -> str:
    """音声ファイルを採譜エンジンで MIDI に変換し、生成ファイルのパスを返す。

    output_dir 省略時は音声と同じフォルダに出力する（ユーザーの手元に残す）。
    on_progress にはエンジンの進捗ログが 1 行ずつ渡される。
    返り値の MIDI は既存の midi_parser 経路へそのまま渡せる。
    """
    engine = resolve_engine()
    if engine is None:
        raise PitchError(install_hint())
    if output_dir is None:
        output_dir = os.path.dirname(os.path.abspath(audio_path)) or "."
    os.makedirs(output_dir, exist_ok=True)

    # basic-pitch は既存の出力ファイルがあると上書きを拒否して失敗する。専用の作業
    # ディレクトリへ出力させ、成功後に最終フォルダへ移すことで「同じ音源の再採譜
    # （＝自前の前回出力の置き換え）」を可能にする。work_dir は output_dir 直下に
    # 作る（同一ファイルシステムなので移動が rename で済む）。
    work_dir = tempfile.mkdtemp(prefix="apn_pitch_", dir=output_dir)
    try:
        argv, run_env = _build_command(engine, audio_path, work_dir)

        started = time.monotonic()
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
            raise PitchError(f"採譜エンジンを起動できません: {exc}") from exc

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
                    raise PitchError("音源の採譜がタイムアウトしました。")
            proc.wait(timeout=60)
        finally:
            proc.stdout.close()

        if proc.returncode != 0:
            detail = " / ".join(tail[-3:])
            raise PitchError(f"音源の採譜に失敗しました。{detail[:300]}")

        produced = _midi_set(work_dir)
        if not produced:
            raise PitchError("採譜エンジンは終了しましたが、MIDI が見つかりませんでした。")
        newest = max(produced, key=lambda p: os.path.getmtime(p))
        final = os.path.join(output_dir, os.path.basename(newest))
        if os.path.abspath(final) != os.path.abspath(newest):
            if os.path.exists(final):
                os.remove(final)  # 同じ音源の再採譜＝自前の前回出力を置き換える
            shutil.move(newest, final)
        return final
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _midi_set(directory: str) -> set[str]:
    try:
        return {
            os.path.join(directory, name)
            for name in os.listdir(directory)
            if name.lower().endswith((".mid", ".midi"))
        }
    except OSError:
        return set()
