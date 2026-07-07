"""musicxml_parser のテスト（手書きの MusicXML 文字列で純ロジックを検証）。"""

import os
import tempfile
import unittest
import zipfile

from autoplaynotes.musicxml_parser import (
    build_score,
    inspect_musicxml,
    is_musicxml_path,
)


def _note(step, octave, duration, alter=None, chord=False, ties=()):
    alter_xml = f"<alter>{alter}</alter>" if alter is not None else ""
    chord_xml = "<chord/>" if chord else ""
    tie_xml = "".join(f'<tie type="{t}"/>' for t in ties)
    return (
        f"<note>{chord_xml}<pitch><step>{step}</step>{alter_xml}"
        f"<octave>{octave}</octave></pitch><duration>{duration}</duration>{tie_xml}</note>"
    )


def _rest(duration):
    return f"<note><rest/><duration>{duration}</duration></note>"


def _wrap(measures_p1, measures_p2=None, title="Test Song"):
    parts = f'<part id="P1">{measures_p1}</part>'
    part_list = '<score-part id="P1"><part-name>Melody</part-name></score-part>'
    if measures_p2 is not None:
        parts += f'<part id="P2">{measures_p2}</part>'
        part_list += '<score-part id="P2"><part-name>Drums</part-name></score-part>'
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<score-partwise version="3.1"><work><work-title>{title}</work-title></work>'
        f"<part-list>{part_list}</part-list>{parts}</score-partwise>"
    )


class MusicXmlTest(unittest.TestCase):
    def _write(self, content, suffix=".musicxml"):
        fd, path = tempfile.mkstemp(suffix=suffix, dir=self._dir.name)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._dir.cleanup()

    def test_extension_detection(self):
        self.assertTrue(is_musicxml_path("a.musicxml"))
        self.assertTrue(is_musicxml_path("A.MXL"))
        self.assertTrue(is_musicxml_path("b.xml"))
        self.assertFalse(is_musicxml_path("c.mid"))

    def test_simple_melody(self):
        xml = _wrap(
            '<measure number="1"><attributes><divisions>2</divisions></attributes>'
            '<sound tempo="90"/>'
            + _note("C", 4, 2) + _note("E", 4, 2) + _rest(2) + _note("G", 4, 2)
            + "</measure>"
            '<measure number="2">' + _note("C", 5, 4, alter=1) + "</measure>"
        )
        score = build_score(self._write(xml))
        self.assertEqual(score.tempo_bpm, 90.0)
        self.assertEqual(score.title, "Test Song")
        self.assertEqual(
            [(e.start_beat, e.duration_beat, e.midi_notes) for e in score.events],
            [(0.0, 1.0, (60,)), (1.0, 1.0, (64,)), (3.0, 1.0, (67,)), (4.0, 2.0, (73,))],
        )

    def test_chord_grouping(self):
        xml = _wrap(
            '<measure number="1"><attributes><divisions>2</divisions></attributes>'
            + _note("C", 4, 2) + _note("E", 4, 2, chord=True) + _note("G", 4, 2, chord=True)
            + _note("D", 4, 2) + "</measure>"
        )
        score = build_score(self._write(xml))
        self.assertEqual(score.events[0].midi_notes, (60, 64, 67))
        self.assertEqual(score.events[1].start_beat, 1.0)
        self.assertEqual(score.events[1].midi_notes, (62,))

    def test_tie_merged_across_measures(self):
        xml = _wrap(
            '<measure number="1"><attributes><divisions>2</divisions></attributes>'
            + _note("G", 4, 4, ties=("start",)) + "</measure>"
            '<measure number="2">' + _note("G", 4, 4, ties=("stop",)) + _note("A", 4, 2)
            + "</measure>"
        )
        score = build_score(self._write(xml))
        self.assertEqual(len(score.events), 2)
        self.assertEqual(score.events[0].midi_notes, (67,))
        self.assertEqual(score.events[0].duration_beat, 4.0)
        self.assertEqual(score.events[1].start_beat, 4.0)

    def test_two_voices_with_backup(self):
        xml = _wrap(
            '<measure number="1"><attributes><divisions>1</divisions></attributes>'
            + _note("C", 5, 1) + _note("D", 5, 1)
            + "<backup><duration>2</duration></backup>"
            + _note("C", 3, 2) + "</measure>"
        )
        score = build_score(self._write(xml))
        self.assertEqual(score.events[0].midi_notes, (48, 72))  # 同時開始は和音に統合
        self.assertEqual(score.events[0].duration_beat, 2.0)    # 長い方を採用
        self.assertEqual(score.events[1].start_beat, 1.0)
        self.assertEqual(score.events[1].midi_notes, (74,))

    def test_leading_rest_trimmed(self):
        xml = _wrap(
            '<measure number="1"><attributes><divisions>1</divisions></attributes>'
            + _rest(2) + _note("C", 4, 1) + "</measure>"
        )
        score = build_score(self._write(xml))
        self.assertEqual(score.events[0].start_beat, 0.0)

    def test_monophonic_and_octave_shift(self):
        xml = _wrap(
            '<measure number="1"><attributes><divisions>1</divisions></attributes>'
            + _note("C", 4, 1) + _note("E", 4, 1, chord=True) + _note("G", 4, 1, chord=True)
            + "</measure>"
        )
        path = self._write(xml)
        score = build_score(path, monophonic=True)
        self.assertEqual(score.events[0].midi_notes, (67,))  # 最高音のみ
        score = build_score(path, octave_shift=-1)
        self.assertEqual(score.events[0].midi_notes, (48, 52, 55))

    def test_inspect_parts_and_drum(self):
        drums = (
            '<measure number="1"><attributes><divisions>1</divisions></attributes>'
            "<note><unpitched><display-step>C</display-step>"
            "<display-octave>4</display-octave></unpitched><duration>1</duration></note>"
            "</measure>"
        )
        melody = (
            '<measure number="1"><attributes><divisions>1</divisions></attributes>'
            + _note("C", 4, 1) + _note("G", 5, 1) + "</measure>"
        )
        path = self._write(_wrap(melody, measures_p2=drums))
        info = inspect_musicxml(path)
        self.assertEqual(len(info.parts), 2)
        self.assertEqual(info.parts[0].name, "Melody")
        self.assertEqual(info.parts[0].note_count, 2)
        self.assertFalse(info.parts[0].is_drum)
        self.assertTrue(info.parts[1].is_drum)
        # 既定（選択なし）では打楽器パートは除外される
        score = build_score(path)
        self.assertEqual(len(score.events), 2)
        # パート選択
        score = build_score(path, selected_keys={(0, 0)})
        self.assertEqual(len(score.events), 2)

    def test_mxl_zip(self):
        xml = _wrap(
            '<measure number="1"><attributes><divisions>1</divisions></attributes>'
            + _note("C", 4, 1) + "</measure>"
        )
        path = os.path.join(self._dir.name, "song.mxl")
        container = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<container><rootfiles><rootfile full-path="song.musicxml"/></rootfiles></container>'
        )
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("META-INF/container.xml", container)
            zf.writestr("song.musicxml", xml)
        score = build_score(path)
        self.assertEqual(score.events[0].midi_notes, (60,))

    def test_invalid_root_raises(self):
        path = self._write("<not-music/>")
        with self.assertRaises(ValueError):
            build_score(path)


if __name__ == "__main__":
    unittest.main()
