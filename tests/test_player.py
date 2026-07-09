"""player.build_actions の音長・キー衝突の解決に関するテスト。

対象のゲーム内楽器は「キーを押している間だけ鳴り、押下エッジでしか発音しない」。
したがって音長はそのまま演奏の質になり、同じキーの重なりは離してから押し直すしかない。
従来この層にはテストが無く、音長を 40ms で潰していたことに誰も気づけなかった。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoplaynotes.keymap import KeyMapping  # noqa: E402
from autoplaynotes.model import NoteEvent, Score  # noqa: E402
from autoplaynotes.player import PlaybackOptions, Player  # noqa: E402
from autoplaynotes.win_input import high_resolution_timer  # noqa: E402


class _FakeSender:
    """build_actions はキー送出をしないので、中身は不要。"""


def _mapping(sustain: bool = True) -> KeyMapping:
    # 音域は C4..E4 のみ。範囲外はオクターブ移調で畳まれる（多対一になる）。
    return KeyMapping(
        name="test",
        note_to_key={60: "a", 62: "s", 64: "d"},
        out_of_range="transpose",
        sustain=sustain,
    )


def _actions(score: Score, mapping: KeyMapping, **opts: object) -> list:
    player = Player(_FakeSender())  # type: ignore[arg-type]
    params: dict[str, object] = {"gate_ms": 40.0, "retrigger_gap_ms": 10.0}
    params.update(opts)
    actions, _skipped = player.build_actions(score, mapping, PlaybackOptions(**params))  # type: ignore[arg-type]
    return actions


def _spans(actions: list) -> dict[str, list[tuple[float, float]]]:
    """キーごとの (押下時刻, 解放時刻) を集める。"""
    open_at: dict[str, float] = {}
    spans: dict[str, list[tuple[float, float]]] = {}
    for a in actions:
        key = a.keys[0]
        if a.is_down:
            open_at[key] = a.at
        else:
            spans.setdefault(key, []).append((open_at.pop(key), a.at))
    assert not open_at, f"解放されていないキー: {open_at}"
    return spans


def _score(*events: NoteEvent) -> Score:
    # BPM 60 → 1 拍 = 1 秒。秒と拍が一致するので読みやすい。
    return Score(tempo_bpm=60.0, events=list(events))


class SustainTest(unittest.TestCase):
    def test_key_is_held_for_the_note_length(self) -> None:
        actions = _actions(_score(NoteEvent(0.0, 2.0, (60,), (2.0,))), _mapping())
        self.assertEqual(_spans(actions)["a"], [(0.0, 2.0)])

    def test_long_note_is_not_capped_at_gate(self) -> None:
        """従来は gate(40ms) が上限で、全音符もスタッカートになっていた。"""
        actions = _actions(_score(NoteEvent(0.0, 4.0, (60,), (4.0,))), _mapping())
        onset, release = _spans(actions)["a"][0]
        self.assertAlmostEqual(release - onset, 4.0)

    def test_non_sustaining_instrument_taps(self) -> None:
        """撥弦楽器は押した瞬間に鳴って減衰するので、音長ぶん押し続けない。"""
        actions = _actions(_score(NoteEvent(0.0, 4.0, (60,), (4.0,))), _mapping(sustain=False))
        onset, release = _spans(actions)["a"][0]
        self.assertAlmostEqual(release - onset, 0.040)

    def test_short_note_gets_minimum_hold(self) -> None:
        actions = _actions(_score(NoteEvent(0.0, 0.001, (60,), (0.001,))), _mapping())
        onset, release = _spans(actions)["a"][0]
        self.assertAlmostEqual(release - onset, 0.040)


class ChordDurationTest(unittest.TestCase):
    def test_chord_notes_are_held_individually(self) -> None:
        actions = _actions(_score(NoteEvent(0.0, 2.0, (60, 62), (2.0, 0.5))), _mapping())
        spans = _spans(actions)
        self.assertEqual(spans["a"], [(0.0, 2.0)])
        self.assertEqual(spans["s"], [(0.0, 0.5)])

    def test_folded_notes_keep_the_longest_duration(self) -> None:
        """音域外の C3 はオクターブ移調で C4 と同じキーに落ちる。長い方を採る。"""
        actions = _actions(_score(NoteEvent(0.0, 4.0, (48, 60), (4.0, 1.0))), _mapping())
        spans = _spans(actions)
        self.assertEqual(list(spans), ["a"])
        self.assertEqual(spans["a"], [(0.0, 4.0)])


class RetriggerTest(unittest.TestCase):
    def test_overlapping_same_key_releases_before_next_press(self) -> None:
        """後勝ち。先行音は次の押下の手前で離す（間隔 10ms）。"""
        actions = _actions(
            _score(
                NoteEvent(0.0, 2.0, (60,), (2.0,)),   # 2 拍伸ばすが…
                NoteEvent(1.0, 1.0, (60,), (1.0,)),   # 1 拍後に同じキーを鳴らし直す
            ),
            _mapping(),
        )
        spans = _spans(actions)["a"]
        self.assertAlmostEqual(spans[0][1], 0.99)   # 1.0 - 0.010
        self.assertAlmostEqual(spans[1][0], 1.0)
        self.assertLess(spans[0][1], spans[1][0])

    def test_release_precedes_press_when_gap_is_zero(self) -> None:
        actions = _actions(
            _score(NoteEvent(0.0, 1.0, (60,), (1.0,)), NoteEvent(1.0, 1.0, (60,), (1.0,))),
            _mapping(),
            retrigger_gap_ms=0.0,
        )
        at_one = [a for a in actions if abs(a.at - 1.0) < 1e-9]
        self.assertEqual([a.is_down for a in at_one], [False, True])

    def test_different_keys_may_overlap_freely(self) -> None:
        actions = _actions(
            _score(NoteEvent(0.0, 4.0, (60,), (4.0,)), NoteEvent(1.0, 1.0, (62,), (1.0,))),
            _mapping(),
        )
        spans = _spans(actions)
        self.assertEqual(spans["a"], [(0.0, 4.0)])   # 切り詰められない
        self.assertEqual(spans["s"], [(1.0, 2.0)])

    def test_folded_octaves_collide_on_one_key(self) -> None:
        """C3 と C4 は別の音だが同じキー。時間的に重なれば後勝ちで切られる。"""
        actions = _actions(
            _score(NoteEvent(0.0, 3.0, (48,), (3.0,)), NoteEvent(1.0, 1.0, (60,), (1.0,))),
            _mapping(),
        )
        spans = _spans(actions)["a"]
        self.assertEqual(len(spans), 2)
        self.assertAlmostEqual(spans[0][1], 0.99)


class NearCollisionTest(unittest.TestCase):
    """同じキーの押下が近すぎるとき、鳴らし直す余地が無い。"""

    def _assert_alternates(self, actions: list) -> None:
        """キーごとに down / up が必ず交互で、押下時間が正であること。

        崩れると win_input が押しっぱなしのキーを二重に押し、余った up が
        後続の音を切る。ここが player の最も壊れやすい不変条件。
        """
        per_key: dict[str, list] = {}
        for a in actions:
            per_key.setdefault(a.keys[0], []).append(a)
        for key, seq in per_key.items():
            expect_down = True
            last_at = float("-inf")
            for a in seq:
                self.assertEqual(a.is_down, expect_down, f"key {key!r} の down/up が交互でない")
                if not a.is_down:
                    self.assertGreater(a.at, last_at, f"key {key!r} の押下時間が 0 以下")
                last_at = a.at
                expect_down = not expect_down
            self.assertFalse(expect_down is False, f"key {key!r} が押しっぱなし")

    def test_attacks_too_close_merge_into_one_hold(self) -> None:
        """2.5ms 差の再発音は、離す隙が無いので 1 つの押しっぱなしにする。"""
        actions = _actions(
            _score(NoteEvent(0.00, 0.5, (60,), (0.5,)), NoteEvent(0.02, 0.5, (60,), (0.5,))),
            _mapping(),
            speed=8.0,
            retrigger_gap_ms=25.0,
        )
        self._assert_alternates(actions)
        spans = _spans(actions)["a"]
        self.assertEqual(len(spans), 1)
        self.assertAlmostEqual(spans[0][0], 0.0)
        self.assertAlmostEqual(spans[0][1], 0.0025 + 0.5 / 8.0)  # 後続の音の終わりまで伸びる

    def test_attacks_within_one_frame_merge(self) -> None:
        """10ms 差。1 フレーム(16.7ms)より短く、離して押し直しても観測されない。"""
        actions = _actions(
            _score(NoteEvent(0.0, 0.5, (60,), (0.5,)), NoteEvent(0.01, 0.5, (60,), (0.5,))),
            _mapping(),
            retrigger_gap_ms=25.0,
        )
        self._assert_alternates(actions)
        self.assertEqual(len(_spans(actions)["a"]), 1)

    def test_attacks_with_room_still_retrigger(self) -> None:
        """余地があるなら統合せず、ちゃんと離して押し直す。"""
        actions = _actions(
            _score(NoteEvent(0.0, 0.5, (60,), (0.5,)), NoteEvent(0.5, 0.5, (60,), (0.5,))),
            _mapping(),
            retrigger_gap_ms=25.0,
        )
        self._assert_alternates(actions)
        spans = _spans(actions)["a"]
        self.assertEqual(len(spans), 2)
        self.assertAlmostEqual(spans[1][0] - spans[0][1], 0.025)

    def test_merging_is_reported_not_silent(self) -> None:
        """統合は音を 1 つ消す。黙って落とさず、必ず知らせる。"""
        messages: list[str] = []
        player = Player(_FakeSender(), on_status=messages.append)  # type: ignore[arg-type]
        player.build_actions(
            _score(NoteEvent(0.0, 0.5, (60,), (0.5,)), NoteEvent(0.01, 0.5, (60,), (0.5,))),
            _mapping(),
            PlaybackOptions(gate_ms=40.0, retrigger_gap_ms=25.0),
        )
        self.assertTrue(any("統合" in m for m in messages), messages)

    def test_no_message_when_nothing_is_merged(self) -> None:
        messages: list[str] = []
        player = Player(_FakeSender(), on_status=messages.append)  # type: ignore[arg-type]
        player.build_actions(
            _score(NoteEvent(0.0, 0.5, (60,), (0.5,)), NoteEvent(1.0, 0.5, (60,), (0.5,))),
            _mapping(),
            PlaybackOptions(gate_ms=40.0, retrigger_gap_ms=25.0),
        )
        self.assertEqual(messages, [])

    def test_dense_repeats_never_break_the_invariant(self) -> None:
        events = [NoteEvent(i * 0.02, 0.5, (60, 62), (0.5, 0.5)) for i in range(12)]
        for speed in (0.5, 1.0, 4.0, 16.0):
            with self.subTest(speed=speed):
                self._assert_alternates(
                    _actions(_score(*events), _mapping(), speed=speed, retrigger_gap_ms=25.0)
                )


class ScheduleTest(unittest.TestCase):
    def test_rests_produce_no_actions(self) -> None:
        self.assertEqual(_actions(_score(NoteEvent(0.0, 1.0, ())), _mapping()), [])

    def test_start_beat_skips_earlier_events_and_rebases_time(self) -> None:
        actions = _actions(
            _score(NoteEvent(0.0, 1.0, (60,), (1.0,)), NoteEvent(2.0, 1.0, (62,), (1.0,))),
            _mapping(),
            start_beat=2.0,
        )
        spans = _spans(actions)
        self.assertEqual(list(spans), ["s"])
        self.assertEqual(spans["s"], [(0.0, 1.0)])

    def test_actions_are_time_ordered(self) -> None:
        actions = _actions(
            _score(NoteEvent(0.0, 1.0, (60, 62, 64), (1.0, 0.5, 0.25))), _mapping()
        )
        self.assertEqual([a.at for a in actions], sorted(a.at for a in actions))

    def test_unmapped_notes_are_counted_as_skipped(self) -> None:
        mapping = KeyMapping(name="t", note_to_key={60: "a"}, out_of_range="skip")
        player = Player(_FakeSender())  # type: ignore[arg-type]
        _acts, skipped = player.build_actions(
            _score(NoteEvent(0.0, 1.0, (60, 62), (1.0, 1.0))), mapping, PlaybackOptions()
        )
        self.assertEqual(skipped, 1)

    def test_speed_scales_durations(self) -> None:
        actions = _actions(_score(NoteEvent(0.0, 2.0, (60,), (2.0,))), _mapping(), speed=2.0)
        onset, release = _spans(actions)["a"][0]
        self.assertAlmostEqual(release - onset, 1.0)


class TimingDefaultsTest(unittest.TestCase):
    def test_retrigger_gap_exceeds_one_frame_at_60fps(self) -> None:
        """60fps のゲームは 16.7ms ごとにしかキー状態を見ないことがある。

        1 フレームより短い間隔は丸ごと取りこぼされ、押下エッジでしか発音しない楽器では
        鳴らし直しが消える。実測でも、既定のタイマ分解能（約 15.6ms）のままでは
        10ms の間隔が 0ms に潰れた。
        """
        self.assertGreaterEqual(PlaybackOptions().retrigger_gap_ms, 1000.0 / 60.0)

    def test_high_resolution_timer_does_not_raise(self) -> None:
        """winmm が使えない環境でも、例外を投げず単に何もしない。"""
        with high_resolution_timer():
            with high_resolution_timer():
                pass


class KeyMappingSustainTest(unittest.TestCase):
    """sustain は保存・読み込み・テキスト編集を通っても失われない。"""

    def test_defaults_to_sustaining(self) -> None:
        self.assertTrue(KeyMapping(name="t", note_to_key={60: "a"}).sustain)

    def test_round_trip_through_dict(self) -> None:
        original = KeyMapping(name="t", note_to_key={60: "a"}, sustain=False)
        self.assertFalse(KeyMapping.from_dict(original.to_dict()).sustain)

    def test_old_config_without_sustain_loads_as_sustaining(self) -> None:
        data = {"name": "t", "out_of_range": "transpose", "note_to_key": {"60": "a"}}
        self.assertTrue(KeyMapping.from_dict(data).sustain)

    def test_from_text_keeps_sustain(self) -> None:
        mapping = KeyMapping.from_text("C4 = a", name="t", sustain=False)
        self.assertFalse(mapping.sustain)

if __name__ == "__main__":
    unittest.main()
