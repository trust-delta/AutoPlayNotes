"""MIDI ファイルの読み込み（トラック/チャンネル選択対応）。

1 つの MIDI は複数パート（メロディ・伴奏・ベース・ドラム等）に分かれている。
- inspect_midi(): パート一覧（トラック×チャンネル）と各パートの音数・音域を返す
- build_score(): 選択したパートだけを 1 本の時間軸へ統合して Score を作る
    - monophonic: 各時点で最高音のみ残す（同時押しを減らすだけ。声部は追わないので
      メロディ抽出ではない。分散和音では何も減らず、保続音の下では伴奏の最高音が残る）
    - octave_shift: 全体をオクターブ単位で移調

音長は note_on/note_off の対から取る（「次の発音まで」ではない）。対象のゲーム内楽器は
キーを押している間だけ鳴るため、音長は演奏の質そのものになる。休符は音長を伸ばして
埋めるのではなく、イベント間のギャップとして表現する（書き出し側が休符へ変換する）。

鳴っている同音を再発音した場合は、先行音をその時点で閉じる（後勝ち）。物理キーは状態を
1 つしか持てないので、同じキーの重なりは表現できない。

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

# 音長の下限（拍）。tick 上で長さ 0 の音を潰さないための保険。
_MIN_DURATION_BEATS = 0.05

# General MIDI 音色ファミリー（program // 8）
_GM_FAMILIES = [
    "ピアノ", "クロマチック打楽器", "オルガン", "ギター",
    "ベース", "ストリングス", "アンサンブル", "ブラス",
    "リード", "パイプ", "シンセリード", "シンセパッド",
    "シンセFX", "エスニック", "パーカッシブ", "効果音",
]

# 内部イベント表現: (track, channel, start_tick, note, end_tick)
_Event = tuple[int, int, int, int, int]


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
    for track, channel, _tick, note, _end in events:
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
    # tick -> {音: 終了 tick}。同 tick に同じ音が重なったら長い方を採る。
    onsets: dict[int, dict[int, int]] = {}
    for track, channel, tick, note, end in events:
        if selected_keys is not None:
            if (track, channel) not in selected_keys:
                continue
        elif channel == 9 and not include_drums:
            continue
        shifted = max(0, min(127, note + 12 * octave_shift))
        slot = onsets.setdefault(tick, {})
        if end > slot.get(shifted, -1):
            slot[shifted] = end

    if not onsets:
        return Score(tempo_bpm=tempo_bpm, events=[], title=title)

    # 近接する tick を 1 グループ（和音）へ統合
    groups: list[list] = []  # [group_start_tick, {note: end_tick}]
    for tick in sorted(onsets):
        if groups and tick - groups[-1][0] <= _MERGE_WINDOW_TICKS:
            merged: dict[int, int] = groups[-1][1]
            for note, end in onsets[tick].items():
                if end > merged.get(note, -1):
                    merged[note] = end
        else:
            groups.append([tick, dict(onsets[tick])])

    base_tick = groups[0][0]
    result: list[NoteEvent] = []
    for tick, notes in groups:
        start_beat = (tick - base_tick) / ticks_per_beat
        if monophonic:
            top = max(notes)
            notes = {top: notes[top]}
        midis = tuple(sorted(notes))
        # 音長はグループの開始からその音の終了まで（note_off 由来の実音長）
        durations = tuple(
            max((notes[note] - tick) / ticks_per_beat, _MIN_DURATION_BEATS)
            for note in midis
        )
        result.append(
            NoteEvent(
                start_beat=start_beat,
                duration_beat=max(durations),
                midi_notes=midis,
                durations=durations,
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
        # (channel, note) -> 発音した tick。note_off が来るまで開いたまま。
        open_notes: dict[tuple[int, int], int] = {}
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
                key = (msg.channel, msg.note)
                # 鳴っている同音を再発音した場合は、ここで先行音を閉じる（後勝ち）
                start = open_notes.pop(key, None)
                if start is not None:
                    events.append((track_index, key[0], start, key[1], abs_tick))
                open_notes[key] = abs_tick
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                key = (msg.channel, msg.note)
                start = open_notes.pop(key, None)
                if start is not None:
                    events.append((track_index, key[0], start, key[1], abs_tick))

        # note_off が来ないまま終わった音は、トラック終端で閉じる
        for (channel, note), start in open_notes.items():
            events.append((track_index, channel, start, note, abs_tick))

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
