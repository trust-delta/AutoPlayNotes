"""窓の選択画面と suggest_window のテスト。

窓は同時押しを許容するので、選ぶ前に代償（必要な指の本数）を見せなければ意味が無い。
ダイアログが出す数字が譜面の実態と一致していることを、ここで担保する。
"""

import os
import sys
import tkinter as tk
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoplaynotes import difficulty  # noqa: E402
from autoplaynotes.keymap import PRESETS, KeyMapping, name_to_midi  # noqa: E402
from autoplaynotes.model import NoteEvent, Score  # noqa: E402


def _diatonic() -> KeyMapping:
    return PRESETS()["diatonic"]


def _twinkle() -> Score:
    """メロディは C4〜A4、4 音ごとに C3+E3 の伴奏が重なる。"""
    melody = [60, 60, 67, 67, 69, 69, 67, 65, 65, 64, 64, 62, 62, 60]
    return Score(events=[
        NoteEvent(i * 0.5, 0.5, (n,) if i % 4 else (n, 48, 52), ())
        for i, n in enumerate(melody)
    ])


class SuggestWindowTest(unittest.TestCase):
    def test_one_finger_suggestion_lands_on_the_melody(self) -> None:
        """メロディ検出はしていない。音の密度と指の制約だけで、結果的に旋律を選ぶ。"""
        window = difficulty.suggest_window(_twinkle(), _diatonic(), 1)
        mapping = _diatonic()
        pitches = sorted(p for k, p in difficulty.keyboard(mapping) if k in window)
        self.assertEqual(pitches[0], name_to_midi("C4"))
        self.assertEqual(pitches[-1], name_to_midi("A4"))

    def test_suggestion_respects_the_finger_budget(self) -> None:
        for budget in (1, 2, 3):
            with self.subTest(budget=budget):
                window = difficulty.suggest_window(_twinkle(), _diatonic(), budget)
                self.assertLessEqual(
                    difficulty.fingers_needed(_twinkle(), _diatonic(), window), budget
                )

    def test_more_fingers_never_means_fewer_notes(self) -> None:
        previous = -1
        for budget in (1, 2, 3):
            window = difficulty.suggest_window(_twinkle(), _diatonic(), budget)
            mine, _total = difficulty.note_share(_twinkle(), _diatonic(), window)
            self.assertGreaterEqual(mine, previous)
            previous = mine

    def test_generous_budget_takes_every_note(self) -> None:
        window = difficulty.suggest_window(_twinkle(), _diatonic(), 9)
        mine, total = difficulty.note_share(_twinkle(), _diatonic(), window)
        self.assertEqual(mine, total)

    def test_ties_prefer_the_narrower_window(self) -> None:
        """覚えるキーは少ないほうが易しい。同じ音数なら狭い窓。"""
        score = Score(events=[NoteEvent(0.0, 1.0, (name_to_midi("G4"),))])
        window = difficulty.suggest_window(score, _diatonic(), 1)
        self.assertEqual(len(window), 1)

    def test_empty_score_suggests_nothing(self) -> None:
        self.assertEqual(difficulty.suggest_window(Score(events=[]), _diatonic()), frozenset())

    def test_rests_only_score_suggests_nothing(self) -> None:
        score = Score(events=[NoteEvent(0.0, 1.0, ())])
        self.assertEqual(difficulty.suggest_window(score, _diatonic()), frozenset())


class PersistenceTest(unittest.TestCase):
    """演奏範囲は曲ごとに保存する。練習メモと同じ曲キーに相乗りする。"""

    def setUp(self) -> None:
        from autoplaynotes.config import AppConfig

        self.config = AppConfig()

    def test_unknown_song_has_no_window(self) -> None:
        from autoplaynotes import keywindow

        self.assertIsNone(keywindow.load_window(self.config, _twinkle(), _diatonic()))

    def test_round_trip(self) -> None:
        from autoplaynotes import keywindow

        window = difficulty.suggest_window(_twinkle(), _diatonic(), 1)
        keywindow.save_window(self.config, _twinkle(), window)
        self.assertEqual(keywindow.load_window(self.config, _twinkle(), _diatonic()), window)

    def test_window_from_another_mapping_is_discarded(self) -> None:
        """キー割り当てを変えたら、保存されたキー名は今の鍵盤に無い。勝手に狭めない。"""
        from autoplaynotes import keywindow

        keywindow.save_window(self.config, _twinkle(), frozenset({"存在しないキー"}))
        self.assertIsNone(keywindow.load_window(self.config, _twinkle(), _diatonic()))

    def test_describe_window(self) -> None:
        from autoplaynotes import keywindow

        mapping = _diatonic()
        window = difficulty.keys_between(mapping, name_to_midi("C4"), name_to_midi("A4"))
        self.assertEqual(keywindow.describe_window(mapping, window), "C4〜A4（6鍵）")
        self.assertEqual(
            keywindow.describe_window(mapping, difficulty.full_window(mapping)), "原曲どおり"
        )
        self.assertEqual(keywindow.describe_window(mapping, frozenset()), "なし")


