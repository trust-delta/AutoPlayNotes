"""難易度＝「あなたが自分で弾くキーの範囲（窓）」。

「弾きたいのに弾けない」を埋めるための層。譜面を弾き手のレベルまで易しくする作業は
本来は編曲であり、音楽知識を要求する。そこを自動化する。

**難易度の軸はひとつ。あなたが担当するキーの窓をどこに、どれだけ広く取るか。**
窓の外の音はアプリが受け持つ（ゲームへ送出 / スピーカーで鳴らす / 鳴らさない）。
速度も、時間の進み方（リズム / ステップ）も、別の軸として既に実装済みで、ここでは扱わない。

窓が同時押しの上限も決める。幅 8 鍵の窓なら指は最大 8 本、1 鍵なら必ず 1 本。
ただし窓は「メロディ全部を 1 音ずつ」を表現できない。8 鍵の中に和音があれば和音を弾く。
**だから窓を選ぶ前に、その窓で何本指が要るかを見せなければならない**（`fingers_needed`）。

窓で分ける最大の理由は技術的なものでもある。**あなたのキー集合とアプリのキー集合が
全曲を通じて素になる**ため、両者が同じ物理キーを取り合わない。同時押し数で分けると、
役割が時間をまたいで入れ替わり、アプリの keyup があなたの音を切る。

⚠️ 窓は**キー**の範囲であって、原曲の音域ではない。`KeyMapping.resolve()` は音域外を
オクターブ移調で畳むため、遠く離れた音が窓の中へ落ちてくることがある。可視化が
見せるのは畳んだ後のキーなので、そこに嘘は無い。

⚠️ 音楽の 1 オクターブは「ド〜ド」の 8 鍵だが、MIDI のオクターブ番号は C4〜B4 で切れる。
窓を**オクターブ番号**で定義すると「ドレミファソラシ**ド**」の最後の音が窓から外れる。
だから窓は**連続したキー範囲**で定義する。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

from .keymap import KeyMapping
from .model import NoteEvent, Score

KeySet = frozenset[str]


# --- キーボードの並び ---------------------------------------------------------
def key_pitches(mapping: KeyMapping) -> dict[str, int]:
    """キー -> そのキーが鳴らす音高。同じキーに複数の音が割り当たっていれば最低音。"""
    pitches: dict[str, int] = {}
    for midi, key in mapping.note_to_key.items():
        if key not in pitches or midi < pitches[key]:
            pitches[key] = midi
    return pitches


def keyboard(mapping: KeyMapping) -> list[tuple[str, int]]:
    """(キー, 音高) を低い方から。可視化と窓の指定はこの並びで行う。"""
    return sorted(key_pitches(mapping).items(), key=lambda item: item[1])


def keys_between(mapping: KeyMapping, lo: int, hi: int) -> KeySet:
    """音高 lo〜hi（両端を含む）に対応するキーの集合＝窓。"""
    return frozenset(k for k, p in key_pitches(mapping).items() if lo <= p <= hi)


def full_window(mapping: KeyMapping) -> KeySet:
    """全鍵。あなたが原曲をそのまま弾く。"""
    return frozenset(mapping.note_to_key.values())


# --- 譜面をあなたとアプリに分ける ---------------------------------------------
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


def split(
    score: Score, mapping: KeyMapping, yours: KeySet
) -> tuple[Score, Score]:
    """(あなたが弾く譜面, アプリが受け持つ譜面) に分ける。

    どのキーにも割り当たらない音（`out_of_range="skip"`）は誰にも弾けない。
    2 つを合わせれば必ず原曲に戻るよう、アプリ側へ寄せる。
    """
    mine: list[NoteEvent] = []
    theirs: list[NoteEvent] = []
    for event in score.events:
        kept = tuple(n for n in event.midi_notes if mapping.resolve(n) in yours)
        dropped = tuple(n for n in event.midi_notes if mapping.resolve(n) not in yours)
        mine.append(_rebuild(event, kept))
        theirs.append(_rebuild(event, dropped))
    return replace(score, events=mine), replace(score, events=theirs)


def apply(score: Score, mapping: KeyMapping, yours: KeySet) -> Score:
    """あなたが弾く譜面だけを返す。"""
    return split(score, mapping, yours)[0]


# --- 窓を選ぶための材料（可視化が使う） ---------------------------------------
def keys_at_once(
    event: NoteEvent, mapping: KeyMapping, within: KeySet | None = None
) -> int:
    """そのイベントで同時に押すキーの数。`within` を渡すとその窓の中だけ数える。

    オクターブ移調で同じキーへ畳まれた音は、何個あっても指 1 本。
    """
    keys = {mapping.resolve(note) for note in event.midi_notes}
    keys.discard(None)
    if within is not None:
        keys &= set(within)
    return len(keys)


def fingers_needed(
    score: Score, mapping: KeyMapping, within: KeySet | None = None
) -> int:
    """その窓を選んだとき、同時に押す必要のある最大キー数。**選ぶ前に見せる値。**"""
    if not score.events:
        return 0
    return max(keys_at_once(event, mapping, within) for event in score.events)


def key_usage(score: Score, mapping: KeyMapping) -> dict[str, int]:
    """キーごとの発音回数。可視化のヒストグラム。窓をどこへ置くかの手がかり。"""
    counts: dict[str, int] = {}
    for event in score.events:
        for note in event.midi_notes:
            key = mapping.resolve(note)
            if key is not None:
                counts[key] = counts.get(key, 0) + 1
    return counts


def keys_used(score: Score, mapping: KeyMapping) -> KeySet:
    """その曲が実際に使うキー。"""
    return frozenset(key_usage(score, mapping))


def note_share(score: Score, mapping: KeyMapping, yours: KeySet) -> tuple[int, int]:
    """(あなたが弾く音数, 曲全体の音数)。窓の広さの実感。"""
    total = sum(len(event.midi_notes) for event in score.events)
    mine = sum(
        1
        for event in score.events
        for note in event.midi_notes
        if mapping.resolve(note) in yours
    )
    return mine, total


# --- 同時押しの間引き（難易度の軸ではない・任意の補助） -----------------------
ChordStrategy = Literal["outer", "top"]
"""同時に鳴る音のうち、どれを残すか。

