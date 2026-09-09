"""自動演奏から練習への導線（onboarding）のテスト。

⚠️ この層は「画面には出ているので、壊れても動いて見える」。タブの並びが元へ戻る・
誘いが出っぱなしになる／二度と出ない、はどれも例外を投げずに起こる ∴ 判断を
純関数へ出したうえで、ここで固定する（→ docs/aims/practice-onboarding.md）。
"""

import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoplaynotes import config as config_mod  # noqa: E402
from autoplaynotes import onboarding  # noqa: E402
from autoplaynotes.config import AppConfig  # noqa: E402
from autoplaynotes.keymap import KeyMapping  # noqa: E402
from autoplaynotes.model import NoteEvent, Score  # noqa: E402


def _mapping(notes=(60, 62, 64)) -> KeyMapping:
    return KeyMapping(name="テスト", note_to_key={n: chr(ord("a") + i) for i, n in enumerate(notes)},
                      out_of_range="skip")


def _score(title: str = "きらきら星", notes: int = 3) -> Score:
    events = [NoteEvent(start_beat=float(i), duration_beat=1.0, midi_notes=(60,))
              for i in range(notes)]
    return Score(title=title, tempo_bpm=120.0, events=events)


class TabOrderTest(unittest.TestCase):
    def test_practice_comes_before_play(self) -> None:
        self.assertEqual(onboarding.TAB_ORDER[0], onboarding.TAB_PRACTICE)
        self.assertEqual(onboarding.TAB_ORDER[1], onboarding.TAB_PLAY)

    def test_auto_play_is_not_removed(self) -> None:
        """自動演奏は消さない・隠さない。並べ替えるだけである。"""
        self.assertIn(onboarding.TAB_PLAY, onboarding.TAB_ORDER)
        self.assertEqual(len(set(onboarding.TAB_ORDER)), len(onboarding.TAB_ORDER))
        self.assertEqual(len(onboarding.TAB_ORDER), 5)

    def test_startup_defaults_to_practice(self) -> None:
        self.assertEqual(onboarding.startup_tab(""), onboarding.TAB_PRACTICE)

    def test_startup_respects_the_last_tab(self) -> None:
        # 毎回 練習 へ引き戻すのは説教になる ∴ 選んだ人の選択を優先する
        self.assertEqual(onboarding.startup_tab(onboarding.TAB_PLAY), onboarding.TAB_PLAY)
        self.assertEqual(onboarding.startup_tab(onboarding.TAB_LOG), onboarding.TAB_LOG)

    def test_unknown_tab_falls_back(self) -> None:
        # 旧版の設定やタブ改名で消えた名前を渡しても、起動を壊さない
        self.assertEqual(onboarding.startup_tab("🎹 演奏（旧）"), onboarding.TAB_PRACTICE)


class ShouldInviteTest(unittest.TestCase):
    def _kwargs(self, **over):
        base = dict(stopped=False, playlist_active=False, assist=False,
                    enabled=True, note_count=22, already_invited=False)
        base.update(over)
        return base

    def test_invites_after_a_finished_auto_play(self) -> None:
        self.assertTrue(onboarding.should_invite(**self._kwargs()))

    def test_silent_when_the_user_stopped_it(self) -> None:
        self.assertFalse(onboarding.should_invite(**self._kwargs(stopped=True)))

    def test_silent_between_playlist_songs(self) -> None:
        self.assertFalse(onboarding.should_invite(**self._kwargs(playlist_active=True)))

    def test_silent_for_assisted_play(self) -> None:
        """補助演奏 ＝ その人はもう自分で弾いている。誘う相手ではない。"""
        self.assertFalse(onboarding.should_invite(**self._kwargs(assist=True)))

    def test_silent_when_disabled(self) -> None:
        self.assertFalse(onboarding.should_invite(**self._kwargs(enabled=False)))

    def test_silent_on_the_second_time_for_the_same_song(self) -> None:
        self.assertFalse(onboarding.should_invite(**self._kwargs(already_invited=True)))

    def test_silent_for_an_empty_score(self) -> None:
        self.assertFalse(onboarding.should_invite(**self._kwargs(note_count=0)))


