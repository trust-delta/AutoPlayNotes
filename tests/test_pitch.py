"""pitch のエンジン解決・コマンド組み立て・transcribe のテスト。

実際の basic-pitch は使わず、manifest.json と偽エンジン（Python サブプロセスで
MIDI ファイルを書き出すだけ）で隣接アドオン方式の配線を検証する。
"""

import json
import os
import sys
import tempfile
import unittest
from unittest import mock

from autoplaynotes import midi_parser, pitch


def _write_manifest(addon_dir: str, command: list[str], *, env: dict | None = None,
                    name: str = "テスト採譜") -> None:
    data: dict[str, object] = {"name": name, "command": command}
    if env is not None:
        data["env"] = env
    with open(os.path.join(addon_dir, "manifest.json"), "w", encoding="utf-8") as fh:
        json.dump(data, fh)


class IsAudioPathTest(unittest.TestCase):
    def test_common_audio_extensions(self) -> None:
        for name in ("a.wav", "b.MP3", "c.flac", "d.m4a", "e.ogg"):
            self.assertTrue(pitch.is_audio_path(name), name)

    def test_non_audio(self) -> None:
        for name in ("x.mid", "y.png", "z.musicxml", "no_ext"):
            self.assertFalse(pitch.is_audio_path(name), name)


class ResolveEngineTest(unittest.TestCase):
    def test_none_when_no_addon_and_no_basic_pitch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, pitch.ADDON_ENV: os.path.join(tmp, "missing")}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(pitch.shutil, "which", return_value=None):
                self.assertIsNone(pitch.resolve_engine())
                self.assertFalse(pitch.is_available())

    def test_path_basic_pitch_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, pitch.ADDON_ENV: os.path.join(tmp, "missing")}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(pitch.shutil, "which", return_value="C:/x/basic-pitch.exe"):
                engine = pitch.resolve_engine()
                self.assertIsNotNone(engine)
                assert engine is not None
                self.assertEqual(engine.source, "path")
                self.assertEqual(engine.command[0], "basic-pitch")

    def test_addon_takes_priority_over_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _write_manifest(tmp, ["run.exe", "{out}", "{audio}"])
            env = {**os.environ, pitch.ADDON_ENV: tmp}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(pitch.shutil, "which", return_value="C:/x/basic-pitch.exe"):
                engine = pitch.resolve_engine()
                assert engine is not None
                self.assertEqual(engine.source, "addon")
                self.assertEqual(engine.base_dir, os.path.abspath(tmp))

    def test_invalid_manifest_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as fh:
                fh.write("{ not json")
            env = {**os.environ, pitch.ADDON_ENV: tmp}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(pitch.shutil, "which", return_value=None):
                self.assertIsNone(pitch.resolve_engine())


class BuildCommandTest(unittest.TestCase):
    def test_relative_entry_is_absolutized_against_base_dir(self) -> None:
        engine = pitch.PitchEngine(
            source="addon",
            command=("bin/run.exe", "{out}", "{audio}"),
            base_dir=os.path.abspath("C:/addon"),
        )
        argv, run_env = pitch._build_command(engine, "in.wav", "outdir")
        self.assertEqual(argv[0], os.path.normpath(os.path.join(os.path.abspath("C:/addon"), "bin/run.exe")))
        self.assertEqual(argv[-2], "outdir")
        self.assertEqual(argv[-1], "in.wav")
        self.assertIsNone(run_env)

    def test_absolute_entry_is_untouched(self) -> None:
        entry = os.path.abspath("C:/addon/python.exe")
        engine = pitch.PitchEngine(source="addon", command=(entry, "-m", "basic_pitch"),
                                   base_dir=os.path.abspath("C:/addon"))
        argv, _ = pitch._build_command(engine, "in.wav", "out")
        self.assertEqual(argv[0], entry)

    def test_path_engine_entry_not_absolutized(self) -> None:
        engine = pitch.PitchEngine(source="path", command=("basic-pitch", "{out}", "{audio}"))
        argv, _ = pitch._build_command(engine, "in.wav", "out")
        self.assertEqual(argv[0], "basic-pitch")

    def test_addon_placeholder_in_command(self) -> None:
        engine = pitch.PitchEngine(
            source="addon",
            command=("python/python.exe", "{addon}/run_pitch.py", "{out}", "{audio}"),
            base_dir=os.path.abspath("C:/addon"),
        )
        argv, _ = pitch._build_command(engine, "in.wav", "out")
        self.assertEqual(argv[0], os.path.normpath(os.path.join(os.path.abspath("C:/addon"), "python/python.exe")))
        self.assertEqual(argv[1], os.path.abspath("C:/addon") + "/run_pitch.py")

    def test_env_addon_placeholder(self) -> None:
        engine = pitch.PitchEngine(
            source="addon", command=("run.exe",),
            base_dir=os.path.abspath("C:/addon"),
            env={"BASIC_PITCH_MODEL": "{addon}/model"},
        )
        _, run_env = pitch._build_command(engine, "in.wav", "out")
        assert run_env is not None
        self.assertEqual(
            run_env["BASIC_PITCH_MODEL"],
            os.path.abspath("C:/addon") + "/model",
        )


