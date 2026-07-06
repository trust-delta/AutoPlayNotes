"""楽譜の内部データモデル。

テキスト記譜・MIDI いずれの入力もこのモデルに変換してから演奏する。
時間の単位は「拍 (beat)」で保持し、演奏時に BPM で秒へ変換する。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NoteEvent:
    """同時に発音する音（和音）のまとまり。

    midi_notes が空タプルの場合は休符を表す。
    """

    start_beat: float
    duration_beat: float
    midi_notes: tuple[int, ...]

    @property
    def is_rest(self) -> bool:
        return len(self.midi_notes) == 0


@dataclass
class Score:
    """1 曲分の楽譜。"""

    tempo_bpm: float = 120.0
    events: list[NoteEvent] = field(default_factory=list)
    title: str = ""

    def total_beats(self) -> float:
        if not self.events:
            return 0.0
        return max(e.start_beat + e.duration_beat for e in self.events)

    def total_seconds(self, bpm: float | None = None) -> float:
        beats = self.total_beats()
        tempo = bpm if bpm is not None else self.tempo_bpm
        if tempo <= 0:
            return 0.0
        return beats * (60.0 / tempo)
