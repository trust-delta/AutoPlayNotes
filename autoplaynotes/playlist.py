"""プレイリスト（連続再生）のデータモデル。

各項目は「楽譜のソース（テキスト/数字譜/MIDI）＋パラメータ」を保持し、
再生時に build_score() で Score を生成する。設定ファイルへ保存できるよう
to_dict / from_dict も提供する。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import midi_parser
from .model import Score
from .number_parser import parse_numbers
from .text_parser import parse_text


@dataclass
class PlaylistItem:
    name: str
    kind: str  # "text" | "number" | "midi"
    text: str = ""
    midi_path: str = ""
    midi_selection: list[tuple[int, int]] | None = None
    midi_mono: bool = False
    midi_octave: int = 0
    tempo: float = 120.0
    octave: int = 4
    key: str = "C"

    def build_score(self) -> Score:
        if self.kind == "midi":
            selected = set(self.midi_selection) if self.midi_selection else None
            return midi_parser.build_score(
                self.midi_path,
                selected_keys=selected,
                monophonic=self.midi_mono,
                octave_shift=self.midi_octave,
            )
        if self.kind == "number":
            return parse_numbers(
                self.text, default_tempo=self.tempo, default_octave=self.octave, default_key=self.key
            )
        return parse_text(self.text, default_tempo=self.tempo, default_octave=self.octave)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "text": self.text,
            "midi_path": self.midi_path,
            "midi_selection": (
                [list(k) for k in self.midi_selection] if self.midi_selection is not None else None
            ),
            "midi_mono": self.midi_mono,
            "midi_octave": self.midi_octave,
            "tempo": self.tempo,
            "octave": self.octave,
            "key": self.key,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlaylistItem":
        sel = data.get("midi_selection")
        selection = [tuple(k) for k in sel] if sel else None
        return cls(
            name=str(data.get("name", "曲")),
            kind=str(data.get("kind", "text")),
            text=str(data.get("text", "")),
            midi_path=str(data.get("midi_path", "")),
            midi_selection=selection,
            midi_mono=bool(data.get("midi_mono", False)),
            midi_octave=int(data.get("midi_octave", 0)),
            tempo=float(data.get("tempo", 120.0)),
            octave=int(data.get("octave", 4)),
            key=str(data.get("key", "C")),
        )


class Playlist:
    def __init__(self) -> None:
        self.items: list[PlaylistItem] = []
        self.index = 0

    def add(self, item: PlaylistItem) -> None:
        self.items.append(item)

    def remove(self, i: int) -> None:
        if 0 <= i < len(self.items):
            del self.items[i]
            if self.index >= len(self.items):
                self.index = max(0, len(self.items) - 1)

    def move(self, i: int, delta: int) -> int:
        j = i + delta
        if 0 <= i < len(self.items) and 0 <= j < len(self.items):
            self.items[i], self.items[j] = self.items[j], self.items[i]
            return j
        return i

    def clear(self) -> None:
        self.items.clear()
        self.index = 0

    def current(self) -> PlaylistItem | None:
        if 0 <= self.index < len(self.items):
            return self.items[self.index]
        return None

    def has_next(self) -> bool:
        return self.index + 1 < len(self.items)

    def advance(self) -> None:
        if self.has_next():
            self.index += 1

    def set_index(self, i: int) -> None:
        if 0 <= i < len(self.items):
            self.index = i
