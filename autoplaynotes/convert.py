"""楽譜フォーマットの相互変換 / エクスポート。

すべて Score を中継するので、入力（テキスト/数字譜/MIDI）を Score にしてから
任意の形式へ書き出せる。
- score_to_text  : テキスト記譜（CDE）  ※ text_parser にあるものを再輸出
- score_to_numbers: 数字譜（1〜7）
- score_to_keys  : 共有用のキー文字譜（実際に押すキーの並び）
"""

from __future__ import annotations

from .keymap import KeyMapping, PITCH_CLASS
from .model import Score
from .text_parser import score_to_text  # 再輸出

__all__ = ["score_to_text", "score_to_numbers", "score_to_keys"]

# 相対半音 -> (数字, 変化記号)。#（シャープ）で表記する。
_SEMI_TO_DEGREE: dict[int, tuple[str, str]] = {
    0: ("1", ""), 1: ("1", "#"), 2: ("2", ""), 3: ("2", "#"),
    4: ("3", ""), 5: ("4", ""), 6: ("4", "#"), 7: ("5", ""),
    8: ("5", "#"), 9: ("6", ""), 10: ("6", "#"), 11: ("7", ""),
}


def _tonic_pc(name: str) -> int:
    s = name.strip()
    pc = PITCH_CLASS[s[0].upper()]
    if len(s) > 1 and s[1] in "#b":
        pc += 1 if s[1] == "#" else -1
    return pc % 12


def _fmt(value: float) -> str:
    return f"{value:g}"


def score_to_numbers(score: Score, tonic: str = "C", base_octave: int = 4, per_line: int = 8) -> str:
    """Score を数字譜（1〜7）へ変換する。"""
    tonic_pc = _tonic_pc(tonic)
    base = (base_octave + 1) * 12 + tonic_pc  # 数字「1」（無印）の高さ

    header = []
    if score.title:
        header.append(f"# title: {score.title}")
    header.append(f"# tempo: {_fmt(score.tempo_bpm)}")
    header.append(f"# key: {tonic}")
    header.append(f"# octave: {base_octave}")

    tokens: list[str] = []
    cursor = 0.0
    for event in sorted(score.events, key=lambda e: e.start_beat):
        gap = event.start_beat - cursor
        if gap > 1e-6:
            tokens.append("0" if abs(gap - 1.0) < 1e-9 else f"0:{_fmt(gap)}")
            cursor += gap
        if event.is_rest:
            continue
        parts = []
        for midi in event.midi_notes:
            st = (midi - tonic_pc) % 12
            digit, acc = _SEMI_TO_DEGREE[st]
            octave = round((midi - (base + st)) / 12)
            marks = "'" * octave if octave > 0 else "," * (-octave)
            parts.append(f"{acc}{digit}{marks}")
        token = "+".join(parts)
        if abs(event.duration_beat - 1.0) > 1e-9:
            token += f":{_fmt(event.duration_beat)}"
        tokens.append(token)
        cursor = event.start_beat + event.duration_beat

    lines = list(header)
    for i in range(0, len(tokens), per_line):
        lines.append(" ".join(tokens[i : i + per_line]))
    return "\n".join(lines) + "\n"


def _event_keys(event, mapping: KeyMapping | None) -> tuple[list[str], int]:
    keys: list[str] = []
    seen: set[str] = set()
    skipped = 0
    for midi in event.midi_notes:
        key = mapping.resolve(midi) if mapping is not None else None
        if key is None:
            skipped += 1
            continue
        if key in seen:
            continue
        seen.add(key)
        keys.append(key)
    return keys, skipped


def score_to_keys(
    score: Score,
    mapping: KeyMapping | None,
    beats_per_bar: int = 4,
    bars_per_line: int = 4,
    include_rhythm: bool = False,
) -> str:
    """Score を共有用のキー文字譜へ変換する（実際に押すキーの並び）。

    include_rhythm=True のとき、休符（_）と音の長さ（:拍）も書き出して
    リズムを再現できるようにする。
    """
    header = []
    if score.title:
        header.append(f"# {score.title}")
    if include_rhythm:
        header.append("# キー譜  [ ]=同時押し / _=休符 / :拍数 / | =小節区切り")
    else:
        header.append("# キー譜  [ ]=同時押し / | =小節区切り")
    if mapping is not None:
        header.append(f"# 割り当て: {mapping.name}")
    lines = list(header)

    if include_rhythm:
        items: list[tuple[float, str]] = []  # (拍位置, トークン)
        cursor = 0.0
        skipped = 0
        for event in sorted(score.events, key=lambda e: e.start_beat):
            gap = event.start_beat - cursor
            if gap > 1e-6:
                items.append((cursor, "_" if abs(gap - 1.0) < 1e-9 else f"_:{_fmt(gap)}"))
                cursor += gap
            if event.is_rest:
                continue
            keys, sk = _event_keys(event, mapping)
            skipped += sk
            dur = event.duration_beat
            if not keys:  # 割り当て無し → タイミング維持のため休符に
                items.append((event.start_beat, "_" if abs(dur - 1.0) < 1e-9 else f"_:{_fmt(dur)}"))
            else:
                token = keys[0] if len(keys) == 1 else "[" + "".join(keys) + "]"
                if abs(dur - 1.0) > 1e-9:
                    token += f":{_fmt(dur)}"
                items.append((event.start_beat, token))
            cursor = event.start_beat + dur

        if not items:
            lines.append("（変換できるキーがありません）")
            return "\n".join(lines) + "\n"

        out: list[str] = []
        prev_bar = -1
        for beat, token in items:
            bar = int(beat // beats_per_bar) if beats_per_bar > 0 else 0
            if bar != prev_bar and out:
                out.append("|")
            prev_bar = bar
            out.append(token)
        per_line = 16
        for i in range(0, len(out), per_line):
            lines.append(" ".join(out[i : i + per_line]))
        if skipped:
            lines.append(f"# 注: {skipped} 音は現在の割り当てにキーが無いため休符化")
        return "\n".join(lines) + "\n"

    # リズム無し（簡易・小節グループ）
    bars: dict[int, list[str]] = {}
    skipped = 0
    for event in sorted(score.events, key=lambda e: e.start_beat):
        if event.is_rest:
            continue
        keys, sk = _event_keys(event, mapping)
        skipped += sk
        if not keys:
            continue
        token = keys[0] if len(keys) == 1 else "[" + "".join(keys) + "]"
        bar = int(event.start_beat // beats_per_bar) if beats_per_bar > 0 else 0
        bars.setdefault(bar, []).append(token)

    if not bars:
        lines.append("（変換できるキーがありません）")
        return "\n".join(lines) + "\n"

    bar_strings = [" ".join(bars.get(b, ["-"])) for b in range(max(bars) + 1)]
    for i in range(0, len(bar_strings), bars_per_line):
        lines.append(" | ".join(bar_strings[i : i + bars_per_line]))
    if skipped:
        lines.append(f"# 注: {skipped} 音は現在の割り当てにキーが無いため除外")
    return "\n".join(lines) + "\n"