class PlayableNoteCountTest(unittest.TestCase):
    """誘いは「実際に鳴った曲」にだけ出す ∴ 数えるのは楽譜の音数ではなく解決できた音。"""

    def test_counts_resolved_notes(self) -> None:
        self.assertEqual(onboarding.playable_note_count(_score(notes=3), _mapping()), 3)

    def test_zero_when_nothing_maps(self) -> None:
        # 鍵盤の外の音しか無い楽譜は「演奏できる音がありません」で終わる
        empty = KeyMapping(name="空", note_to_key={}, out_of_range="skip")
        self.assertEqual(onboarding.playable_note_count(_score(notes=3), empty), 0)

    def test_rests_are_not_counted(self) -> None:
        rest = Score(title="休符だけ", tempo_bpm=120.0,
                     events=[NoteEvent(start_beat=0.0, duration_beat=1.0, midi_notes=())])
        self.assertEqual(onboarding.playable_note_count(rest, _mapping()), 0)


class InviteTextTest(unittest.TestCase):
    def test_body_states_the_note_count(self) -> None:
        self.assertIn("22", onboarding.invite_body("きらきら星", 22))

    def test_untitled_score_does_not_break_the_sentence(self) -> None:
        self.assertNotIn("『』", onboarding.invite_lead("   "))
        self.assertIn("この曲", onboarding.invite_lead(""))

    def test_lead_names_the_song(self) -> None:
        self.assertIn("きらきら星", onboarding.invite_lead("きらきら星"))


class ConfigFieldsTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        path = os.path.join(self._dir.name, "config.json")
        patcher = mock.patch.object(config_mod, "config_path", lambda: path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_defaults(self) -> None:
        config = AppConfig()
        self.assertEqual(config.last_tab, "")  # 初回は既定タブ（練習）で開く
        self.assertTrue(config.invite_practice)

    def test_round_trip(self) -> None:
        original = AppConfig(last_tab=onboarding.TAB_PLAY, invite_practice=False)
        original.save()
        loaded = AppConfig.load()
        self.assertEqual(loaded.last_tab, onboarding.TAB_PLAY)
        self.assertFalse(loaded.invite_practice)


class InviteWiringTest(unittest.TestCase):
    """GUI 側の配線（誘いを出す条件・重複抑止）を、ウィンドウ無しで確かめる。"""

    def setUp(self) -> None:
        from autoplaynotes import gui  # 遅延 import（tkinter を要する）
        self.gui = gui

    def _app(self, **over):
        app = SimpleNamespace(
            root=None, config=AppConfig(), _invited=set(),
            _last_played=_score(), _last_assist=False, _playlist_active=False,
            _open_practice=lambda score=None: None, _mute_invite=lambda: None,
            _current_mapping=lambda: _mapping(),
        )
        for key, value in over.items():
            setattr(app, key, value)
        return app

    def _invite(self, app):
        with mock.patch.object(self.gui, "PracticeInviteDialog") as dialog:
            self.gui.App._maybe_invite_to_practice(app)
        return dialog

    def test_invites_once_per_song(self) -> None:
        app = self._app()
        self.assertEqual(self._invite(app).call_count, 1)
        # 同じ曲の二度目は勧誘であって導線ではない
        self.assertEqual(self._invite(app).call_count, 0)

    def test_another_song_invites_again(self) -> None:
        app = self._app()
        self.assertEqual(self._invite(app).call_count, 1)
        app._last_played = _score(title="かえるのうた", notes=5)
        self.assertEqual(self._invite(app).call_count, 1)

    def test_silent_when_muted(self) -> None:
        app = self._app(config=AppConfig(invite_practice=False))
        self.assertEqual(self._invite(app).call_count, 0)

    def test_silent_for_assisted_play(self) -> None:
        self.assertEqual(self._invite(self._app(_last_assist=True)).call_count, 0)

    def test_silent_without_a_played_score(self) -> None:
        self.assertEqual(self._invite(self._app(_last_played=None)).call_count, 0)

    def test_silent_when_no_note_could_be_played(self) -> None:
        # 「演奏できる音がありません」で終わった直後に誘わない
        empty = KeyMapping(name="空", note_to_key={}, out_of_range="skip")
        app = self._app(_current_mapping=lambda: empty)
        self.assertEqual(self._invite(app).call_count, 0)


class AppTabsTest(unittest.TestCase):
    """実際にウィンドウを組み立てて、タブの並びと起動時のタブを固定する。

    純関数だけを守っても、`_build_ui` が並びを直書きへ戻せば画面は静かに元へ戻る。
    ∴ ここだけは本物のウィジェットで確かめる（画面を作れない環境では skip）。
    """

    def setUp(self) -> None:
        path = os.path.join(tempfile.mkdtemp(), "config.json")
        patcher = mock.patch.object(config_mod, "config_path", lambda: path)
        patcher.start()
        self.addCleanup(patcher.stop)
        try:
            import customtkinter as ctk
            from autoplaynotes import gui, theme
            theme.setup(True)
            self.root = ctk.CTk()
        except Exception as exc:  # noqa: BLE001  tkinter 不在・画面なし等
            self.skipTest(f"GUI を組み立てられません: {exc}")
        self.gui = gui
        # 見た目の後追い処理（アイコンの貼り直し・タイトルバーの暗色化リトライ）は
        # 100〜800ms 後に発火する。テストはそれより早く窓を閉じるので、宙に浮いた
        # after が Tcl のエラーを吐く。確かめたいのはタブの並びなので、止めておく。
        for target, stub in ((theme, "apply_titlebar"), (gui.App, "_set_window_icon")):
            patcher = mock.patch.object(target, stub, staticmethod(lambda *a, **k: None))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.root.withdraw()
        self.addCleanup(self._destroy_root)

    def _destroy_root(self) -> None:
        # ⚠️ customtkinter は窓の内部で after を仕込む ∴ テストが窓を閉じたあとに
        # それが発火して Tcl が `invalid command name ... ("after" script)` を
        # stderr へ 1 行吐くことがある。テストの成否とは無関係で、待っても消えない
        # （宙に浮くのは破棄済みウィジェット側のコールバックである）。追わないこと。
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def _app(self, config: AppConfig):
        app = self.gui.App(self.root, config)
        self.addCleanup(app.hotkeys.stop)
        return app

    def test_tab_order_matches_onboarding(self) -> None:
        app = self._app(AppConfig(first_run=False))
        names = [app._tabs.get(i) for i in range(len(onboarding.TAB_ORDER))]
        self.assertEqual(names, list(onboarding.TAB_ORDER))

    def test_starts_on_the_practice_tab(self) -> None:
        app = self._app(AppConfig(first_run=False))
        self.assertEqual(app._tabs.get(), onboarding.TAB_PRACTICE)

    def test_starts_on_the_remembered_tab(self) -> None:
        app = self._app(AppConfig(first_run=False, last_tab=onboarding.TAB_PLAY))
        self.assertEqual(app._tabs.get(), onboarding.TAB_PLAY)

    def test_tab_change_is_remembered(self) -> None:
        app = self._app(AppConfig(first_run=False))
        app._tabs.set(onboarding.TAB_PLAYLIST)
        app._on_tab_changed()  # CTkTabview はユーザー操作時にこれを呼ぶ
        self.assertEqual(app.config.last_tab, onboarding.TAB_PLAYLIST)


if __name__ == "__main__":
    unittest.main()
