"""difficulty（難易度＝同時に押すキーの数）のテスト。

難易度の軸はひとつだけ。速度も、リズム/ステップの別も、誰が弾くかも、別の軸として
既に実装済み。ここでは「同時に押すキーの数」だけを扱う。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoplaynotes import difficulty  # noqa: E402
from autoplaynotes.keymap import KeyMapping  # noqa: E402
from autoplaynotes.model import NoteEvent, Score  # noqa: E402


def _sample_score() -> Score:
    return Score(tempo_bpm=100, title="Test", events=[
        NoteEvent(0.0, 1.0, (60, 64, 67)),   # C メジャー三和音
        NoteEvent(1.0, 1.0, (62,)),          # 単音
        NoteEvent(2.0, 1.0, ()),             # 休符
        NoteEvent(3.0, 1.0, (48, 60, 64, 67, 72)),  # 5 音
    ])


class ThinChordTest(unittest.TestCase):
    def test_outer_keeps_melody_and_bass(self) -> None:
        self.assertEqual(difficulty.thin_chord((60, 64, 67), 2), (60, 67))

    def test_outer_with_one_key_keeps_the_top(self) -> None:
        self.assertEqual(difficulty.thin_chord((60, 64, 67), 1), (67,))

    def test_outer_fills_from_the_top(self) -> None:
        # 最高音 72・最低音 48 を確保し、余り 1 枠は高い方（67）から
        self.assertEqual(difficulty.thin_chord((48, 60, 64, 67, 72), 3), (48, 67, 72))

    def test_top_strategy_keeps_highest(self) -> None:
        self.assertEqual(difficulty.thin_chord((60, 64, 67), 2, "top"), (64, 67))

    def test_fewer_notes_than_budget_is_unchanged(self) -> None:
        self.assertEqual(difficulty.thin_chord((60,), 3), (60,))

    def test_rest_stays_rest(self) -> None:
        self.assertEqual(difficulty.thin_chord((), 2), ())

    def test_duplicates_collapse(self) -> None:
        self.assertEqual(difficulty.thin_chord((60, 60, 64), 2), (60, 64))

    def test_result_is_sorted_ascending(self) -> None:
        self.assertEqual(difficulty.thin_chord((67, 60, 64), 3), (60, 64, 67))

    def test_zero_keys_rejected(self) -> None:
        with self.assertRaises(ValueError):
            difficulty.thin_chord((60,), 0)


class KeySpaceTest(unittest.TestCase):
    """数えるのは音の数ではなくキーの数。同じキーに落ちる音は指 1 本。"""

    def _folding_mapping(self) -> KeyMapping:
        # C4..E4 の 3 鍵。C3 も C5 もオクターブ移調で C4 のキーへ畳まれる。
        return KeyMapping(name="t", note_to_key={60: "a", 62: "s", 64: "d"})

    def test_octave_folded_notes_cost_one_key(self) -> None:
        mapping = self._folding_mapping()
        event = NoteEvent(0.0, 1.0, (48, 60, 72))  # 3 音、すべてキー 'a'
        self.assertEqual(difficulty.keys_at_once(event, mapping), 1)

    def test_folded_notes_are_kept_together(self) -> None:
        """同じキーなら何音あっても指は増えないので、まとめて残す。"""
        mapping = self._folding_mapping()
        kept = difficulty.thin_chord((48, 60, 72), 1, mapping=mapping)
        self.assertEqual(kept, (48, 60, 72))

    def test_without_mapping_notes_are_counted_as_keys(self) -> None:
        event = NoteEvent(0.0, 1.0, (48, 60, 72))
        self.assertEqual(difficulty.keys_at_once(event), 3)

    def test_budget_counts_keys_not_notes(self) -> None:
        mapping = self._folding_mapping()
        # C3/C4/C5 は 1 キー、D4 が 2 キー目。予算 1 なら D4 が落ちる。
        kept = difficulty.thin_chord((48, 60, 62, 72), 1, mapping=mapping)
        self.assertEqual(kept, (48, 60, 72))

    def test_unplayable_notes_cost_no_key(self) -> None:
        """out_of_range='skip' で鳴らない音は指を使わない。原曲へ戻せるよう残す。"""
        mapping = KeyMapping(name="t", note_to_key={60: "a"}, out_of_range="skip")
        self.assertEqual(difficulty.keys_at_once(NoteEvent(0.0, 1.0, (60, 62)), mapping), 1)
        self.assertEqual(difficulty.thin_chord((60, 62), 1, mapping=mapping), (60, 62))


class MonotonicityTest(unittest.TestCase):
    """難易度を上げると音は増えるだけで、消えない。"""

    def _chord(self) -> tuple[int, ...]:
        return (48, 55, 60, 64, 67, 72)

    def test_levels_are_nested(self) -> None:
        for strategy in ("outer", "top"):
            with self.subTest(strategy=strategy):
                previous: set[int] = set()
                for budget in range(1, len(self._chord()) + 1):
                    kept = set(difficulty.thin_chord(self._chord(), budget, strategy))
                    self.assertTrue(
                        previous <= kept,
                        f"難易度 {budget} で {previous - kept} が消えた（{strategy}）",
                    )
                    previous = kept

    def test_never_exceeds_the_budget(self) -> None:
        for budget in range(1, 7):
            kept = difficulty.thin_chord(self._chord(), budget)
            self.assertLessEqual(len(kept), budget)

    def test_top_of_the_ladder_is_the_original(self) -> None:
        score = _sample_score()
        top = difficulty.max_simultaneous(score)
        thinned = difficulty.thin_score(score, top)
        self.assertEqual(
            [e.midi_notes for e in thinned.events], [e.midi_notes for e in score.events]
        )

    def test_full_is_the_original(self) -> None:
        score = _sample_score()
        full = difficulty.apply(score, difficulty.FULL)
        self.assertEqual(
            [e.midi_notes for e in full.events], [e.midi_notes for e in score.events]
        )


class LevelsForTest(unittest.TestCase):
    def test_max_simultaneous_is_the_widest_chord(self) -> None:
        self.assertEqual(difficulty.max_simultaneous(_sample_score()), 5)

    def test_levels_run_from_one_to_the_maximum(self) -> None:
        self.assertEqual(difficulty.levels_for(_sample_score()), (1, 2, 3, 4, 5))

    def test_monophonic_song_has_a_single_level(self) -> None:
        score = Score(events=[NoteEvent(0.0, 1.0, (60,)), NoteEvent(1.0, 1.0, (62,))])
        self.assertEqual(difficulty.levels_for(score), (1,))

    def test_empty_score_has_no_levels(self) -> None:
        self.assertEqual(difficulty.levels_for(Score(events=[])), ())

    def test_rests_only_score_has_no_levels(self) -> None:
        self.assertEqual(difficulty.levels_for(Score(events=[NoteEvent(0.0, 1.0, ())])), ())

    def test_mapping_lowers_the_maximum_when_keys_fold(self) -> None:
        mapping = KeyMapping(name="t", note_to_key={60: "a", 64: "d"})
        score = Score(events=[NoteEvent(0.0, 1.0, (48, 60, 64))])  # 3 音だが 2 キー
        self.assertEqual(difficulty.max_simultaneous(score), 3)
        self.assertEqual(difficulty.max_simultaneous(score, mapping), 2)

    def test_describe(self) -> None:
        self.assertEqual(difficulty.describe(difficulty.FULL), "原曲どおり")
        self.assertIn("1", difficulty.describe(1))
        self.assertIn("3", difficulty.describe(3))


class ThinScoreTest(unittest.TestCase):
    def test_single_key(self) -> None:
        thinned = difficulty.thin_score(_sample_score(), 1)
        self.assertEqual(
            [e.midi_notes for e in thinned.events], [(67,), (62,), (), (72,)]
        )

    def test_timing_and_metadata_preserved(self) -> None:
        original = _sample_score()
        thinned = difficulty.thin_score(original, 1)
        self.assertEqual(thinned.tempo_bpm, original.tempo_bpm)
        self.assertEqual(thinned.title, original.title)
        self.assertEqual(
            [e.start_beat for e in thinned.events], [e.start_beat for e in original.events]
        )

    def test_original_score_not_mutated(self) -> None:
        original = _sample_score()
        difficulty.thin_score(original, 1)
        self.assertEqual(original.events[0].midi_notes, (60, 64, 67))

    def test_reversible_from_source(self) -> None:
        """元の Score が生きているので、いつでも原曲へ戻れる。"""
        original = _sample_score()
        easy = difficulty.thin_score(original, 1)
        back = difficulty.apply(original, difficulty.FULL)
        self.assertNotEqual(easy.events[0].midi_notes, back.events[0].midi_notes)
        self.assertEqual(back.events[0].midi_notes, (60, 64, 67))


class PerNoteDurationTest(unittest.TestCase):
    """音を間引いたとき、音ごとの音長も一緒に絞り込まれること。"""

    def _held_bass(self) -> Score:
        # 左手 C3 を 4 拍、その上で右手 E4/G4 が 1 拍
        return Score(tempo_bpm=120, events=[
            NoteEvent(0.0, 4.0, (48, 64, 67), (4.0, 1.0, 1.0)),
            NoteEvent(4.0, 1.0, (62,), (1.0,)),
        ])

    def test_thinning_keeps_the_kept_notes_durations(self) -> None:
        thinned = difficulty.thin_score(self._held_bass(), 1)
        self.assertEqual(thinned.events[0].midi_notes, (67,))
        self.assertEqual(thinned.events[0].durations, (1.0,))

    def test_event_extent_shrinks_with_the_notes(self) -> None:
        thinned = difficulty.thin_score(self._held_bass(), 1)
        self.assertEqual(thinned.events[0].duration_beat, 1.0)  # 4.0 のままではない

    def test_outer_keeps_bass_duration(self) -> None:
        thinned = difficulty.thin_score(self._held_bass(), 2)
        self.assertEqual(thinned.events[0].midi_notes, (48, 67))
        self.assertEqual(thinned.events[0].durations, (4.0, 1.0))
        self.assertEqual(thinned.events[0].duration_beat, 4.0)

    def test_rest_survives_thinning(self) -> None:
        score = Score(events=[NoteEvent(0.0, 1.0, ())])
        thinned = difficulty.thin_score(score, 1)
        self.assertTrue(thinned.events[0].is_rest)
        self.assertEqual(thinned.events[0].durations, ())

    def test_uniform_durations_are_materialised(self) -> None:
        score = Score(events=[NoteEvent(0.0, 2.0, (60, 64))])
        thinned = difficulty.thin_score(score, 1)
        self.assertEqual(thinned.events[0].durations, (2.0,))


class NotMelodyExtractionTest(unittest.TestCase):
    """同時押しを減らすだけで、声部（メロディ）は追わない。

    ここは「バグ」ではなく仕様。skyline 法でメロディを取ろうとすると下記のとおり
    壊れるため、意図的にやっていない。将来これを「メロディ抽出」と呼び直そうと
    する人が現れたら、このテストが何を失うかを見せる。
    """

    def test_arpeggio_is_untouched(self) -> None:
        """分散和音（アルベルティ・バス）は各イベントが単音。減らす対象が無い。"""
        alberti = Score(events=[
            NoteEvent(i * 0.5, 0.5, (n,), (0.5,))
            for i, n in enumerate([48, 55, 52, 55])
        ])
        thinned = difficulty.thin_score(alberti, 1)
        self.assertEqual(
            [e.midi_notes for e in thinned.events], [(48,), (55,), (52,), (55,)]
        )

    def test_sustained_melody_is_lost_after_its_onset(self) -> None:
        """保続するメロディは発音時のイベントにしか無い。以降は伴奏の最高音が残る。"""
        score = Score(events=[
            NoteEvent(0.0, 2.0, (48, 72), (0.5, 2.0)),  # 伴奏 C3 ＋ 保続するメロディ C5
            NoteEvent(0.5, 0.5, (55,), (0.5,)),         # 伴奏だけ
            NoteEvent(1.0, 0.5, (52,), (0.5,)),
        ])
        thinned = difficulty.thin_score(score, 1)
        self.assertEqual([e.midi_notes for e in thinned.events], [(72,), (55,), (52,)])
        # メロディ C5 は 1 回しか現れない。旋律線は追えていない。
        self.assertEqual(sum(72 in e.midi_notes for e in thinned.events), 1)

    def test_inner_voice_melody_is_dropped(self) -> None:
        """内声にメロディがあれば当然残らない。最高音を採るとはそういうこと。"""
        score = Score(events=[NoteEvent(0.0, 1.0, (48, 60, 79), (1.0, 1.0, 1.0))])
        self.assertEqual(difficulty.thin_score(score, 1).events[0].midi_notes, (79,))

    def test_what_it_does_guarantee_is_the_number_of_keys(self) -> None:
        """保証しているのはただ 1 つ、同時に押すキーの数。"""
        score = Score(events=[
            NoteEvent(0.0, 1.0, (48, 55, 60, 64, 67), (1.0,) * 5),
            NoteEvent(1.0, 1.0, (50, 62), (1.0, 1.0)),
        ])
        for budget in (1, 2, 3):
            with self.subTest(budget=budget):
                for event in difficulty.thin_score(score, budget).events:
                    self.assertLessEqual(difficulty.keys_at_once(event), budget)


if __name__ == "__main__":
    unittest.main()
