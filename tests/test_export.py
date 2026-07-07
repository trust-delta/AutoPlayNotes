"""score_export（MIDI / MusicXML 書き出し）の往復テスト。"""

import os
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoplaynotes import musicxml_parser, score_export  # noqa: E402
from autoplaynotes.model import NoteEvent, Score  # noqa: E402


def _sample_score() -> Score:
    return Score(tempo_bpm=100, title="Test & <Song>", events=[
        NoteEvent(0.0, 1.0, (60,)),
        NoteEvent(1.0, 1.0, (62,)),
        NoteEvent(2.0, 2.0, (64, 67)),   # 和音
        NoteEvent(5.0, 1.0, (65,)),      # 4〜5 拍は休符
    ])


def _read_midi_notes(data: bytes) -> tuple[list[int], int]:
    """SMF type 0 を解析して note-on のノート番号一覧と分解能を返す。"""
    assert data[:4] == b"MThd"
    _, _fmt, _ntrk, div = struct.unpack(">IHHH", data[4:14])
    assert data[14:18] == b"MTrk"
    (tlen,) = struct.unpack(">I", data[18:22])
    track = data[22:22 + tlen]
    i = 0
    notes: list[int] = []
    status = 0

    def read_vlq(pos: int) -> tuple[int, int]:
        value = 0
        while True:
            b = track[pos]
            pos += 1
            value = (value << 7) | (b & 0x7F)
            if not (b & 0x80):
                return value, pos

    while i < len(track):
        _delta, i = read_vlq(i)
        b = track[i]
        if b == 0xFF:  # メタイベント
            i += 2  # 0xFF, type
            length, i = read_vlq(i)
            i += length
            continue
        if b & 0x80:
            status = b
            i += 1
        note = track[i]
        vel = track[i + 1]
        i += 2
        if status == 0x90 and vel > 0:
            notes.append(note)
    return notes, div


class TestMidiExport(unittest.TestCase):
    def test_structure_and_notes(self) -> None:
        data = score_export.score_to_midi_bytes(_sample_score())
        notes, div = _read_midi_notes(data)
        self.assertEqual(div, 480)
        self.assertEqual(sorted(notes), [60, 62, 64, 65, 67])

    def test_tempo_from_score(self) -> None:
        data = score_export.score_to_midi_bytes(_sample_score())
        # テンポ meta (FF 51 03) が存在する
        self.assertIn(b"\xff\x51\x03", data)


class TestMusicXmlExport(unittest.TestCase):
    def test_wellformed(self) -> None:
        xml = score_export.score_to_musicxml(_sample_score())
        ET.fromstring(xml)  # 例外なしなら整形式

    def test_roundtrip_via_parser(self) -> None:
        xml = score_export.score_to_musicxml(_sample_score())
        with tempfile.NamedTemporaryFile(
            "w", suffix=".musicxml", delete=False, encoding="utf-8"
        ) as f:
            f.write(xml)
            path = f.name
        try:
            score = musicxml_parser.build_score(
                path, selected_keys=None, monophonic=False, octave_shift=0
            )
        finally:
            os.unlink(path)
        got = [(round(e.start_beat, 2), round(e.duration_beat, 2), e.midi_notes)
               for e in score.events]
        self.assertEqual(got, [
            (0.0, 1.0, (60,)),
            (1.0, 1.0, (62,)),
            (2.0, 2.0, (64, 67)),
            (5.0, 1.0, (65,)),
        ])


if __name__ == "__main__":
    unittest.main()
