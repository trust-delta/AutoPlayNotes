"""difficulty（難易度＝あなたが弾くキーの窓）のテスト。

難易度の軸はひとつ。窓をどこに、どれだけ広く取るか。速度も、時間の進み方も、
別の軸として既に実装済み。同時押しの間引き（thin_chord）は難易度ではなく任意の補助。
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoplaynotes import difficulty  # noqa: E402
from autoplaynotes.keymap import KeyMapping, name_to_midi  # noqa: E402
from autoplaynotes.model import NoteEvent, Score  # noqa: E402


def _piano() -> KeyMapping:
    """2 オクターブぶんの白鍵（C3〜B4）＋ C5。ドレミファソラシド が窓に収まる。"""
    names = ["C3", "D3", "E3", "F3", "G3", "A3", "B3",
             "C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5"]
    keys = "zxcvbnmasdfghjq"
    return KeyMapping(
        name="piano",
        note_to_key={name_to_midi(n): k for n, k in zip(names, keys)},
    )


def _do_re_mi() -> Score:
    """ドレミファソラシド。最後の「ド」が C5＝オクターブ境界の向こう側。"""
    scale = ["C4", "D4", "E4", "F4", "G4", "A4", "B4", "C5"]
    return Score(events=[
        NoteEvent(i * 0.5, 0.5, (name_to_midi(n),), (0.5,))
        for i, n in enumerate(scale)
    ])


def _chorale() -> Score:
    return Score(events=[
        NoteEvent(0.0, 1.0, (name_to_midi("C3"), name_to_midi("E4"), name_to_midi("G4"))),
        NoteEvent(1.0, 1.0, (name_to_midi("G3"), name_to_midi("D4"), name_to_midi("B4"))),
        NoteEvent(2.0, 1.0, ()),  # 休符
    ])


class WindowTest(unittest.TestCase):
    def test_keyboard_is_ordered_by_pitch(self) -> None:
        layout = difficulty.keyboard(_piano())
        self.assertEqual([k for k, _p in layout][:3], ["z", "x", "c"])
        self.assertEqual([p for _k, p in layout], sorted(p for _k, p in layout))

    def test_do_re_mi_fits_in_one_window(self) -> None:
        """音楽の 1 オクターブは ド〜ド の 8 鍵。MIDI のオクターブ番号では切れない。"""
        window = difficulty.keys_between(_piano(), name_to_midi("C4"), name_to_midi("C5"))
        self.assertEqual(len(window), 8)
        mine, app = difficulty.split(_do_re_mi(), _piano(), window)
        self.assertEqual(sum(len(e.midi_notes) for e in mine.events), 8)
        self.assertEqual(sum(len(e.midi_notes) for e in app.events), 0)

    def test_octave_numbered_window_would_lose_the_last_note(self) -> None:
        """C4〜B4 で切ると、最後の「ド」(C5) が窓から外れる。窓をこう定義してはいけない。"""
        window = difficulty.keys_between(_piano(), name_to_midi("C4"), name_to_midi("B4"))
        mine, app = difficulty.split(_do_re_mi(), _piano(), window)
        self.assertEqual(sum(len(e.midi_notes) for e in mine.events), 7)
        self.assertEqual(sum(len(e.midi_notes) for e in app.events), 1)


class PartitionTest(unittest.TestCase):
    """窓で分ける限り、あなたとアプリは同じ物理キーを取り合わない。"""

    def _windows(self) -> list[frozenset[str]]:
        piano = _piano()
        lo, hi = name_to_midi("C3"), name_to_midi("C5")
        return [
            difficulty.keys_between(piano, a, b)
            for a in range(lo, hi + 1, 2)
            for b in range(a, hi + 1, 3)
        ]

    def test_key_sets_are_always_disjoint(self) -> None:
        piano = _piano()
        for window in self._windows():
            with self.subTest(window=sorted(window)):
                mine, app = difficulty.split(_chorale(), piano, window)
                my_keys = {piano.resolve(n) for e in mine.events for n in e.midi_notes}
                app_keys = {piano.resolve(n) for e in app.events for n in e.midi_notes}
                self.assertEqual(my_keys & app_keys, set())

    def test_no_note_is_lost(self) -> None:
        piano = _piano()
        for window in self._windows():
            with self.subTest(window=sorted(window)):
                mine, app = difficulty.split(_chorale(), piano, window)
                for src, a, b in zip(_chorale().events, mine.events, app.events):
                    self.assertEqual(
                        tuple(sorted(a.midi_notes + b.midi_notes)), tuple(sorted(src.midi_notes))
                    )

    def test_widening_the_window_only_adds_notes(self) -> None:
        """窓を広げると音は増えるだけで、消えない。練習した譜面が別物にならない。"""
        piano = _piano()
        previous: set[int] = set()
        lo = name_to_midi("C4")
        for hi in range(lo, name_to_midi("C5") + 1):
            window = difficulty.keys_between(piano, lo, hi)
            mine = difficulty.apply(_chorale(), piano, window)
            notes = {n for e in mine.events for n in e.midi_notes}
            self.assertTrue(previous <= notes, f"hi={hi} で {previous - notes} が消えた")
            previous = notes

    def test_full_window_is_the_original(self) -> None:
        piano = _piano()
        mine, app = difficulty.split(_chorale(), piano, difficulty.full_window(piano))
        self.assertEqual(
            [e.midi_notes for e in mine.events], [e.midi_notes for e in _chorale().events]
        )
        self.assertEqual(sum(len(e.midi_notes) for e in app.events), 0)

    def test_empty_window_gives_everything_to_the_app(self) -> None:
        piano = _piano()
        mine, app = difficulty.split(_chorale(), piano, frozenset())
        self.assertEqual(sum(len(e.midi_notes) for e in mine.events), 0)
        self.assertEqual(
            [e.midi_notes for e in app.events], [e.midi_notes for e in _chorale().events]
        )

    def test_durations_survive_the_split(self) -> None:
        piano = _piano()
        score = Score(events=[
            NoteEvent(0.0, 4.0, (name_to_midi("C3"), name_to_midi("G4")), (4.0, 1.0)),
        ])
        window = difficulty.keys_between(piano, name_to_midi("C4"), name_to_midi("C5"))
        mine, app = difficulty.split(score, piano, window)
        self.assertEqual(mine.events[0].durations, (1.0,))   # G4
        self.assertEqual(app.events[0].durations, (4.0,))    # C3 の保続はアプリ側で保たれる

    def test_unplayable_notes_go_to_the_app_so_nothing_vanishes(self) -> None:
        mapping = KeyMapping(name="t", note_to_key={60: "a"}, out_of_range="skip")
        score = Score(events=[NoteEvent(0.0, 1.0, (60, 62))])
        mine, app = difficulty.split(score, mapping, frozenset({"a"}))
        self.assertEqual(mine.events[0].midi_notes, (60,))
        self.assertEqual(app.events[0].midi_notes, (62,))


class MergeTest(unittest.TestCase):
    """split() の逆。合わせれば必ず原曲に戻る。伴奏を一緒に鳴らすときに使う。"""

    def test_split_then_merge_restores_the_original(self) -> None:
        piano = _piano()
        for hi in ("C4", "E4", "C5"):
            with self.subTest(hi=hi):
                window = difficulty.keys_between(piano, name_to_midi("C4"), name_to_midi(hi))
                mine, theirs = difficulty.split(_chorale(), piano, window)
                restored = difficulty.merge(mine, theirs)
                for src, got in zip(_chorale().events, restored.events):
                    self.assertEqual(got.midi_notes, tuple(sorted(src.midi_notes)))

    def test_merge_keeps_per_note_durations(self) -> None:
        piano = _piano()
        score = Score(events=[
            NoteEvent(0.0, 4.0, (name_to_midi("C3"), name_to_midi("G4")), (4.0, 1.0)),
        ])
        window = difficulty.keys_between(piano, name_to_midi("C4"), name_to_midi("C5"))
        merged = difficulty.merge(*difficulty.split(score, piano, window))
        self.assertEqual(merged.events[0].midi_notes, (name_to_midi("C3"), name_to_midi("G4")))
        self.assertEqual(merged.events[0].durations, (4.0, 1.0))
        self.assertEqual(merged.events[0].duration_beat, 4.0)

    def test_merge_keeps_rests(self) -> None:
        piano = _piano()
        window = difficulty.full_window(piano)
        merged = difficulty.merge(*difficulty.split(_chorale(), piano, window))
        self.assertTrue(merged.events[2].is_rest)

    def test_merge_rejects_unrelated_scores(self) -> None:
        with self.assertRaises(ValueError):
            difficulty.merge(_chorale(), Score(events=[]))


class VisualisationDataTest(unittest.TestCase):
    """窓を選ぶ前に見せる材料。見せずに選ばせてはいけない。"""

    def test_fingers_needed_warns_about_chords_inside_the_window(self) -> None:
        piano = _piano()
        window = difficulty.keys_between(piano, name_to_midi("C4"), name_to_midi("C5"))
        # 窓の中に E4+G4 と D4+B4 がある。窓が狭くても指は 2 本要る。
        self.assertEqual(difficulty.fingers_needed(_chorale(), piano, window), 2)

    def test_fingers_needed_without_a_window_is_the_whole_song(self) -> None:
        self.assertEqual(difficulty.fingers_needed(_chorale(), _piano()), 3)

    def test_one_key_window_always_needs_one_finger(self) -> None:
        piano = _piano()
        window = difficulty.keys_between(piano, name_to_midi("G4"), name_to_midi("G4"))
        self.assertEqual(difficulty.fingers_needed(_chorale(), piano, window), 1)

    def test_fingers_needed_on_empty_score(self) -> None:
        self.assertEqual(difficulty.fingers_needed(Score(events=[]), _piano()), 0)

    def test_key_usage_counts_each_sounding_note(self) -> None:
        usage = difficulty.key_usage(_do_re_mi(), _piano())
        self.assertEqual(sum(usage.values()), 8)
        self.assertEqual(set(usage.values()), {1})

    def test_key_usage_ignores_rests(self) -> None:
        usage = difficulty.key_usage(_chorale(), _piano())
        self.assertEqual(sum(usage.values()), 6)

    def test_keys_used_is_what_the_song_touches(self) -> None:
        piano = _piano()
        self.assertEqual(len(difficulty.keys_used(_do_re_mi(), piano)), 8)

    def test_note_share_tells_how_much_you_take_on(self) -> None:
        piano = _piano()
        window = difficulty.keys_between(piano, name_to_midi("C4"), name_to_midi("C5"))
        mine, total = difficulty.note_share(_chorale(), piano, window)
        self.assertEqual((mine, total), (4, 6))   # C3 と G3 はアプリ

    def test_folded_notes_land_inside_the_window(self) -> None:
        """音域外はオクターブ移調で畳まれる。遠い音が窓へ落ちてくる。可視化はそれを見せる。"""
        piano = _piano()
        window = difficulty.keys_between(piano, name_to_midi("C4"), name_to_midi("C5"))
        score = Score(events=[NoteEvent(0.0, 1.0, (name_to_midi("G6"),))])  # 音域の遥か上
        self.assertEqual(piano.resolve(name_to_midi("G6")), piano.resolve(name_to_midi("G4")))
        mine, _app = difficulty.split(score, piano, window)
        self.assertEqual(len(mine.events[0].midi_notes), 1)


class ThinChordTest(unittest.TestCase):
    """難易度の軸ではない。窓の中でさらに指を減らしたいときの任意の補助。"""

    def test_outer_keeps_melody_and_bass(self) -> None:
        self.assertEqual(difficulty.thin_chord((60, 64, 67), 2), (60, 67))

    def test_one_key_keeps_the_top(self) -> None:
        self.assertEqual(difficulty.thin_chord((60, 64, 67), 1), (67,))

    def test_top_strategy(self) -> None:
        self.assertEqual(difficulty.thin_chord((60, 64, 67), 2, "top"), (64, 67))

    def test_rest_stays_rest(self) -> None:
        self.assertEqual(difficulty.thin_chord((), 2), ())

    def test_zero_keys_rejected(self) -> None:
        with self.assertRaises(ValueError):
            difficulty.thin_chord((60,), 0)

    def test_folded_notes_cost_one_key(self) -> None:
        mapping = KeyMapping(name="t", note_to_key={60: "a", 62: "s"})
        self.assertEqual(difficulty.thin_chord((48, 60, 72), 1, mapping=mapping), (48, 60, 72))

    def test_thin_score_keeps_durations(self) -> None:
        score = Score(events=[NoteEvent(0.0, 4.0, (48, 64, 67), (4.0, 1.0, 1.0))])
        thinned = difficulty.thin_score(score, 1)
        self.assertEqual(thinned.events[0].midi_notes, (67,))
        self.assertEqual(thinned.events[0].durations, (1.0,))
        self.assertEqual(thinned.events[0].duration_beat, 1.0)


class NotMelodyExtractionTest(unittest.TestCase):
    """thin_chord は同時押しを減らすだけで、声部（メロディ）は追わない。

    ここは「バグ」ではなく仕様。skyline 法でメロディを取ろうとすると下記のとおり
    壊れるため、意図的にやっていない。
    """

    def test_arpeggio_is_untouched(self) -> None:
        alberti = Score(events=[
            NoteEvent(i * 0.5, 0.5, (n,), (0.5,))
            for i, n in enumerate([48, 55, 52, 55])
        ])
        thinned = difficulty.thin_score(alberti, 1)
        self.assertEqual(
            [e.midi_notes for e in thinned.events], [(48,), (55,), (52,), (55,)]
        )

    def test_sustained_melody_is_lost_after_its_onset(self) -> None:
        score = Score(events=[
            NoteEvent(0.0, 2.0, (48, 72), (0.5, 2.0)),
            NoteEvent(0.5, 0.5, (55,), (0.5,)),
            NoteEvent(1.0, 0.5, (52,), (0.5,)),
        ])
        thinned = difficulty.thin_score(score, 1)
        self.assertEqual([e.midi_notes for e in thinned.events], [(72,), (55,), (52,)])

    def test_inner_voice_melody_is_dropped(self) -> None:
        score = Score(events=[NoteEvent(0.0, 1.0, (48, 60, 79), (1.0, 1.0, 1.0))])
        self.assertEqual(difficulty.thin_score(score, 1).events[0].midi_notes, (79,))


if __name__ == "__main__":
    unittest.main()
