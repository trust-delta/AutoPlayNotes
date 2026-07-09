"""練習モード（リズム）のロングノート判定テスト。

対象のゲーム内楽器はキーを押している間だけ鳴るので、長い音は「叩く」のではなく
「押し続けて、正しいところで離す」。従来は落ちノーツのテールを描いておきながら
<KeyPress> しか見ておらず、離鍵は一切判定していなかった。

判定の芯は GUI に依存しない純粋関数（is_long_note / judge_release）に置く。
押下→離鍵の一連の流れは、ウィンドウを実際に組み立てて時計を差し替えて検証する。
"""

import os
import sys
import time
import tkinter as tk
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoplaynotes import practice  # noqa: E402
from autoplaynotes.keymap import KeyMapping  # noqa: E402
from autoplaynotes.model import NoteEvent, Score  # noqa: E402


class JudgeReleaseTest(unittest.TestCase):
    """離鍵の判定は GUI 無しで検証できる。"""

    def test_exact_release_is_perfect(self) -> None:
        self.assertEqual(practice.judge_release(0.0), ("Perfect", 100))

    def test_slightly_off_is_good(self) -> None:
        judgment, _points = practice.judge_release(0.10)
        self.assertEqual(judgment, "Good")

    def test_releasing_too_early_is_a_miss(self) -> None:
        """早く離すと音が途切れる。"""
        self.assertEqual(practice.judge_release(-0.30), ("Miss", 0))

    def test_forgetting_to_release_is_a_miss(self) -> None:
        """離し忘れると鳴り続ける。"""
        self.assertEqual(practice.judge_release(0.30), ("Miss", 0))

    def test_window_is_symmetric(self) -> None:
        self.assertEqual(practice.judge_release(-0.14)[0], practice.judge_release(0.14)[0])


class IsLongNoteTest(unittest.TestCase):
    def test_short_note_needs_no_release(self) -> None:
        self.assertFalse(practice.is_long_note(0.1))

    def test_long_note_needs_release(self) -> None:
        self.assertTrue(practice.is_long_note(1.0))


class _WindowTest(unittest.TestCase):
    """実際に PracticeWindow を組み立てる（mainloop は回さない）。"""

    root: "object"

    @classmethod
    def setUpClass(cls) -> None:
        import customtkinter as ctk

        cls.root = ctk.CTk()
        cls.root.withdraw()  # type: ignore[attr-defined]
        # PracticeWindow と customtkinter は after() でコールバックを予約する。
        # ウィンドウを破棄すると予約だけが残り、Tcl が背景エラーを吐く。テストの
        # 出力を汚すだけで実害は無いので黙らせる。
        cls.root.tk.eval("proc bgerror {msg} {}")  # type: ignore[attr-defined]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.root.destroy()  # type: ignore[attr-defined]

    def _window(self, score: Score, mapping: KeyMapping) -> practice.PracticeWindow:
        win = practice.PracticeWindow(self.root, score, mapping)  # type: ignore[arg-type]
        self.addCleanup(win.destroy)
        return win

    @staticmethod
    def _press(win: practice.PracticeWindow, char: str) -> None:
        event = tk.Event()
        event.char = char
        event.keysym = char
        win._on_key(event)

    @staticmethod
    def _release(win: practice.PracticeWindow, char: str) -> None:
        event = tk.Event()
        event.char = char
        event.keysym = char
        win._on_key_release(event)

    @staticmethod
    def _set_clock(win: practice.PracticeWindow, seconds: float) -> None:
        """「開始から seconds 秒経った」状態にする。"""
        win._running = True
        win._t0 = time.perf_counter() - seconds


def _mapping() -> KeyMapping:
    return KeyMapping(name="t", note_to_key={60: "a", 62: "s"})


def _score(*events: NoteEvent) -> Score:
    # BPM 60 → 1 拍 = 1 秒
    return Score(tempo_bpm=60.0, events=list(events))


class BuildNotesTest(_WindowTest):
    def test_per_note_durations_reach_the_lanes(self) -> None:
        win = self._window(_score(NoteEvent(0.0, 2.0, (60, 62), (2.0, 0.5))), _mapping())
        durations = {n.lane: n.dur_beat for n in win._notes}
        self.assertEqual(durations, {0: 2.0, 1: 0.5})

    def test_notes_folded_onto_one_lane_are_merged(self) -> None:
        """C3 は移調で C4 と同じキーに落ちる。1 レーンに 2 つ置くと判定が二重になる。"""
        win = self._window(_score(NoteEvent(0.0, 4.0, (48, 60), (4.0, 1.0))), _mapping())
        self.assertEqual(len(win._notes), 1)
        self.assertEqual(win._notes[0].dur_beat, 4.0)  # 長い方が残る


