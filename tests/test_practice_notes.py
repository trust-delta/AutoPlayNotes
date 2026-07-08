"""練習メモ（practice_notes）の純ロジックと config フィールドのテスト。"""

import unittest
from dataclasses import asdict

from autoplaynotes import practice_notes as pn
from autoplaynotes.config import AppConfig


class SongKeyTest(unittest.TestCase):
    def test_key_includes_title_and_count(self) -> None:
        self.assertEqual(pn.song_key("きらきら星", 14), "きらきら星#14")

    def test_blank_title_defaults(self) -> None:
        self.assertEqual(pn.song_key("", 3), "無題#3")
        self.assertEqual(pn.song_key("   ", 3), "無題#3")

    def test_same_song_same_key(self) -> None:
        # 同じ曲（タイトル＋音数）なら別入口でも同じキー＝メモ復元される
        self.assertEqual(pn.song_key("曲A", 20), pn.song_key("曲A", 20))
        self.assertNotEqual(pn.song_key("曲A", 20), pn.song_key("曲A", 21))


class NoteCrudTest(unittest.TestCase):
    def setUp(self) -> None:
        self.store: dict = {}
        self.key = pn.song_key("曲", 5)

    def test_add_get_count(self) -> None:
        pn.add_note(self.store, self.key, pn.PracticeNote(2.0, "難所", "ここ難しい", "t1"))
        pn.add_note(self.store, self.key, pn.PracticeNote(-1.0, "テンポ", "0.75で", "t2"))
        self.assertEqual(pn.note_count(self.store, self.key), 2)
        notes = pn.get_notes(self.store, self.key)
        self.assertEqual(notes[0].tag, "難所")
        self.assertEqual(notes[1].beat, -1.0)

    def test_count_zero_for_unknown(self) -> None:
        self.assertEqual(pn.note_count(self.store, "無い#0"), 0)
        self.assertEqual(pn.get_notes(self.store, "無い#0"), [])

    def test_delete_and_key_cleanup(self) -> None:
        pn.add_note(self.store, self.key, pn.PracticeNote(1.0, "指使い", "またぎ", "t"))
        self.assertTrue(pn.delete_note(self.store, self.key, 0))
        self.assertEqual(pn.note_count(self.store, self.key), 0)
        self.assertNotIn(self.key, self.store)  # 空になったらキーごと消える

    def test_delete_out_of_range(self) -> None:
        self.assertFalse(pn.delete_note(self.store, self.key, 0))
        pn.add_note(self.store, self.key, pn.PracticeNote(1.0, "x", "y", "t"))
        self.assertFalse(pn.delete_note(self.store, self.key, 5))
        self.assertEqual(pn.note_count(self.store, self.key), 1)

    def test_roundtrip(self) -> None:
        note = pn.PracticeNote(3.5, "暗譜", "サビ", "2026-07-08 10:00")
        self.assertEqual(pn.PracticeNote.from_dict(note.to_dict()), note)

    def test_from_dict_defaults(self) -> None:
        note = pn.PracticeNote.from_dict({})
        self.assertEqual(note.beat, -1.0)
        self.assertEqual(note.tag, "")

    def test_summary(self) -> None:
        s = pn.PracticeNote(2.0, "難所", "指またぎ", "t").summary()
        self.assertIn("難所", s)
        self.assertIn("指またぎ", s)
        self.assertIn("2.0", s)
        s2 = pn.PracticeNote(-1.0, "", "", "t").summary()
        self.assertIn("位置なし", s2)
        self.assertIn("(メモなし)", s2)


class ConfigFieldTest(unittest.TestCase):
    def test_default_empty(self) -> None:
        self.assertEqual(AppConfig().practice_notes, {})

    def test_asdict_includes_field(self) -> None:
        # save() は asdict(self) を JSON 化するので、フィールドが載ることを確認
        config = AppConfig()
        pn.add_note(config.practice_notes, pn.song_key("曲", 3),
                    pn.PracticeNote(1.0, "難所", "メモ", "t"))
        data = asdict(config)
        self.assertIn("practice_notes", data)
        self.assertEqual(data["practice_notes"]["曲#3"][0]["tag"], "難所")


if __name__ == "__main__":
    unittest.main()