# 偽エンジン: 引数 (out_dir, audio) を受け、out_dir に <stem>_basic_pitch.mid を書く
# （basic-pitch の出力命名を模倣。中身はダミーで、transcribe はパス検出のみ検証する）
_FAKE_ENGINE = (
    "import os, sys\n"
    "out_dir, audio = sys.argv[1], sys.argv[2]\n"
    "stem = os.path.splitext(os.path.basename(audio))[0]\n"
    "print('predicting', flush=True)\n"
    "open(os.path.join(out_dir, stem + '_basic_pitch.mid'), 'wb').write(b'MThd')\n"
    "print('done', flush=True)\n"
)


class TranscribeTest(unittest.TestCase):
    def test_transcribe_via_fake_engine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "fake_engine.py")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(_FAKE_ENGINE)
            _write_manifest(tmp, [sys.executable, script, "{out}", "{audio}"])
            out_dir = os.path.join(tmp, "out")
            audio = os.path.join(tmp, "song.wav")

            progress: list[str] = []
            env = {**os.environ, pitch.ADDON_ENV: tmp}
            with mock.patch.dict(os.environ, env, clear=True):
                result = pitch.transcribe(audio, output_dir=out_dir,
                                          on_progress=progress.append)

            self.assertTrue(result.endswith("song_basic_pitch.mid"))
            self.assertTrue(os.path.isfile(result))
            self.assertIn("predicting", progress)

    def test_transcribe_without_engine_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = {**os.environ, pitch.ADDON_ENV: os.path.join(tmp, "missing")}
            with mock.patch.dict(os.environ, env, clear=True), \
                    mock.patch.object(pitch.shutil, "which", return_value=None):
                with self.assertRaises(pitch.PitchError):
                    pitch.transcribe(os.path.join(tmp, "x.wav"))


# 実 MIDI を吐く偽エンジン（C4,E4,G4 を順に）。データ経路 音源→MIDI→Score を通す検証用。
_FAKE_ENGINE_REAL_MIDI = (
    "import os, sys, mido\n"
    "out_dir, audio = sys.argv[1], sys.argv[2]\n"
    "stem = os.path.splitext(os.path.basename(audio))[0]\n"
    "mid = mido.MidiFile(ticks_per_beat=480)\n"
    "tr = mido.MidiTrack(); mid.tracks.append(tr)\n"
    "tr.append(mido.MetaMessage('set_tempo', tempo=mido.bpm2tempo(120), time=0))\n"
    "for i, n in enumerate((60, 64, 67)):\n"
    "    tr.append(mido.Message('note_on', note=n, velocity=80, time=0 if i==0 else 480))\n"
    "    tr.append(mido.Message('note_off', note=n, velocity=0, time=240))\n"
    "mid.save(os.path.join(out_dir, stem + '_basic_pitch.mid'))\n"
    "print('done', flush=True)\n"
)


class ChainToScoreTest(unittest.TestCase):
    """音源 → MIDI → 楽譜(Score) の一気通貫（練習まで運べるデータ経路）を検証。"""

    @unittest.skipUnless(midi_parser.is_available(), "mido が必要")
    def test_audio_to_midi_to_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = os.path.join(tmp, "fake_engine_midi.py")
            with open(script, "w", encoding="utf-8") as fh:
                fh.write(_FAKE_ENGINE_REAL_MIDI)
            _write_manifest(tmp, [sys.executable, script, "{out}", "{audio}"])
            out_dir = os.path.join(tmp, "out")
            audio = os.path.join(tmp, "song.wav")

            env = {**os.environ, pitch.ADDON_ENV: tmp}
            with mock.patch.dict(os.environ, env, clear=True):
                midi_path = pitch.transcribe(audio, output_dir=out_dir)

            self.assertTrue(midi_path.endswith("song_basic_pitch.mid"))
            # ここが要件の核心: MIDI が実際に Score になる（＝練習/自動演奏へ運べる）
            score = midi_parser.build_score(midi_path)
            self.assertEqual(len(score.events), 3)
            self.assertEqual([ev.midi_notes for ev in score.events], [(60,), (64,), (67,)])
            self.assertAlmostEqual(score.tempo_bpm, 120.0, places=3)


if __name__ == "__main__":
    unittest.main()