class KeyWindowDialogTest(unittest.TestCase):
    root: "object"

    @classmethod
    def setUpClass(cls) -> None:
        import customtkinter as ctk

        cls.root = ctk.CTk()
        cls.root.withdraw()  # type: ignore[attr-defined]
        # 破棄済みウィジェットの after 予約が Tcl の背景エラーを出す。実害は無い。
        cls.root.tk.eval("proc bgerror {msg} {}")  # type: ignore[attr-defined]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.root.destroy()  # type: ignore[attr-defined]

    def _dialog(self, score: Score | None = None):
        from autoplaynotes import keywindow

        self.applied: list[frozenset[str]] = []
        dialog = keywindow.KeyWindowDialog(
            self.root, score or _twinkle(), _diatonic(),  # type: ignore[arg-type]
            on_apply=self.applied.append,
        )
        self.addCleanup(dialog.destroy)
        return dialog

    @staticmethod
    def _drag(dialog, lo_note: str, hi_note: str) -> None:
        mapping = _diatonic()
        lo = dialog._index[mapping.note_to_key[name_to_midi(lo_note)]]
        hi = dialog._index[mapping.note_to_key[name_to_midi(hi_note)]]
        press, move = tk.Event(), tk.Event()
        press.x, move.x = dialog._x(lo) + 2, dialog._x(hi) + 2
        dialog._on_press(press)
        dialog._on_drag(move)

    def test_opens_with_the_whole_keyboard(self) -> None:
        dialog = self._dialog()
        self.assertEqual(dialog._window(), difficulty.full_window(_diatonic()))

    def test_initial_window_is_honoured(self) -> None:
        from autoplaynotes import keywindow

        window = difficulty.keys_between(_diatonic(), name_to_midi("C4"), name_to_midi("C5"))
        dialog = keywindow.KeyWindowDialog(
            self.root, _twinkle(), _diatonic(),  # type: ignore[arg-type]
            on_apply=lambda w: None, initial=window,
        )
        self.addCleanup(dialog.destroy)
        self.assertEqual(dialog._window(), window)

    def test_drag_selects_a_contiguous_range(self) -> None:
        dialog = self._dialog()
        self._drag(dialog, "C4", "A4")
        self.assertEqual(len(dialog._window()), 6)

    def test_drag_backwards_works(self) -> None:
        dialog = self._dialog()
        self._drag(dialog, "A4", "C4")
        self.assertEqual(len(dialog._window()), 6)

    def test_click_outside_the_keyboard_is_clamped(self) -> None:
        dialog = self._dialog()
        self.assertEqual(dialog._cell_at(-999), 0)
        self.assertEqual(dialog._cell_at(99999), len(dialog.layout) - 1)

    def test_stats_match_the_score(self) -> None:
        dialog = self._dialog()
        self._drag(dialog, "C4", "A4")
        text = dialog._stats.get()
        self.assertIn("C4〜A4", text)
        self.assertIn("6 鍵", text)
        self.assertIn("必要な指 1 本", text)
        self.assertIn("あなたが弾く音 14", text)
        self.assertIn("アプリ 8", text)

    def test_stats_warn_when_the_window_needs_more_fingers(self) -> None:
        """窓は同時押しを許容する。選ぶ前に代償が見えていること。"""
        dialog = self._dialog()
        self.assertIn("必要な指 3 本", dialog._stats.get())

    def test_usage_counts_every_sounding_note(self) -> None:
        dialog = self._dialog()
        self.assertEqual(sum(dialog.usage.values()), 22)

    def test_suggest_button_selects_the_melody(self) -> None:
        dialog = self._dialog()
        dialog._select_keys(difficulty.suggest_window(_twinkle(), _diatonic(), 1))
        self.assertIn("必要な指 1 本", dialog._stats.get())
        self.assertIn("あなたが弾く音 14", dialog._stats.get())

    def test_apply_returns_the_selected_window(self) -> None:
        dialog = self._dialog()
        self._drag(dialog, "C4", "A4")
        window = dialog._window()
        dialog._apply()
        self.assertEqual(self.applied, [window])

    def test_cancel_returns_nothing(self) -> None:
        dialog = self._dialog()
        dialog.destroy()
        self.assertEqual(self.applied, [])

    def test_empty_mapping_does_not_crash(self) -> None:
        from autoplaynotes import keywindow

        dialog = keywindow.KeyWindowDialog(
            self.root, _twinkle(), KeyMapping(name="empty", note_to_key={}),  # type: ignore[arg-type]
            on_apply=lambda w: None,
        )
        self.addCleanup(dialog.destroy)
        self.assertEqual(dialog._window(), frozenset())
        self.assertIn("キー割り当てが空", dialog._stats.get())

    def test_silent_score_does_not_crash(self) -> None:
        dialog = self._dialog(Score(events=[NoteEvent(0.0, 1.0, ())]))
        self.assertEqual(dialog.usage, {})
        self.assertIn("必要な指 0 本", dialog._stats.get())


if __name__ == "__main__":
    unittest.main()