class LongNoteJudgmentTest(_WindowTest):
    def _long_note_window(self) -> practice.PracticeWindow:
        # レーン 'a' に 2 秒（=2拍）のロングノート
        return self._window(_score(NoteEvent(0.0, 2.0, (60,), (2.0,))), _mapping())

    def test_press_then_release_on_time_scores_twice(self) -> None:
        win = self._long_note_window()
        self._set_clock(win, 0.0)
        self._press(win, "a")
        self.assertEqual(win._counts["Perfect"], 1)
        self.assertTrue(win._notes[0].hold_pending)

        self._set_clock(win, 2.0)
        self._release(win, "a")
        self.assertEqual(win._counts["Perfect"], 2)   # 押下 + 離鍵
        self.assertEqual(win._counts["Miss"], 0)
        self.assertTrue(win._notes[0].hold_ok)
        self.assertFalse(win._notes[0].hold_pending)

    def test_releasing_too_early_breaks_the_combo(self) -> None:
        win = self._long_note_window()
        self._set_clock(win, 0.0)
        self._press(win, "a")
        self.assertEqual(win._combo, 1)

        self._set_clock(win, 1.0)   # 1 秒早く離した
        self._release(win, "a")
        self.assertEqual(win._counts["Miss"], 1)
        self.assertEqual(win._combo, 0)
        self.assertTrue(win._notes[0].hold_failed)

    def test_key_repeat_is_not_a_second_hit(self) -> None:
        """押しっぱなしにすると OS がキーリピートを送る。打鍵として数えてはいけない。"""
        win = self._long_note_window()
        self._set_clock(win, 0.0)
        self._press(win, "a")
        for _ in range(5):
            self._press(win, "a")   # OS のリピート
        self.assertEqual(sum(win._counts.values()), 1)
        self.assertTrue(win._notes[0].hold_pending)

    def test_release_without_press_is_ignored(self) -> None:
        win = self._long_note_window()
        self._set_clock(win, 5.0)
        self._release(win, "a")
        self.assertEqual(sum(win._counts.values()), 0)

    def test_unknown_key_is_ignored(self) -> None:
        win = self._long_note_window()
        self._set_clock(win, 0.0)
        self._press(win, "q")
        self._release(win, "q")
        self.assertEqual(sum(win._counts.values()), 0)


class ShortNoteJudgmentTest(_WindowTest):
    def test_short_note_completes_on_press(self) -> None:
        win = self._window(_score(NoteEvent(0.0, 0.1, (60,), (0.1,))), _mapping())
        self._set_clock(win, 0.0)
        self._press(win, "a")
        self.assertFalse(win._notes[0].hold_pending)
        self.assertEqual(win._held, {})

    def test_short_note_release_adds_no_judgment(self) -> None:
        win = self._window(_score(NoteEvent(0.0, 0.1, (60,), (0.1,))), _mapping())
        self._set_clock(win, 0.0)
        self._press(win, "a")
        self._release(win, "a")
        self.assertEqual(sum(win._counts.values()), 1)


class ResetTest(_WindowTest):
    def test_reset_clears_held_notes(self) -> None:
        win = self._window(_score(NoteEvent(0.0, 2.0, (60,), (2.0,))), _mapping())
        self._set_clock(win, 0.0)
        self._press(win, "a")
        self.assertEqual(len(win._held), 1)

        win._running = False
        win._reset_rhythm_state()
        self.assertEqual(win._held, {})
        self.assertEqual(win._down_chars, set())
        self.assertFalse(win._notes[0].hold_pending)

    def test_reset_allows_pressing_again(self) -> None:
        """リピート抑止の集合が残っていると、リトライで打鍵が効かなくなる。"""
        win = self._window(_score(NoteEvent(0.0, 2.0, (60,), (2.0,))), _mapping())
        self._set_clock(win, 0.0)
        self._press(win, "a")
        win._running = False
        win._reset_rhythm_state()

        self._set_clock(win, 0.0)
        self._press(win, "a")
        self.assertEqual(sum(win._counts.values()), 1)


if __name__ == "__main__":
    unittest.main()
