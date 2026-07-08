"""omr のエンジン解決・コマンド組み立て・transcribe のテスト。

実際の oemer は使わず、manifest.json と偽エンジン（Python サブプロセスで
MusicXML を書き出すだけ）で隣接アドオン方式の配線を検証する。
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from autoplaynotes import omr


def _write_manifest(addon_dir: str, command: list[str], *, env: dict | None = None,
                    name: str = "テスト OMR") -> None:
    data: dict[str, object] = {"name": name, "command": command}
    if env is not None:
        data["env"] = env
    with open(os.path.join(addon_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh)


class ResolveEngineTest(unittest.TestCase):
    def test_none_when_no_addon_and_no_oemer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, omr.ADDON_ENV: os.path.join(tmp, "missing")}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(omr.shutil, "which", return_value=None):
                self.assertIsNone(omr.resolve_engine())
                self.assertFalse(omr.is_available())

    def test_path_oemer_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, omr.ADDON_ENV: os.path.join(tmp, "missing")}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(omr.shutil, "which", return_value="C:/x/oemer.exe"):
                engine = omr.resolve_engine()
                self.assertIsNotNone(engine)
                assert engine is not None
                self.assertEqual(engine.source, "path")
                self.assertEqual(engine.command[0], "oemer")

    def test_addon_takes_priority_over_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_manifest(tmp, ["run.exe", "-o", "{out}", "{image}"])
            env = {**os.environ, omr.ADDON_ENV: tmp}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(omr.shutil, "which", return_value="C:/x/oemer.exe"):
                engine = omr.resolve_engine()
                assert engine is not None
                self.assertEqual(engine.source, "addon")
                self.assertEqual(engine.base_dir, os.path.abspath(tmp))

    def test_invalid_manifest_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as fh:
                fh.write("{ not json")
            env = {**os.environ, omr.ADDON_ENV: tmp}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(omr.shutil, "which", return_value=None):
                self.assertIsNone(omr.resolve_engine())


class BuildCommandTest(unittest.TestCase):
    def test_relative_entry_is_absolutized_against_base_dir(self) -> None:
        engine = omr.OmrEngine(
            source="addon",
            command=("bin/run.exe", "-o", "{out}", "{image}"),
            base_dir=os.path.abspath("C:/addon"),
        )
        argv, run_env = omr._build_command(engine, "in.png", "outdir")
        self.assertEqual(argv[0], os.path.join(os.path.abspath("C:/addon"), "bin/run.exe"))
        self.assertEqual(argv[-2], "outdir")
        self.assertEqual(argv[-1], "in.png")
        self.assertIsNone(run_env)

    def test_absolute_entry_is_untouched(self) -> None:
        entry = os.path.abspath("C:/addon/python.exe")
        engine = omr.OmrEngine(source="addon", command=(entry, "-m", "oemer"),
                               base_dir=os.path.abspath("C:/addon"))
        argv, _ = omr._build_command(engine, "in.png", "out")
        self.assertEqual(argv[0], entry)

    def test_path_engine_entry_not_absolutized(self) -> None:
        engine = omr.OmrEngine(source="path", command=("oemer", "-o", "{out}", "{image}"))
        argv, _ = omr._build_command(engine, "in.png", "out")
        self.assertEqual(argv[0], "oemer")

    def test_env_addon_placeholder(self) -> None:
        engine = omr.OmrEngine(
            source="addon", command=("run.exe",),
            base_dir=os.path.abspath("C:/addon"),
            env={"OEMER_CHECKPOINTS": "{addon}/checkpoints"},
        )
        _, run_env = omr._build_command(engine, "in.png", "out")
        assert run_env is not None
        self.assertEqual(
            run_env["OEMER_CHECKPOINTS"],
            os.path.abspath("C:/addon") + "/checkpoints",
        )


# 偽エンジン: 引数 (out_dir, image) を受け、out_dir に <stem>.musicxml を書く
_FAKE_ENGINE = (
    "import os, sys\n"
    "out_dir, image = sys.argv[1], sys.argv[2]\n"
    "stem = os.path.splitext(os.path.basename(image))[0]\n"
    "print('recognizing', flush=True)\n"
    "open(os.path.join(out_dir, stem + '.musicxml'), 'w').write('<score-partwise/>')\n"
    "print('done', flush=True)\n"
)


class TranscribeTest(unittest.TestCase):
    def test_transcribe_via_fake_engine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "fake_engine.py")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(_FAKE_ENGINE)
            _write_manifest(tmp, [sys.executable, script, "{out}", "{image}"])
            out_dir = os.path.join(tmp, "out")
            image = os.path.join(tmp, "score.png")

            progress: list[str] = []
            env = {**os.environ, omr.ADDON_ENV: tmp}
            with mock.patch.dict(os.environ, env, clear=True):
                result = omr.transcribe(image, output_dir=out_dir,
                                        on_progress=progress.append)

            self.assertTrue(result.endswith("score.musicxml"))
            self.assertTrue(os.path.isfile(result))
            self.assertIn("recognizing", progress)

    def test_transcribe_without_engine_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, omr.ADDON_ENV: os.path.join(tmp, "missing")}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(omr.shutil, "which", return_value=None):
                with self.assertRaises(omr.OmrError):
                    omr.transcribe(os.path.join(tmp, "x.png"))


if __name__ == "__main__":
    unittest.main()
