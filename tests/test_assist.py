"""補助演奏（演奏範囲は自分で弾き、アプリは範囲外だけをゲームへ送る）のテスト。

段0（全自動）から一歩出た人のためのモード。キーは飛ぶのでグレー側だが、
**アプリが送るキーとあなたが押すキーは全曲を通じて素**でなければならない。
交差すると、アプリの keyup があなたの音を切り、あなたの物理キーがアプリを妨げる。
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoplaynotes import config, difficulty, keywindow  # noqa: E402
from autoplaynotes.config import AppConfig  # noqa: E402
from autoplaynotes.keymap import PRESETS, name_to_midi  # noqa: E402
from autoplaynotes.model import NoteEvent, Score  # noqa: E402
from autoplaynotes.player import PlaybackOptions, Player  # noqa: E402


class _FakeSender:
    def __init__(self) -> None:
        self.pressed: list[str] = []

    def down(self, keys) -> None:
        self.pressed.extend(keys)

    def up(self, keys) -> None:
        pass

    def release_all(self) -> None:
        pass

    def validate(self, keys) -> None:
        pass


def _mapping():
    return PRESETS()["diatonic"]


def _score() -> Score:
    """低音 C3 の上でメロディが動く。"""
    return Score(tempo_bpm=120.0, events=[
        NoteEvent(0.0, 1.0, (name_to_midi("C3"), name_to_midi("C4"))),
        NoteEvent(1.0, 1.0, (name_to_midi("G4"),)),
        NoteEvent(2.0, 1.0, (name_to_midi("C3"), name_to_midi("E4"))),
    ])


def _window():
    return difficulty.keys_between(_mapping(), name_to_midi("C4"), name_to_midi("B4"))


def _keys_the_app_sends(score: Score) -> set[str]:
    sender = _FakeSender()
    actions, _skipped = Player(sender).build_actions(  # type: ignore[arg-type]
        score, _mapping(), PlaybackOptions(count_in_seconds=0.0)
    )
    return {a.keys[0] for a in actions if a.is_down}


class KeyDisjointnessTest(unittest.TestCase):
    """補助演奏の生命線。ここが破れると、両者が同じ物理キーを取り合う。"""

    def test_app_never_touches_your_keys(self) -> None:
        _mine, theirs = difficulty.split(_score(), _mapping(), _window())
        self.assertEqual(_keys_the_app_sends(theirs) & _window(), set())

    def test_app_sends_exactly_the_notes_outside_the_window(self) -> None:
        _mine, theirs = difficulty.split(_score(), _mapping(), _window())
        self.assertEqual(_keys_the_app_sends(theirs), {_mapping().resolve(name_to_midi("C3"))})

    def test_together_they_cover_the_whole_song(self) -> None:
        mine, theirs = difficulty.split(_score(), _mapping(), _window())
        your_keys = {_mapping().resolve(n) for e in mine.events for n in e.midi_notes}
        app_keys = _keys_the_app_sends(theirs)
        everything = {_mapping().resolve(n) for e in _score().events for n in e.midi_notes}
        self.assertEqual(your_keys | app_keys, everything)

    def test_holds_do_not_overlap_across_the_boundary(self) -> None:
        """低音を 4 拍伸ばしても、あなたのキーには影響しない。"""
        score = Score(tempo_bpm=120.0, events=[
            NoteEvent(0.0, 4.0, (name_to_midi("C3"), name_to_midi("C4")), (4.0, 1.0)),
            NoteEvent(1.0, 1.0, (name_to_midi("E4"),), (1.0,)),
        ])
        _mine, theirs = difficulty.split(score, _mapping(), _window())
        self.assertEqual(_keys_the_app_sends(theirs) & _window(), set())

    def test_every_window_keeps_the_key_sets_disjoint(self) -> None:
        mapping = _mapping()
        lo, hi = name_to_midi("C3"), name_to_midi("C5")
        for a in range(lo, hi + 1, 3):
            for b in range(a, hi + 1, 4):
                window = difficulty.keys_between(mapping, a, b)
                with self.subTest(window=sorted(window)):
                    _mine, theirs = difficulty.split(_score(), mapping, window)
                    self.assertEqual(_keys_the_app_sends(theirs) & window, set())


class AssistScoreTest(unittest.TestCase):
    """本物の gui.App._assist_score を呼ぶ。危険な状態では始めないこと。"""

    root: "object"

    @classmethod
    def setUpClass(cls) -> None:
        import customtkinter as ctk

        from autoplaynotes import theme

        theme.setup(dark=True)
        cls.root = ctk.CTk()
        cls.root.withdraw()  # type: ignore[attr-defined]
        cls.root.tk.eval("proc bgerror {msg} {}")  # type: ignore[attr-defined]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.root.destroy()  # type: ignore[attr-defined]

    def setUp(self) -> None:
        from autoplaynotes import gui

        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        for target in (config, gui):
            patcher = mock.patch.object(
                target, "config_path", lambda: os.path.join(self._dir.name, "c.json"),
                create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.warnings: list[tuple[str, str]] = []
        patcher = mock.patch.object(
            gui.messagebox, "showwarning",
            lambda title, message, **kw: self.warnings.append((title, message)))
        patcher.start()
        self.addCleanup(patcher.stop)

        cfg = AppConfig()
        cfg.first_run = False
        cfg.active_mapping = "diatonic"
        self.app = gui.App(self.root, cfg)  # type: ignore[arg-type]
        self.addCleanup(self.app.hotkeys.stop)

    def test_without_a_saved_window_it_refuses_and_says_why(self) -> None:
        self.assertIsNone(self.app._assist_score(_score(), _mapping()))
        self.assertIn("演奏範囲", self.warnings[0][0])

    def test_a_full_window_leaves_the_app_nothing_to_send(self) -> None:
        keywindow.save_window(self.app.config, _score(), difficulty.full_window(_mapping()))
        self.assertIsNone(self.app._assist_score(_score(), _mapping()))
        self.assertIn("アプリが弾く音がありません", self.warnings[0][0])

    def test_with_a_window_it_returns_only_the_outside_notes(self) -> None:
        keywindow.save_window(self.app.config, _score(), _window())
        theirs = self.app._assist_score(_score(), _mapping())
        self.assertIsNotNone(theirs)
        self.assertEqual(_keys_the_app_sends(theirs), {"Z"})   # C3 だけ
        self.assertEqual(self.warnings, [])

    def test_a_window_from_another_keyboard_is_not_silently_used(self) -> None:
        """保存済みのキーが今の鍵盤に無いなら未設定扱い。勝手に全自動へ落とさない。"""
        keywindow.save_window(self.app.config, _score(), frozenset({"存在しないキー"}))
        self.assertIsNone(self.app._assist_score(_score(), _mapping()))

    def test_editing_the_song_forgets_the_window(self) -> None:
        """曲キーは音数を含む。譜面を編集したら選び直してもらう。"""
        keywindow.save_window(self.app.config, _score(), _window())
        edited = Score(tempo_bpm=120.0, events=_score().events[:2])
        self.assertIsNone(self.app._assist_score(edited, _mapping()))


if __name__ == "__main__":
    unittest.main()
