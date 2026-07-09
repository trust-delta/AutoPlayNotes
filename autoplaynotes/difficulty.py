"""難易度の調整＝「同時に押すキーの数」を減らすこと。

「弾きたいのに弾けない」を埋めるための層。譜面を弾き手のレベルまで易しくする作業は
本来は編曲であり、音楽知識を要求する。そこを自動化する。

**難易度の軸はひとつだけ。同時に押すキーの数。**
速度（`PlaybackOptions.speed` / 練習モードの速度倍率）と、時間の進め方（リズム / ステップ）は
別の軸として既に実装済みで、ここでは扱わない。「誰が弾くか」（自動演奏 / 自分）も別の軸。

数えるのは**音の数ではなくキーの数**。`KeyMapping.resolve()` は音域外をオクターブ移調で
畳むため多対一で、C3 と C5 が同じキーに落ちることがある。2 音でも指は 1 本。だから
マッピングを渡すとキー空間で、渡さなければ音高空間で数える。

`midi_parser` の `monophonic` は取り込み時に和音を潰して Score へ焼き付けるため、
一度減らして読み込むと原曲へ戻すには読み直すしかない。ここでは
**Score に対する可逆な変換**として表現し、練習中に難易度を上下できるようにする。

⚠️ **これは「メロディ抽出」ではない。**
同時に鳴る音のまとまりから、指定した数まで残すだけ。声部を追いかけないので:

- 分散和音（アルベルティ・バス等）は各イベントが単音なので、**何も減らない**。
  減らす対象が無いのだから正しい挙動だが、「メロディだけになる」と期待してはいけない。
- 保続音の上で伴奏が動くと、保続音は発音時のイベントにしか存在しないため、以降の
  イベントでは**伴奏の最高音が残る**。旋律線は追えていない。
- 内声や左手にメロディがある編曲では、当然その音は残らない。

本当のメロディ抽出には声部分離が要る。我々の主力素材（basic-pitch の出力）には
声部が無く、skyline 法では上記のとおり壊れるため、**意図的にやっていない**。
同時押しを減らすだけでも指の負担は確実に下がり、リズムは保たれる。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from .keymap import KeyMapping
from .model import NoteEvent, Score

ChordStrategy = Literal["outer", "top"]
"""同時に鳴る音のうち、どれを残すか。

- `outer`: 最高音と最低音を優先し、余りは高い方から埋める（旋律と低音を残す・既定）
- `top`: 高い音から順に残す
"""

FULL: None = None
"""難易度の上限。間引かない＝原曲どおり。"""


def _priority(notes: tuple[int, ...], strategy: ChordStrategy) -> list[int]:
    """残す優先順に並べ替える。"""
    if strategy == "top":
        return list(reversed(notes))
    # outer: 最高音 → 最低音 → 残りを高い方から
    if len(notes) <= 2:
        return list(reversed(notes))
    return [notes[-1], notes[0], *reversed(notes[1:-1])]


def _key_of(midi: int, mapping: KeyMapping | None) -> object:
    """その音が落ちるキー。マッピングが無ければ音高そのものをキーとみなす。"""
    return midi if mapping is None else mapping.resolve(midi)


def thin_chord(
    midi_notes: tuple[int, ...],
    max_keys: int,
    strategy: ChordStrategy = "outer",
    mapping: KeyMapping | None = None,
) -> tuple[int, ...]:
    """同時に押すキーが max_keys 個までになるよう音を間引く。昇順のタプルを返す。

    同じキーに落ちる音は何個あっても指 1 本なので、まとめて残す。
    どのキーにも割り当たらない音（`out_of_range="skip"`）は鳴らないため
    キーを消費しない。そのまま残す（難易度を上限にしたとき原曲へ戻るように）。
    """
    if max_keys < 1:
        raise ValueError(f"max_keys は 1 以上である必要があります: {max_keys}")

    notes = tuple(sorted(set(midi_notes)))
    if not notes:
        return ()

    kept: list[int] = []
    keys: set[object] = set()
    for note in _priority(notes, strategy):
        key = _key_of(note, mapping)
        if key is None:  # 鳴らない音は指を使わない
            kept.append(note)
        elif key in keys or len(keys) < max_keys:
            keys.add(key)
            kept.append(note)
    return tuple(sorted(kept))


def _rebuild(event: NoteEvent, kept: tuple[int, ...]) -> NoteEvent:
    """残す音だけの NoteEvent を作る。音ごとの音長も一緒に絞り込む。

    `durations` は `midi_notes` と長さが揃っていないと NoteEvent が受け付けないので、
    音を減らすときは必ずここを通す。
    """
    if not kept:
        return replace(event, midi_notes=(), durations=(), duration_beat=event.duration_beat)
    by_note = dict(zip(event.midi_notes, event.note_durations()))
    durations = tuple(by_note[note] for note in kept)
    return replace(event, midi_notes=kept, durations=durations, duration_beat=max(durations))


def thin_score(
    score: Score,
    max_keys: int,
    strategy: ChordStrategy = "outer",
    mapping: KeyMapping | None = None,
) -> Score:
    """全イベントを max_keys キーまで間引いた新しい Score を返す（元は変更しない）。"""
    events = [
        _rebuild(event, thin_chord(event.midi_notes, max_keys, strategy, mapping))
        for event in score.events
    ]
    return replace(score, events=events)


def apply(
    score: Score,
    max_keys: int | None,
    strategy: ChordStrategy = "outer",
    mapping: KeyMapping | None = None,
) -> Score:
    """難易度を適用する。`max_keys=FULL`（None）なら原曲どおり。"""
    if max_keys is None:
        return replace(score, events=list(score.events))
    return thin_score(score, max_keys, strategy, mapping)


def keys_at_once(event: NoteEvent, mapping: KeyMapping | None = None) -> int:
    """そのイベントで同時に押すキーの数。"""
    keys = {_key_of(note, mapping) for note in event.midi_notes}
    keys.discard(None)  # 鳴らない音は指を使わない
    return len(keys)


def max_simultaneous(score: Score, mapping: KeyMapping | None = None) -> int:
    """この曲で一度に押す必要のある最大キー数。難易度の上限。"""
    if not score.events:
        return 0
    return max(keys_at_once(event, mapping) for event in score.events)


def levels_for(score: Score, mapping: KeyMapping | None = None) -> tuple[int, ...]:
    """この曲で意味のある難易度の一覧（1 から、原曲に必要な最大キー数まで）。

    上限を選べば原曲どおり。単音の曲なら (1,) だけで、下げようがない。
    """
    top = max_simultaneous(score, mapping)
    return tuple(range(1, top + 1)) if top >= 1 else ()


def describe(max_keys: int | None) -> str:
    if max_keys is None:
        return "原曲どおり"
    if max_keys == 1:
        return "同時押し 1 キー（指 1 本）"
    return f"同時押し {max_keys} キーまで"
