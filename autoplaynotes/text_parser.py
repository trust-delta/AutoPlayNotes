"""自作テキスト記譜のパーサ。

書式（例は README.md 参照）:
  # tempo: 120        … BPM 指定（ヘッダ）
  # octave: 4         … 既定オクターブ
  # title: 曲名        … タイトル
  ---- 本文 ----
  C  D  E  F           … 1 トークン = 1 音（既定で 1 拍）
  C:2                  … 「:数値」で拍数を指定（2 拍）
  C+E+G                … 「+」で和音
  C+E+G:2              … 和音 + 拍数
  -                    … 直前の音を伸ばす（タイ / 拍を進める）
  R / r / 0 / _        … 休符
  |                    … 小節線（無視・見やすさ用）
"""

from __future__ import annotations

import re

from .keymap import name_to_midi, note_name
from .model import NoteEvent, Score, sequential_durations

_HEADER = re.compile(r"^#\s*(\w+)\s*:\s*(.+)$")


def parse_text(
    text: str,
    default_tempo: float = 120.0,
    default_octave: int = 4,
    default_duration: float = 1.0,
) -> Score:
    tempo = default_tempo
    octave = default_octave
    title = ""

    body_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            m = _HEADER.match(stripped)
            if m:
                key = m.group(1).lower()
                value = m.group(2).strip()
                if key == "tempo":
                    tempo = float(value)
                elif key == "octave":
                    octave = int(value)
                elif key == "title":
                    title = value
            # ヘッダに合致しない '#' 行は単なるコメントとして無視
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

            if spec in ("R", "r", "0", "_"):
                cursor += duration
                last_event = None
                continue

            notes = tuple(name_to_midi(p, octave) for p in spec.split("+") if p)
            if not notes:
                raise ValueError(f"音を解釈できません: '{token}'")
            event = NoteEvent(start_beat=cursor, duration_beat=duration, midi_notes=notes)
            events.append(event)
            last_event = event
            cursor += duration

    return Score(tempo_bpm=tempo, events=events, title=title)


def _fmt(value: float) -> str:
    """末尾の 0 を落として数値を文字列化（2.0 -> '2', 0.5 -> '0.5'）。"""
    return f"{value:g}"


def score_to_text(score: Score, per_line: int = 8) -> str:
    """Score をテキスト記譜（CDE 形式）へ変換する。

    音と音の間に空きがあれば休符 R を挿入して発音タイミングを保つ。
    五線譜エディタの編集結果をテキスト欄へ戻すために使う。
    """
    header: list[str] = []
    if score.title:
        header.append(f"# title: {score.title}")
    header.append(f"# tempo: {_fmt(score.tempo_bpm)}")

    tokens: list[str] = []
    cursor = 0.0
    # 重なった音（複声部由来など）は次の音の開始で切り詰め、発音タイミングを保つ
    for event, duration in sequential_durations(score.events):
        gap = event.start_beat - cursor
        if gap > 1e-6:
            tokens.append("R" if abs(gap - 1.0) < 1e-9 else f"R:{_fmt(gap)}")
            cursor += gap
        if event.is_rest:
            continue
        names = "+".join(note_name(n) for n in event.midi_notes)
        if abs(duration - 1.0) > 1e-9:
            names += f":{_fmt(duration)}"
        tokens.append(names)
        cursor = event.start_beat + duration

    lines = list(header)
    for i in range(0, len(tokens), per_line):
        lines.append(" ".join(tokens[i : i + per_line]))
    return "\n".join(lines) + "\n"
