"""ocr モジュールの純ロジック（整形・行復元）のテスト。OCR 本体は呼ばない。"""

import unittest

from autoplaynotes.ocr import _rows_to_text, clean_number_text


class CleanNumberTextTest(unittest.TestCase):
    def test_basic_tokens_pass_through(self):
        self.assertEqual(clean_number_text("1 2 3 4 5 6 7"), "1 2 3 4 5 6 7")

    def test_digit_runs_are_split(self):
        self.assertEqual(clean_number_text("1234 567"), "1 2 3 4 5 6 7")

    def test_octave_marks_stay_attached(self):
        self.assertEqual(clean_number_text("1' 2'' 3,"), "1' 2'' 3,")

    def test_accidentals_stay_attached(self):
        self.assertEqual(clean_number_text("#1 b3"), "#1 b3")

    def test_chords_and_duration(self):
        self.assertEqual(clean_number_text("1+3+5 1:2 0:0.5"), "1+3+5 1:2 0:0.5")

    def test_rest_extension_bar(self):
        self.assertEqual(clean_number_text("1 - 0 | 2"), "1 - 0 | 2")

    def test_fullwidth_normalized(self):
        self.assertEqual(clean_number_text("１　２　３"), "1 2 3")
        self.assertEqual(clean_number_text("＃１ ｂ３ １＋５"), "#1 b3 1+5")

    def test_ocr_confusions_mapped(self):
        # l/I -> 1, O/o/○ -> 0, 長音・ダッシュ類 -> -
        self.assertEqual(clean_number_text("l I O o ○"), "1 1 0 0 0")
        self.assertEqual(clean_number_text("1 ー 2 — 3"), "1 - 2 - 3")
        self.assertEqual(clean_number_text("♯1 ♭3 1’"), "#1 b3 1'")

    def test_detached_symbols_rejoined(self):
        # OCR が単語分割した記号は音へ再結合される
        self.assertEqual(clean_number_text("# 1 b 3"), "#1 b3")
        self.assertEqual(clean_number_text("1 + 3 + 5"), "1+3+5")
        self.assertEqual(clean_number_text("1 : 2"), "1:2")
        self.assertEqual(clean_number_text("5 ' 5 '"), "5' 5'")
        self.assertEqual(clean_number_text("1 ' '"), "1''")

    def test_comma_not_rejoined(self):
        # "1、2、3" のような列挙をオクターブ下げと誤認しない
        self.assertEqual(clean_number_text("1、2、3"), "1 2 3")
        self.assertEqual(clean_number_text("7, 6,"), "7, 6,")

    def test_garbage_is_dropped(self):
        self.assertEqual(clean_number_text("あ 1 x 2 ！ 3 8 9"), "1 2 3")

    def test_line_structure_preserved(self):
        self.assertEqual(clean_number_text("1 2 3\n\nうた\n4 5 6"), "1 2 3\n4 5 6")

    def test_empty(self):
        self.assertEqual(clean_number_text(""), "")
        self.assertEqual(clean_number_text("認識できない文字だけ"), "")


class RowsToTextTest(unittest.TestCase):
    def test_sorted_by_y_then_x(self):
        entries = [
            (100, 10, 20, "4 5 6"),
            (10, 10, 20, "1 2 3"),
        ]
        self.assertEqual(_rows_to_text(entries), "1 2 3\n4 5 6")

    def test_same_row_merged_in_x_order(self):
        # y が行高の半分以内なら同じ段として x 順に結合される
        entries = [
            (12, 300, 20, "4 5"),
            (10, 10, 20, "1 2 3"),
            (60, 10, 20, "6 7"),
        ]
        self.assertEqual(_rows_to_text(entries), "1 2 3 4 5\n6 7")

    def test_empty(self):
        self.assertEqual(_rows_to_text([]), "")


if __name__ == "__main__":
    unittest.main()