- `outer`: 最高音と最低音を優先し、余りは高い方から埋める
- `top`: 高い音から順に残す
"""


def _priority(notes: tuple[int, ...], strategy: ChordStrategy) -> list[int]:
    if strategy == "top" or len(notes) <= 2:
        return list(reversed(notes))
    return [notes[-1], notes[0], *reversed(notes[1:-1])]


def thin_chord(
    midi_notes: tuple[int, ...],
    max_keys: int,
    strategy: ChordStrategy = "outer",
    mapping: KeyMapping | None = None,
) -> tuple[int, ...]:
    """同時に押すキーが max_keys 個までになるよう音を間引く。

    ⚠️ **難易度の軸ではない。** 難易度は窓（`split`）で決める。これはその上に重ねられる
    任意の補助で、「窓の中に和音があるが、まだ 1 本指で弾きたい」ときにだけ使う。
    声部は追わないので、これで「メロディだけ」にはならない（`tests/test_difficulty.py` 参照）。
    """
    if max_keys < 1:
        raise ValueError(f"max_keys は 1 以上である必要があります: {max_keys}")

    notes = tuple(sorted(set(midi_notes)))
    if not notes:
        return ()

    kept: list[int] = []
    keys: set[object] = set()
    for note in _priority(notes, strategy):
        key = note if mapping is None else mapping.resolve(note)
        if key is None:  # 鳴らない音は指を使わない
            kept.append(note)
        elif key in keys or len(keys) < max_keys:
            keys.add(key)
            kept.append(note)
    return tuple(sorted(kept))


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
