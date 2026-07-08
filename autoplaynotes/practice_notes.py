"""練習メモのデータモデルと永続化補助（GUI 非依存＝テスト可能）。

練習しながら気づきを一行残す機能。**二役**: ユーザーには「練習メモ」
（"この小節が難所"／"指使い"／"テンポ0.75で" 等＝譜面余白への書き込みの
デジタル版）、作り手には dogfooding の backlog（欲しい機能の一次資料）。

Score 単位（タイトル＋音数の簡易キー）でメモを紐づけ、config.practice_notes に
保存する。各入口（テキスト/数字譜/MIDI 等）から来た曲でも、同じ曲を開けば
同じキーになりメモが復元される。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

# 練習中にワンタップで付けられるクイックタグ（自由文と併用）
QUICK_TAGS = ("難所", "指使い", "テンポ", "暗譜", "その他")


@dataclass
class PracticeNote:
    beat: float      # 譜面上の位置（拍）。負値は「位置なし」
    tag: str
    text: str
    created: str     # 記録時刻（呼び出し側で採番＝GUI 側で time.strftime）

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PracticeNote":
        return cls(
            beat=float(data.get("beat", -1.0)),
            tag=str(data.get("tag", "")),
            text=str(data.get("text", "")),
            created=str(data.get("created", "")),
        )

    def summary(self) -> str:
        """一覧表示用の1行。"""
        pos = f"♪{self.beat:.1f}拍" if self.beat >= 0 else "位置なし"
        tag = f"[{self.tag}] " if self.tag else ""
        body = self.text.strip() or "(メモなし)"
        created = f"  — {self.created}" if self.created else ""
        return f"{pos}  {tag}{body}{created}"


def song_key(title: str, event_count: int) -> str:
    """曲の同一性キー（タイトル＋音数の簡易ハッシュ）。同じ曲を開くと復元される。"""
    name = (title or "").strip() or "無題"
    return f"{name}#{event_count}"


def get_notes(store: dict[str, list[dict[str, Any]]], key: str) -> list[PracticeNote]:
    return [PracticeNote.from_dict(d) for d in store.get(key, [])]


def note_count(store: dict[str, list[dict[str, Any]]], key: str) -> int:
    return len(store.get(key, []))


def add_note(store: dict[str, list[dict[str, Any]]], key: str, note: PracticeNote) -> None:
    store.setdefault(key, []).append(note.to_dict())


def delete_note(store: dict[str, list[dict[str, Any]]], key: str, index: int) -> bool:
    """index 番目のメモを削除。空になったらキーごと消す。範囲外は False。"""
    notes = store.get(key)
    if notes is None or not (0 <= index < len(notes)):
        return False
    notes.pop(index)
    if not notes:
        store.pop(key, None)
    return True
