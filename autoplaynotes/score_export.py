"""Score を MIDI / MusicXML へ書き出す（相互運用用・追加依存なし）。

- score_to_midi_bytes: 標準 MIDI ファイル（SMF type 0）を純 Python で生成
- score_to_musicxml : MusicXML（score-partwise）を純 Python で生成

MuseScore / Sibelius / Dorico など他ツールへ持ち出すための書き出し。
小節をまたぐ音符は小節線で切り詰める簡易実装（発音タイミングは保つ）。
"""

from __future__ import annotations

import struct
from xml.sax.saxutils import escape

from .model import Score

_TPQ = 480  # MIDI の 4 分音符あたりの tick
_VELOCITY = 80

# ピッチクラス -> (音名, 変化記号 alter)。# 表記。
_PC_TO_PITCH: list[tuple[str, int]] = [
    ("C", 0), ("C", 1), ("D", 0), ("D", 1), ("E", 0), ("F", 0),
    ("F", 1), ("G", 0), ("G", 1), ("A", 0), ("A", 1), ("B", 0),
]


def _vlq(value: int) -> bytes:
    """MIDI の可変長数量（delta time）。"""
    if value < 0:
        value = 0
    out = bytearray([value & 0x7F])
    value >>= 7
    while value:
        out.insert(0, (value & 0x7F) | 0x80)
        value >>= 7
    return bytes(out)


def score_to_midi_bytes(score: Score, bpm: float | None = None) -> bytes:
    """Score を SMF type 0 のバイト列に変換する。"""
    tempo = bpm if bpm and bpm > 0 else (score.tempo_bpm or 120.0)

    # (tick, order, status, midi, velocity) を集める。order: note_off=0 を先に。
    raw: list[tuple[int, int, int, int, int]] = []
    for event in score.events:
        if event.is_rest:
            continue
        on = round(event.start_beat * _TPQ)
        # 和音の中でも音長は揃わないので、音ごとに note_off を打つ
        for midi, dur in zip(event.midi_notes, event.note_durations()):
            off = max(on + 1, round((event.start_beat + dur) * _TPQ))
            m = max(0, min(127, midi))
            raw.append((on, 1, 0x90, m, _VELOCITY))
            raw.append((off, 0, 0x80, m, 0))
    raw.sort(key=lambda e: (e[0], e[1]))

    track = bytearray()
    # テンポ meta（マイクロ秒/4分音符）
    mpq = int(round(60_000_000 / tempo))
    track += _vlq(0) + b"\xff\x51\x03" + struct.pack(">I", mpq)[1:]

    prev = 0
    for tick, _order, status, midi, vel in raw:
        track += _vlq(tick - prev) + bytes([status, midi, vel])
        prev = tick
    track += _vlq(0) + b"\xff\x2f\x00"  # end of track

    header = b"MThd" + struct.pack(">IHHH", 6, 0, 1, _TPQ)
    chunk = b"MTrk" + struct.pack(">I", len(track)) + bytes(track)
    return header + chunk


def _midi_to_pitch(midi: int) -> tuple[str, int, int]:
    """MIDI -> (音名, alter, オクターブ)。C4=60 -> ("C",0,4)。"""
    step, alter = _PC_TO_PITCH[midi % 12]
    octave = midi // 12 - 1
    return step, alter, octave


def _note_type(dur_beats: float) -> str:
    if dur_beats >= 4:
        return "whole"
    if dur_beats >= 2:
        return "half"
    if dur_beats >= 1:
        return "quarter"
    if dur_beats >= 0.5:
        return "eighth"
    if dur_beats >= 0.25:
        return "16th"
    return "32nd"


def _note_xml(midi: int, dur_div: int, dur_beats: float, chord: bool) -> list[str]:
    step, alter, octave = _midi_to_pitch(midi)
    lines = ["      <note>"]
    if chord:
        lines.append("        <chord/>")
    lines.append("        <pitch>")
    lines.append(f"          <step>{step}</step>")
    if alter:
        lines.append(f"          <alter>{alter}</alter>")
    lines.append(f"          <octave>{octave}</octave>")
    lines.append("        </pitch>")
    lines.append(f"        <duration>{dur_div}</duration>")
    lines.append("        <voice>1</voice>")
    lines.append(f"        <type>{_note_type(dur_beats)}</type>")
    lines.append("      </note>")
    return lines


def _rest_xml(dur_div: int) -> list[str]:
    return [
        "      <note>",
        "        <rest/>",
        f"        <duration>{dur_div}</duration>",
        "        <voice>1</voice>",
        "      </note>",
    ]


def score_to_musicxml(score: Score, beats_per_bar: int = 4) -> str:
    """Score を MusicXML（score-partwise）文字列へ変換する。"""
    div = _TPQ
    eps = 1e-6
    events = [e for e in sorted(score.events, key=lambda e: e.start_beat) if not e.is_rest]
    total_beats = max(score.total_beats(), float(beats_per_bar))
    n_measures = max(1, int(-(-total_beats // beats_per_bar)))  # 切り上げ
    title = escape(score.title or "AutoPlayNotes")

    out: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" '
        '"http://www.musicxml.org/dtds/partwise.dtd">',
        '<score-partwise version="3.1">',
        "  <work>",
        f"    <work-title>{title}</work-title>",
        "  </work>",
        "  <part-list>",
        '    <score-part id="P1">',
        "      <part-name>Music</part-name>",
        "    </score-part>",
        "  </part-list>",
        '  <part id="P1">',
    ]

    idx = 0
    for m in range(n_measures):
        m_start = m * beats_per_bar
        m_end = m_start + beats_per_bar
        out.append(f'    <measure number="{m + 1}">')
        if m == 0:
            out += [
                "      <attributes>",
                f"        <divisions>{div}</divisions>",
                "        <key><fifths>0</fifths></key>",
                f"        <time><beats>{beats_per_bar}</beats><beat-type>4</beat-type></time>",
                "        <clef><sign>G</sign><line>2</line></clef>",
                "      </attributes>",
            ]
        cursor = float(m_start)
        while idx < len(events) and events[idx].start_beat < m_end - eps:
            ev = events[idx]
            gap = ev.start_beat - cursor
            if gap > eps:
                out += _rest_xml(round(gap * div))
                cursor += gap
            dur_beats = min(ev.duration_beat, m_end - ev.start_beat)
            if dur_beats <= eps:
                dur_beats = m_end - ev.start_beat
            dur_div = max(1, round(dur_beats * div))
            for i, midi in enumerate(ev.midi_notes):
                out += _note_xml(midi, dur_div, dur_beats, chord=(i > 0))
            cursor = ev.start_beat + dur_beats
            idx += 1
        tail = m_end - cursor
        if tail > eps:
            out += _rest_xml(round(tail * div))
        out.append("    </measure>")

    out.append("  </part>")
    out.append("</score-partwise>")
    return "\n".join(out) + "\n"
