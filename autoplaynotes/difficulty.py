"""難易度の階段（Difficulty Ladder）。

「弾きたいのに弾けない」を埋めるための層。譜面を弾き手のレベルまで易しくする作業は
本来は編曲であり、音楽知識を要求する。そこを自動化する。

`midi_parser` の `monophonic` は取り込み時に和音を潰して Score へ焼き付けるため、
一度減らして読み込むと原曲へ戻すには読み直すしかない。ここでは難易度を
**Score に対する可逆な変換**として表現し、練習中に段を上下できるようにする。

段0（自動演奏）だけはゲームへキーを送出する（グレー）。段1 以降は送出しない。

⚠️ **これは「メロディ抽出」ではない。**
やっているのは「**同時に押すキーの数を減らす**」ことだけ。各イベント（同時に発音する
音のまとまり）から、指定した数まで音を残す。声部を追いかけないので:

- 分散和音（アルベルティ・バス等）は各イベントが単音なので、**何も減らない**。
  減らす対象が無いのだから正しい挙動だが、「メロディだけになる」と期待してはいけない。
- 保続音の上で伴奏が動くと、保続音は発音時のイベントにしか存在しないため、以降の
  イベントでは**伴奏の最高音が残る**。旋律線は追えていない。
- 内声や左手にメロディがある編曲では、当然その音は残らない。

本当のメロディ抽出には声部分離が要る。我々の主力素材（basic-pitch の出力）には
声部が無く、skyline 法では上記のとおり壊れるため、**意図的にやっていない**。
同時押しを減らすだけでも、指の負担は確実に下がり、リズムは保たれる。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from .model import NoteEvent, Score

ChordStrategy = Literal["top", "outer"]
"""同時に鳴る音をどう間引くか。

- `top`: 高い音から残す
- `outer`: 最高音と最低音を優先し、余りは高い方から埋める（外声を残す）
"""


def thin_chord(
    midi_notes: tuple[int, ...],
    max_notes: int,
    strategy: ChordStrategy = "top",
) -> tuple[int, ...]:
    """和音を max_notes 音まで間引く。昇順のタプルを返す。

    休符（空タプル）はそのまま。重複音は 1 音として扱う。
    """
    if max_notes < 1:
        raise ValueError(f"max_notes は 1 以上である必要があります: {max_notes}")

    notes = tuple(sorted(set(midi_notes)))
    if len(notes) <= max_notes:
        return notes

    if strategy == "top":
        return notes[-max_notes:]

    # outer: メロディ（最高音）を最優先、次に根音（最低音）、余りは高い方から
    keep: set[int] = {notes[-1]}
    if max_notes >= 2:
        keep.add(notes[0])
    for note in reversed(notes[1:-1]):
        if len(keep) >= max_notes:
            break
        keep.add(note)
    return tuple(sorted(keep))


def _rebuild(event: NoteEvent, kept: tuple[int, ...]) -> NoteEvent:
    """残す音だけの NoteEvent を作る。音ごとの音長も一緒に絞り込む。

    `durations` は `midi_notes` と長さが揃っていないと NoteEvent が受け付けないので、
    音を減らすときは必ずここを通す。
    """
    if not kept:
        return replace(event, midi_notes=(), durations=(), duration_beat=event.duration_beat)
    by_note = dict(zip(event.midi_notes, event.note_durations()))
    durations = tuple(by_note[note] for note in kept)
    return replace(
        event,
        midi_notes=kept,
        durations=durations,
        duration_beat=max(durations),
    )


def thin_score(
    score: Score,
    max_notes: int,
    strategy: ChordStrategy = "top",
) -> Score:
    """全イベントの和音を間引いた新しい Score を返す（元の Score は変更しない）。"""
    events = [
        _rebuild(event, thin_chord(event.midi_notes, max_notes, strategy))
        for event in score.events
    ]
    return replace(score, events=events)


@dataclass(frozen=True)
class Level:
    """階段の 1 段。

    `max_notes` が None なら原曲どおり（間引かない）。
    `speed` は Score ではなく再生側へ渡す倍率。
    """

    index: int
    name: str
    description: str
    max_notes: int | None
    strategy: ChordStrategy = "top"
    speed: float = 1.0
    auto_play: bool = False
    """True の段だけゲームへキーを送出する（段0 のみ）。"""

    @property
    def sends_keys_to_game(self) -> bool:
        return self.auto_play


LADDER: tuple[Level, ...] = (
    Level(
        index=0,
        name="ぜんぶ自動",
        description="アプリが弾きます。まずは曲が鳴るところを見てください。",
        max_notes=None,
        auto_play=True,
    ),
    Level(
        index=1,
        name="1本指・ゆっくり",
        description="同時に押すキーは 1 つだけ（一番高い音）。半分の速さで、指の順番を覚えます。",
        max_notes=1,
        speed=0.5,
    ),
    Level(
        index=2,
        name="1本指・原速",
        description="同じ譜面を、曲の速さで。",
        max_notes=1,
    ),
    Level(
        index=3,
        name="2本指",
        description="同時に押すキーは 2 つまで（一番高い音と一番低い音）。左手が入ります。",
        max_notes=2,
        strategy="outer",
    ),
    Level(
        index=4,
        name="原曲どおり",
        description="全部の音を、あなたの指で。",
        max_notes=None,
    ),
)


def level_at(index: int) -> Level:
    """段番号から Level を得る。範囲外は ValueError。"""
    for level in LADDER:
        if level.index == index:
            return level
    raise ValueError(f"存在しない段です: {index}")


def apply_level(score: Score, level: Level) -> Score:
    """その段で「あなたが弾く譜面」を返す。速度倍率は含まない（再生側の責務）。"""
    if level.max_notes is None:
        return replace(score, events=list(score.events))
    return thin_score(score, level.max_notes, level.strategy)
