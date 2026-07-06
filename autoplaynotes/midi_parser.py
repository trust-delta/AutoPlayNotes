"""MIDI ファイルの読み込み（トラック/チャンネル選択対応）。

1 つの MIDI は複数パート（メロディ・伴奏・ベース・ドラム等）に分かれている。
- inspect_midi(): パート一覧（トラック×チャンネル）と各パートの音数・音域を返す
- build_score(): 選択したパートだけを 1 本の時間軸へ統合して Score を作る
    - monophonic: 各時点で最高音のみ残す（メロディ抽出）
    - octave_shift: 全体をオクターブ単位で移調

mido が未インストールでもアプリ本体は動くよう、実ファイル読み込み時のみ遅延インポートする。
パート分け・和音統合・単音化などの純ロジックは mido なしで動作する。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .keymap import note_name
from .model import NoteEvent, Score

# 和音とみなす同時刻の許容誤差（tick）
_MERGE_WINDOW_TICKS = 10

# General MIDI 音色ファミリー（program // 8）
_GM_FAMILIES = [
    "ピアノ", "クロマチック打楽器", "オルガン", "ギター",
    "ベース", "ストリングス", "アンサンブル", "ブラス",
    "リード", "パイプ", "シンセリード", "シンセパッド",
    "シンセFX", "エスニック", "パーカッシブ", "効果音",
]

# 内部イベント表現: (track, channel, tick, note)
_Event = tuple[int, int, int, int]


def is_available() -> bool:
    try:
        import mido  # noqa: F401
    except ImportError:
        return False
    return True


@dataclass
class MidiPart:
    """MIDI 内の 1 パート（トラック×チャンネル）。"""

    key: tuple[int, int]  # (track, channel) 選択のキー
    track: int
    channel: int
    name: str
    program: int | None
    note_count: int
    low: int
    high: int

    @property
    def is_drum(self) -> bool:
        return self.channel == 9

    def label(self) -> str:
        parts = [f"Track{self.track + 1}"]
        if self.name:
            parts.append(f'"{self.name}"')
        parts.append(f"ch{self.channel + 1}")
        if self.is_drum:
            parts.append("[ドラム]")
        elif self.program is not None:
            parts.append(f"[{_GM_FAMILIES[self.program // 8]}]")
        rng = f"{note_name(self.low)}–{note_name(self.high)}" if self.note_count else "-"
        return f"{' '.join(parts)}   音数 {self.note_count} / 音域 {rng}"


@dataclass
class MidiInfo:
    parts: list[MidiPart]
    tempo_bpm: float
    title: str
    ticks_per_beat: int


# --- 純ロジック（mido 不要。テスト可能） -------------------------------------
def _group_parts(events: list[_Event], names: dict[int, str], programs: dict[tuple[int, int], int]) -> list[MidiPart]:
    grouped: dict[tuple[int, int], list[int]] = {}
    for track, channel, _tick, note in events:
        grouped.setdefault((track, channel), []).append(note)
    parts: list[MidiPart] = []
    for key in sorted(grouped):
        notes = grouped[key]
        parts.append(
            MidiPart(
                key=key,
                track=key[0],
                channel=key[1],
                name=names.get(key[0], ""),
                program=programs.get(key),
                note_count=len(notes),
                low=min(notes),
                high=max(notes),
            )
        )
    return parts


def _build_from_events(
    events: list[_Event],
    ticks_per_beat: int,
    tempo_bpm: float,
    title: str,
    selected_keys: set[tuple[int, int]] | None,
    monophonic: bool,
    octave_shift: int,
    include_drums: bool,
) -> Score:
    onsets: dict[int, set[int]] = {}
    for track, channel, tick, note in events:
        if selected_keys is not None:
            if (track, channel) not in selected_keys:
                continue
        elif channel == 9 and not include_drums:
            continue
        shifted = max(0, min(127, note + 12 * octave_shift))
        onsets.setdefault(tick, set()).add(shifted)

    if not onsets:
        return Score(tempo_bpm=tempo_bpm, events=[], title=title)

    # 近接する tick を 1 グループ（和音）へ統合
    groups: list[list] = []  # [group_start_tick, set(notes)]
    for tick in sorted(onsets):
        if groups and tick - groups[-1][0] <= _MERGE_WINDOW_TICKS:
            groups[-1][1].update(onsets[tick])
        else:
            groups.append([tick, set(onsets[tick])])

    base_tick = groups[0][0]
    result: list[NoteEvent] = []
    for i, (tick, notes) in enumerate(groups):
        start_beat = (tick - base_tick) / ticks_per_beat
        if i + 1 < len(groups):
            duration = (groups[i + 1][0] - tick) / ticks_per_beat
        else:
            duration = 1.0
        if monophonic:
            notes = {max(notes)}
        result.append(
            NoteEvent(
                start_beat=start_beat,
                duration_beat=max(duration, 0.05),
                midi_notes=tuple(sorted(notes)),
            )
        )
    return Score(tempo_bpm=tempo_bpm, events=result, title=title)


# --- 実ファイル読み込み（mido 使用） -----------------------------------------
def _read(path: str) -> tuple[int, float, list[_Event], dict[int, str], dict[tuple[int, int], int]]:
    try:
        import mido
    except ImportError as exc:  # pragma: no cover - 環境依存
        raise RuntimeError(
            "MIDI 読み込みには mido が必要です。'pip install mido' を実行してください。"
        ) from exc

    midi = mido.MidiFile(path)
    ticks_per_beat = midi.ticks_per_beat or 480
    tempo_bpm = 120.0
    tempo_found = False
    events: list[_Event] = []
    names: dict[int, str] = {}
    programs: dict[tuple[int, int], int] = {}

    for track_index, track in enumerate(midi.tracks):
        abs_tick = 0
        for msg in track:
            abs_tick += msg.time
            if msg.type == "set_tempo" and not tempo_found:
                tempo_bpm = float(mido.tempo2bpm(msg.tempo))
                tempo_found = True
            elif msg.type == "track_name":
                names[track_index] = msg.name.strip()
            elif msg.type == "program_change":
                programs[(track_index, msg.channel)] = msg.program
            elif msg.type == "note_on" and msg.velocity > 0:
                events.append((track_index, msg.channel, abs_tick, msg.note))

    return ticks_per_beat, tempo_bpm, events, names, programs


def inspect_midi(path: str) -> MidiInfo:
    """MIDI の中身を解析し、パート一覧を返す。"""
    ticks_per_beat, tempo_bpm, events, names, programs = _read(path)
    parts = _group_parts(events, names, programs)
    return MidiInfo(parts=parts, tempo_bpm=tempo_bpm, title=os.path.basename(path), ticks_per_beat=ticks_per_beat)


def build_score(
    path: str,
    selected_keys: set[tuple[int, int]] | None = None,
    monophonic: bool = False,
    octave_shift: int = 0,
    include_drums: bool = False,
) -> Score:
    """選択したパートから Score を構築する。selected_keys=None なら全パート（ドラム除く）。"""
    ticks_per_beat, tempo_bpm, events, names, programs = _read(path)
    return _build_from_events(
        events, ticks_per_beat, tempo_bpm, os.path.basename(path),
        selected_keys, monophonic, octave_shift, include_drums,
    )


def parse_midi(path: str, include_drums: bool = False) -> Score:
    """後方互換: 全パートを 1 本に統合（ドラム除く）。"""
    return build_score(path, selected_keys=None, include_drums=include_drums)
