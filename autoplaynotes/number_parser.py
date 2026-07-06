"""数字譜（簡易譜 / ジャンプ式）のパーサ。

キーボード演奏系アプリでは 1〜7 の数字で音を表す「数字譜」が広く使われるため、
コミュニティ配布の数字譜をほぼそのまま貼り付けて演奏できるようにする。

書式:
  # tempo: 120        … BPM
  # key: C            … 主音（movable do。1 がこの音になる。既定 C）
  # octave: 4         … 数字 1（無印）が属するオクターブ
  ---- 本文 ----
  1 2 3 4 5 6 7       … ドレミファソラシ（既定 C なら C D E F G A B）
  1'                  … 高いオクターブ（' を重ねるほど上、例 1'' で 2 オクターブ上）
  1,                  … 低いオクターブ（, を重ねるほど下）
  #1  b3              … 半音上げ / 下げ
  1:2                 … 拍数指定（2 拍）
  1+3+5              … 和音
  -                   … 直前の音を伸ばす
  0                   … 休符
  |                   … 小節線（無視）
"""

from __future__ import annotations

import re

from .keymap import PITCH_CLASS
from .model import NoteEvent, Score

_MAJOR = [0, 2, 4, 5, 7, 9, 11]  # 1234567 -> 半音
_HEADER = re.compile(r"^#\s*(\w+)\s*:\s*(.+)$")


def _tonic_pc(name: str) -> int:
    s = name.strip()
    if not s or s[0].upper() not in PITCH_CLASS:
        raise ValueError(f"主音を認識できません: '{name}'")
    pc = PITCH_CLASS[s[0].upper()]
    if len(s) > 1 and s[1] in "#b":
        pc += 1 if s[1] == "#" else -1
    return pc % 12


def _degree_to_midi(token: str, tonic_pc: int, base_octave: int) -> int:
    s = token
    accidental = 0
    if s and s[0] in "#b":
        accidental = 1 if s[0] == "#" else -1
        s = s[1:]
    if not s or s[0] not in "1234567":
        raise ValueError(f"数字譜として解釈できません: '{token}'")
    degree = int(s[0])
    s = s[1:]
    octave_shift = 0
    for ch in s:
        if ch == "'":
            octave_shift += 1
        elif ch == ",":
            octave_shift -= 1
        else:
            raise ValueError(f"数字譜の記号を認識できません: '{token}' の '{ch}'")
    semitone = _MAJOR[degree - 1] + accidental
    return (base_octave + 1) * 12 + tonic_pc + semitone + 12 * octave_shift


def parse_numbers(
    text: str,
    default_tempo: float = 120.0,
    default_octave: int = 4,
    default_key: str = "C",
    default_duration: float = 1.0,
) -> Score:
    tempo = default_tempo
    octave = default_octave
    tonic_pc = _tonic_pc(default_key)
    title = ""

    body_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # 数字譜では '#' はシャープ（例 #1）にも使うため、
        # ヘッダ／コメントは "# "（# のあとに空白）で始まる行に限定する。
        if stripped.startswith("# "):
            m = _HEADER.match(stripped)
            if m:
                key = m.group(1).lower()
                value = m.group(2).strip()
                if key == "tempo":
                    tempo = float(value)
                elif key == "octave":
                    octave = int(value)
                elif key == "key":
                    tonic_pc = _tonic_pc(value)
                elif key == "title":
                    title = value
            continue
        body_lines.append(stripped)

    events: list[NoteEvent] = []
    cursor = 0.0
    last_event: NoteEvent | None = None

    for line in body_lines:
        for token in line.split():
            if token == "|":
                continue

            spec = token
            duration = default_duration
            if ":" in token:
                spec, dur_str = token.split(":", 1)
                try:
                    duration = float(dur_str)
                except ValueError as exc:
                    raise ValueError(f"拍数を解釈できません: '{token}'") from exc
                if duration <= 0:
                    raise ValueError(f"拍数は正の数にしてください: '{token}'")

            if spec == "-":
                if last_event is not None:
                    last_event.duration_beat += duration
                cursor += duration
                continue

            if spec in ("0", "R", "r", "_"):
                cursor += duration
                last_event = None
                continue

            notes = tuple(
                _degree_to_midi(p, tonic_pc, octave) for p in spec.split("+") if p
            )
            if not notes:
                raise ValueError(f"音を解釈できません: '{token}'")
            event = NoteEvent(start_beat=cursor, duration_beat=duration, midi_notes=notes)
            events.append(event)
            last_event = event
            cursor += duration

    return Score(tempo_bpm=tempo, events=events, title=title)
