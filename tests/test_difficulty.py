"""difficulty（難易度の階段）の変換テスト。"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoplaynotes import difficulty  # noqa: E402
from autoplaynotes.model import NoteEvent, Score  # noqa: E402


def _sample_score() -> Score:
    return Score(tempo_bpm=100, title="Test", events=[
        NoteEvent(0.0, 1.0, (60, 64, 67)),   # C メジャー三和音
        NoteEvent(1.0, 1.0, (62,)),          # 単音
        NoteEvent(2.0, 1.0, ()),             # 休符
        NoteEvent(3.0, 1.0, (48, 60, 64, 67, 72)),  # 5 音
    ])


class ThinChordTest(unittest.TestCase):
    def test_top_keeps_highest(self) -> None:
        self.assertEqual(difficulty.thin_chord((60, 64, 67), 1), (67,))
        self.assertEqual(difficulty.thin_chord((60, 64, 67), 2), (64, 67))

    def test_outer_keeps_melody_and_root(self) -> None:
        self.assertEqual(difficulty.thin_chord((60, 64, 67), 2, "outer"), (60, 67))

    def test_outer_with_one_note_keeps_melody(self) -> None:
        self.assertEqual(difficulty.thin_chord((60, 64, 67), 1, "outer"), (67,))

    def test_outer_fills_from_top(self) -> None:
        # 最高音 72・最低音 48 を確保し、余り 1 枠は高い方（67）から
        self.assertEqual(
            difficulty.thin_chord((48, 60, 64, 67, 72), 3, "outer"), (48, 67, 72)
        )

    def test_shorter_than_max_is_unchanged(self) -> None:
        self.assertEqual(difficulty.thin_chord((60,), 3), (60,))

    def test_rest_stays_rest(self) -> None:
        self.assertEqual(difficulty.thin_chord((), 2), ())

    def test_duplicates_collapse(self) -> None:
        self.assertEqual(difficulty.thin_chord((60, 60, 64), 2), (60, 64))

    def test_result_is_sorted_ascending(self) -> None:
        self.assertEqual(difficulty.thin_chord((67, 60, 64), 3), (60, 64, 67))

    def test_zero_max_notes_rejected(self) -> None:
        with self.assertRaises(ValueError):
            difficulty.thin_chord((60,), 0)


class ThinScoreTest(unittest.TestCase):
    def test_melody_only(self) -> None:
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
            [(e.start_beat, e.duration_beat) for e in thinned.events],
            [(e.start_beat, e.duration_beat) for e in original.events],
        )

    def test_original_score_not_mutated(self) -> None:
        original = _sample_score()
        difficulty.thin_score(original, 1)
        self.assertEqual(original.events[0].midi_notes, (60, 64, 67))

    def test_reversible_from_source(self) -> None:
        """段を下げても元の Score が生きているので、いつでも原曲へ戻れる。"""
        original = _sample_score()
        easy = difficulty.thin_score(original, 1)
        back = difficulty.apply_level(original, difficulty.level_at(4))
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
        thinned = difficulty.thin_score(self._held_bass(), 2, "outer")
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

    def test_apply_level_carries_durations(self) -> None:
        score = difficulty.apply_level(self._held_bass(), difficulty.level_at(3))
        self.assertEqual(score.events[0].durations, (4.0, 1.0))


class NotMelodyExtractionTest(unittest.TestCase):
    """thin_chord は同時押しを減らすだけで、声部（メロディ）を追わない。

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

    def test_what_it_does_guarantee_is_simultaneity(self) -> None:
        """保証しているのはただ 1 つ、同時に押すキーの数。"""
        score = Score(events=[
            NoteEvent(0.0, 1.0, (48, 55, 60, 64, 67), (1.0,) * 5),
            NoteEvent(1.0, 1.0, (50, 62), (1.0, 1.0)),
        ])
        for max_notes in (1, 2, 3):
            with self.subTest(max_notes=max_notes):
                thinned = difficulty.thin_score(score, max_notes)
                for event in thinned.events:
                    self.assertLessEqual(len(event.midi_notes), max_notes)


class LadderTest(unittest.TestCase):
    def test_indices_are_contiguous_from_zero(self) -> None:
        self.assertEqual([lv.index for lv in difficulty.LADDER], [0, 1, 2, 3, 4])

    def test_only_level_zero_sends_keys_to_game(self) -> None:
        sending = [lv.index for lv in difficulty.LADDER if lv.sends_keys_to_game]
        self.assertEqual(sending, [0])

    def test_speed_is_monotonically_non_decreasing(self) -> None:
        """段を上がるほど速くなる（遅くなる段があってはいけない）。"""
        speeds = [lv.speed for lv in difficulty.LADDER if not lv.auto_play]
        self.assertEqual(speeds, sorted(speeds))

    def test_note_budget_is_monotonically_non_decreasing(self) -> None:
        """段を上がるほど音が増える。None（原曲）は最後だけ。"""
        budgets = [lv.max_notes for lv in difficulty.LADDER if lv.max_notes is not None]
        self.assertEqual(budgets, sorted(budgets))
        self.assertIsNone(difficulty.LADDER[-1].max_notes)

    def test_level_at_rejects_unknown_index(self) -> None:
        with self.assertRaises(ValueError):
            difficulty.level_at(9)

    def test_apply_level_full_song_keeps_all_notes(self) -> None:
        score = difficulty.apply_level(_sample_score(), difficulty.level_at(4))
        self.assertEqual(score.events[3].midi_notes, (48, 60, 64, 67, 72))

    def test_apply_level_melody_only(self) -> None:
        score = difficulty.apply_level(_sample_score(), difficulty.level_at(2))
        self.assertEqual([e.midi_notes for e in score.events], [(67,), (62,), (), (72,)])

    def test_apply_level_melody_plus_root(self) -> None:
        score = difficulty.apply_level(_sample_score(), difficulty.level_at(3))
        self.assertEqual(score.events[0].midi_notes, (60, 67))
        self.assertEqual(score.events[3].midi_notes, (48, 72))

    def test_apply_level_does_not_mutate_source(self) -> None:
        original = _sample_score()
        difficulty.apply_level(original, difficulty.level_at(2))
        self.assertEqual(original.events[0].midi_notes, (60, 64, 67))


if __name__ == "__main__":
    unittest.main()
