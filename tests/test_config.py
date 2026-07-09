"""設定の保存に関するテスト。

設定にはカスタムのキー割り当て・プレイリスト・練習メモが入る。既定値で上書きすると
ユーザーの手作業が黙って消える。実際に一度やってしまったので、ここで守る。
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoplaynotes import config  # noqa: E402
from autoplaynotes.config import AppConfig  # noqa: E402


class SaveTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = os.path.join(self._dir.name, "config.json")
        patcher = mock.patch.object(config, "config_path", lambda: self.path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_round_trip(self) -> None:
        original = AppConfig(tempo_bpm=144.0, active_mapping="diatonic")
        original.key_windows["曲#3"] = ["a", "s", "d"]
        original.save()
        loaded = AppConfig.load()
        self.assertEqual(loaded.tempo_bpm, 144.0)
        self.assertEqual(loaded.active_mapping, "diatonic")
        self.assertEqual(loaded.key_windows, {"曲#3": ["a", "s", "d"]})

    def test_first_save_leaves_no_backup(self) -> None:
        AppConfig().save()
        self.assertFalse(os.path.exists(self.path + ".bak"))

    def test_overwrite_keeps_the_previous_contents_in_bak(self) -> None:
        """既定値で上書きしても、直前の設定は .bak に残る。"""
        AppConfig(tempo_bpm=144.0, active_mapping="diatonic").save()
        AppConfig().save()  # 事故: 既定値で上書き

        self.assertEqual(AppConfig.load().tempo_bpm, 120.0)
        with open(self.path + ".bak", encoding="utf-8") as f:
            backup = json.load(f)
        self.assertEqual(backup["tempo_bpm"], 144.0)
        self.assertEqual(backup["active_mapping"], "diatonic")

    def test_no_temp_file_is_left_behind(self) -> None:
        AppConfig().save()
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_load_missing_file_gives_defaults(self) -> None:
        self.assertEqual(AppConfig.load().tempo_bpm, 120.0)

    def test_load_broken_file_gives_defaults(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ これは JSON ではない")
        self.assertEqual(AppConfig.load().tempo_bpm, 120.0)

    def test_unknown_keys_in_the_file_are_ignored(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"tempo_bpm": 90.0, "将来のフィールド": 1}, f)
        self.assertEqual(AppConfig.load().tempo_bpm, 90.0)

    def test_old_config_without_key_windows_loads(self) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"tempo_bpm": 90.0}, f)
        self.assertEqual(AppConfig.load().key_windows, {})


if __name__ == "__main__":
    unittest.main()
