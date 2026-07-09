"""設定の保存 / 読み込み（%APPDATA%/AutoPlayNotes/config.json）。"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from typing import Any

from .keymap import KeyMapping, PRESETS

APP_NAME = "AutoPlayNotes"


def config_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def config_path() -> str:
    return os.path.join(config_dir(), "config.json")


@dataclass
class AppConfig:
    active_mapping: str = "chromatic"  # プリセット名 or "custom"
    tempo_bpm: float = 120.0
    default_octave: int = 4
    count_in_seconds: float = 3.0
    gate_ms: float = 40.0  # 最短の押し下げ時間。持続音楽器では音長がこれを上回る
    retrigger_gap_ms: float = 25.0  # 同じキーを鳴らし直すとき、離してから押すまでの間隔
    speed: float = 1.0
    # ヒューマナイズ
    timing_jitter_ms: float = 0.0
    gate_jitter_pct: float = 0.0
    chord_roll_ms: float = 0.0
    hotkey_start: str = "F9"
    hotkey_stop: str = "F10"
    loop: bool = False
    dark: bool = True
    # 補助演奏: 演奏範囲は自分で弾き、アプリは範囲外だけをゲームへ送る（グレー）
    assist_play: bool = False
    # 初回起動時のみようこそ画面を表示する
    first_run: bool = True
    # ユーザー定義マッピング（プリセットを上書き / 追加）
    custom_mappings: dict[str, dict[str, Any]] = field(default_factory=dict)
    # プレイリスト（PlaylistItem.to_dict のリスト）
    playlist: list[dict[str, Any]] = field(default_factory=list)
    # 練習メモ（曲キー -> メモ dict のリスト。practice_notes モジュール参照）
    practice_notes: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # 演奏範囲（曲キー -> 自分で弾くキーのリスト。keywindow モジュール参照）
    key_windows: dict[str, list[str]] = field(default_factory=dict)

    def mapping(self) -> KeyMapping:
        """現在有効なマッピングを返す。"""
        if self.active_mapping in self.custom_mappings:
            return KeyMapping.from_dict(self.custom_mappings[self.active_mapping])
        presets = PRESETS()
        if self.active_mapping in presets:
            return presets[self.active_mapping]
        # フォールバック
        return presets["chromatic"]

    def mapping_names(self) -> list[str]:
        names = list(PRESETS().keys())
        for name in self.custom_mappings:
            if name not in names:
                names.append(name)
        return names

    def save(self) -> None:
        """設定を保存する。直前の内容を .bak に残し、書き込みはアトミックに行う。

        設定にはカスタムのキー割り当て・プレイリスト・練習メモが入る。保存中に落ちたり、
        既定値で上書きしてしまったりすると、ユーザーの手作業が黙って消える。
        .bak があれば手で戻せる。
        """
        path = config_path()
        if os.path.exists(path):
            try:
                shutil.copy2(path, path + ".bak")
            except OSError:
                pass  # バックアップに失敗しても保存自体は続ける

        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # 同一ボリューム上での置換はアトミック

    @classmethod
    def load(cls) -> "AppConfig":
        path = config_path()
        if not os.path.exists(path):
            return cls()
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return cls()
        config = cls()
        for key, value in data.items():
            if hasattr(config, key):
                setattr(config, key, value)
        return config
