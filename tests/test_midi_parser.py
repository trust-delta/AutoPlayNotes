"""midi_parser の音長（note_on / note_off の対）に関するテスト。

このモジュールには従来テストが無く、音長を「次の発音までの距離」として
捏造していたことに誰も気づけなかった。純ロジック（_build_from_events）は
mido なしで検証し、実ファイル読み込みは mido があるときだけ検証する。
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoplaynotes import midi_parser, score_export  # noqa: E402
from autoplaynotes.model import NoteEvent, Score  # noqa: E402

TPB = 480


def _build(events: list[tuple[int, int, int, int, int]], **kwargs: object) -> Score:
    """(track, channel, start_tick, note, end_tick) から Score を組む。"""
    params: dict[str, object] = {
        "selected_keys": None,
        "monophonic": False,
        "octave_shift": 0,
        "include_drums": False,
    }
    params.update(kwargs)
    return midi_parser._build_from_events(
        events, TPB, 120.0, "test", **params  # type: ignore[arg-type]
    )


class DurationFromNoteOffTest(unittest.TestCase):
    def test_duration_comes_from_note_off(self) -> None:
        score = _build([(0, 0, 0, 60, TPB)])
        self.assertEqual(score.events[0].duration_beat, 1.0)
        self.assertEqual(score.events[0].durations, (1.0,))

    def test_rest_is_a_gap_not_a_stretched_note(self) -> None:
        """4分音符 → 1.5拍の休符 → 次の音。前の音が休符まで伸びてはいけない。"""
        score = _build([(0, 0, 0, 60, TPB), (0, 0, TPB * 2, 62, TPB * 3)])
        first, second = score.events
        self.assertEqual(first.duration_beat, 1.0)          # 2.0 ではない
        self.assertEqual(second.start_beat, 2.0)
        self.assertEqual(first.start_beat + first.duration_beat, 1.0)

    def test_zero_length_note_gets_floor(self) -> None:
        score = _build([(0, 0, 0, 60, 0)])
        self.assertEqual(score.events[0].duration_beat, midi_parser._MIN_DURATION_BEATS)

    def test_last_note_keeps_its_own_length(self) -> None:
        """末尾の音は 1.0 拍決め打ちではなく、実音長を持つ。"""
        score = _build([(0, 0, 0, 60, TPB * 4)])
        self.assertEqual(score.events[0].duration_beat, 4.0)


class ChordPerNoteDurationTest(unittest.TestCase):
    def _held_bass_with_moving_melody(self) -> Score:
        # 左手 C3 を 4 拍伸ばし、その上で右手 C4 が 1 拍
        return _build([
            (0, 0, 0, 48, TPB * 4),
            (0, 0, 0, 60, TPB),
        ])

    def test_chord_notes_keep_individual_durations(self) -> None:
        event = self._held_bass_with_moving_melody().events[0]
        self.assertEqual(event.midi_notes, (48, 60))
        self.assertEqual(event.durations, (4.0, 1.0))

    def test_event_extent_is_the_longest_note(self) -> None:
        event = self._held_bass_with_moving_melody().events[0]
        self.assertEqual(event.duration_beat, 4.0)

    def test_note_durations_align_with_midi_notes(self) -> None:
        event = self._held_bass_with_moving_melody().events[0]
        self.assertEqual(
            dict(zip(event.midi_notes, event.note_durations())), {48: 4.0, 60: 1.0}
        )


class MergeWindowTest(unittest.TestCase):
    def test_near_onsets_merge_into_one_chord(self) -> None:
        score = _build([(0, 0, 0, 60, TPB), (0, 0, 5, 64, TPB)])
        self.assertEqual(len(score.events), 1)
        self.assertEqual(score.events[0].midi_notes, (60, 64))

    def test_merged_note_duration_measured_from_group_start(self) -> None:
        # tick 5 で始まる音も、グループ開始 (tick 0) からの長さで持つ
        score = _build([(0, 0, 0, 60, TPB), (0, 0, 5, 64, TPB * 4)])
        self.assertEqual(score.events[0].durations, (1.0, 4.0))

    def test_distant_onsets_stay_separate(self) -> None:
        score = _build([(0, 0, 0, 60, TPB), (0, 0, 100, 64, TPB)])
        self.assertEqual(len(score.events), 2)

    def test_duplicate_note_keeps_longer(self) -> None:
        score = _build([(0, 0, 0, 60, TPB), (0, 1, 0, 60, TPB * 3)])
        self.assertEqual(score.events[0].durations, (3.0,))


class OptionsTest(unittest.TestCase):
    def test_monophonic_keeps_top_note_with_its_own_duration(self) -> None:
        score = _build([(0, 0, 0, 48, TPB * 4), (0, 0, 0, 60, TPB)], monophonic=True)
        self.assertEqual(score.events[0].midi_notes, (60,))
        self.assertEqual(score.events[0].durations, (1.0,))

    def test_drums_excluded_by_default(self) -> None:
        score = _build([(0, 9, 0, 38, TPB)])
        self.assertEqual(score.events, [])

    def test_selected_keys_filter(self) -> None:
        events = [(0, 0, 0, 60, TPB), (1, 0, 0, 48, TPB)]
        score = _build(events, selected_keys={(0, 0)})
        self.assertEqual(score.events[0].midi_notes, (60,))

    def test_octave_shift_preserves_duration(self) -> None:
        score = _build([(0, 0, 0, 60, TPB * 2)], octave_shift=-1)
        self.assertEqual(score.events[0].midi_notes, (48,))
        self.assertEqual(score.events[0].durations, (2.0,))

    def test_empty_events(self) -> None:
        self.assertEqual(_build([]).events, [])


@unittest.skipUnless(midi_parser.is_available(), "mido が必要")
class ReadNoteOffTest(unittest.TestCase):
    """実ファイル読み込み（note_on / note_off の対応付け）。"""

    def _read_events(self, messages: list[object]) -> list[tuple[int, int, int, int, int]]:
        import mido

        midi = mido.MidiFile(ticks_per_beat=TPB)
        track = mido.MidiTrack()
        for msg in messages:
            track.append(msg)
        midi.tracks.append(track)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.mid")
            midi.save(path)
            _tpb, _bpm, events, _names, _programs = midi_parser._read(path)
        return events

    def test_note_off_pairs_with_note_on(self) -> None:
        import mido

        events = self._read_events([
            mido.Message("note_on", note=60, velocity=64, time=0),
            mido.Message("note_off", note=60, velocity=0, time=TPB),
        ])
        self.assertEqual([(e[2], e[3], e[4]) for e in events], [(0, 60, TPB)])

    def test_note_on_velocity_zero_is_note_off(self) -> None:
        import mido

        events = self._read_events([
            mido.Message("note_on", note=60, velocity=64, time=0),
            mido.Message("note_on", note=60, velocity=0, time=TPB),
        ])
        self.assertEqual([(e[2], e[3], e[4]) for e in events], [(0, 60, TPB)])

    def test_retrigger_closes_previous_note(self) -> None:
        """鳴っている同音を再発音したら、先行音はその時点で閉じる（後勝ち）。"""
        import mido

        events = self._read_events([
            mido.Message("note_on", note=60, velocity=64, time=0),
            mido.Message("note_on", note=60, velocity=64, time=TPB // 2),
            mido.Message("note_off", note=60, velocity=0, time=TPB // 2),
        ])
        spans = sorted((e[2], e[4]) for e in events)
        self.assertEqual(spans, [(0, TPB // 2), (TPB // 2, TPB)])

    def test_unclosed_note_ends_at_track_end(self) -> None:
        import mido

        events = self._read_events([
            mido.Message("note_on", note=60, velocity=64, time=0),
            mido.MetaMessage("end_of_track", time=TPB * 2),
        ])
        self.assertEqual([(e[2], e[3], e[4]) for e in events], [(0, 60, TPB * 2)])

    def test_same_note_on_different_channels_are_independent(self) -> None:
        import mido

        events = self._read_events([
            mido.Message("note_on", note=60, velocity=64, channel=0, time=0),
            mido.Message("note_on", note=60, velocity=64, channel=1, time=0),
            mido.Message("note_off", note=60, velocity=0, channel=0, time=TPB),
            mido.Message("note_off", note=60, velocity=0, channel=1, time=TPB),
        ])
        self.assertEqual(len(events), 2)
        self.assertEqual(sorted(e[4] for e in events), [TPB, TPB * 2])


@unittest.skipUnless(midi_parser.is_available(), "mido が必要")
class RoundTripTest(unittest.TestCase):
    """score_export で書き出した MIDI を読み戻し、音ごとの音長が保たれるか。"""

    def test_per_note_durations_survive_midi_round_trip(self) -> None:
        score = Score(tempo_bpm=120.0, title="rt", events=[
            NoteEvent(0.0, 4.0, (48, 60), (4.0, 1.0)),
            NoteEvent(4.0, 0.5, (62,), (0.5,)),
        ])
        data = score_export.score_to_midi_bytes(score)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rt.mid")
            with open(path, "wb") as fh:
                fh.write(data)
            restored = midi_parser.build_score(path)

        first = restored.events[0]
        self.assertEqual(first.midi_notes, (48, 60))
        self.assertEqual(first.durations, (4.0, 1.0))
        self.assertEqual(restored.events[1].durations, (0.5,))

    def test_gap_is_preserved_as_a_gap(self) -> None:
        score = Score(tempo_bpm=120.0, title="rt", events=[
            NoteEvent(0.0, 1.0, (60,), (1.0,)),
            NoteEvent(3.0, 1.0, (62,), (1.0,)),
        ])
        data = score_export.score_to_midi_bytes(score)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rt.mid")
            with open(path, "wb") as fh:
                fh.write(data)
            restored = midi_parser.build_score(path)

        self.assertEqual(restored.events[0].duration_beat, 1.0)
        self.assertEqual(restored.events[1].start_beat, 3.0)


class NoteEventValidationTest(unittest.TestCase):
    def test_mismatched_durations_rejected(self) -> None:
        with self.assertRaises(ValueError):
            NoteEvent(0.0, 1.0, (60, 64), (1.0,))

    def test_empty_durations_fall_back_to_uniform(self) -> None:
        event = NoteEvent(0.0, 2.0, (60, 64))
        self.assertEqual(event.note_durations(), (2.0, 2.0))

    def test_stale_durations_after_edit_fall_back(self) -> None:
        event = NoteEvent(0.0, 2.0, (60, 64), (2.0, 1.0))
        event.midi_notes = (60, 64, 67)  # エディタが音を足した想定
        self.assertEqual(event.note_durations(), (2.0, 2.0, 2.0))


if __name__ == "__main__":
    unittest.main()
