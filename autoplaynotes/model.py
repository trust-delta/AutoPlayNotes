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


def sequential_durations(events: list[NoteEvent]) -> list[tuple[NoteEvent, float]]:
    """開始時刻順のイベントと「逐次記譜用に切り詰めた音長」の組を返す。

    テキスト記譜・数字譜は「前の音が終わってから次の音」の逐次形式なので、
    音が重なっている場合（MusicXML の複声部など）にそのままの音長で書き出すと
    後続の発音タイミングが全てずれる。次の音の開始位置で音長を切り詰めることで
    発音タイミングを保つ（音長は犠牲になる）。
    """
    ordered = sorted(events, key=lambda e: e.start_beat)
    result: list[tuple[NoteEvent, float]] = []
    for i, event in enumerate(ordered):
        duration = event.duration_beat
        if i + 1 < len(ordered):
            gap_to_next = ordered[i + 1].start_beat - event.start_beat
            if 1e-9 < gap_to_next < duration:
                duration = gap_to_next
        result.append((event, duration))
    return result


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
