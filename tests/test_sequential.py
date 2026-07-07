"""重なった音（複声部由来）の逐次記譜変換のテスト。

MusicXML / OMR 取り込みでは「長いベースの上にメロディ」のように
イベントが重なる。テキスト・数字譜へ変換しても発音タイミングが
ずれないこと（次の音の開始で音長を切り詰めること）を確認する。
"""

import unittest

from autoplaynotes.convert import score_to_numbers
from autoplaynotes.model import NoteEvent, Score, sequential_durations
from autoplaynotes.number_parser import parse_numbers
from autoplaynotes.text_parser import parse_text, score_to_text


def _overlapping_score() -> Score:
    return Score(
        tempo_bpm=120.0,
        events=[
            NoteEvent(0.0, 4.0, (48,)),  # 長いベース（メロディと重なる）
            NoteEvent(1.0, 1.0, (72,)),
            NoteEvent(2.0, 1.0, (74,)),
            NoteEvent(4.0, 1.0, (76,)),  # 重ならない音
        ],
    )


class SequentialDurationsTest(unittest.TestCase):
    def test_overlap_truncated(self):
        # 3音目(2.0拍開始)は次の音(4.0拍)と重ならないので切り詰めない
        result = sequential_durations(_overlapping_score().events)
        self.assertEqual([round(d, 6) for _e, d in result], [1.0, 1.0, 1.0, 1.0])

    def test_no_overlap_unchanged(self):
        events = [NoteEvent(0.0, 1.0, (60,)), NoteEvent(2.0, 0.5, (62,))]
        result = sequential_durations(events)
        self.assertEqual([d for _e, d in result], [1.0, 0.5])


class OverlapRoundTripTest(unittest.TestCase):
    def test_text_keeps_onsets(self):
        text = score_to_text(_overlapping_score())
        reparsed = parse_text(text)
        self.assertEqual(
            [e.start_beat for e in reparsed.events], [0.0, 1.0, 2.0, 4.0]
        )
        self.assertEqual(
            [e.midi_notes for e in reparsed.events], [(48,), (72,), (74,), (76,)]
        )

    def test_numbers_keep_onsets(self):
        numbers = score_to_numbers(_overlapping_score(), tonic="C")
        reparsed = parse_numbers(numbers)
        self.assertEqual(
            [e.start_beat for e in reparsed.events], [0.0, 1.0, 2.0, 4.0]
        )


if __name__ == "__main__":
    unittest.main()
