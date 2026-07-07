"""確認用の音声プレビュー（アプリのスピーカーから鳴らす。ゲームへは何も送らない）。

Windows 標準の winsound と純 Python のサイン波合成のみを使う（追加依存なし）。
winsound.PlaySound は一度に 1 音源しか鳴らせないため:
- 単音/和音の確認は、その和音を 1 つの WAV にして再生
- 曲の通し試聴は、曲全体を 1 つの WAV にレンダリングして再生
する。
"""

from __future__ import annotations

import array
import io
import math
import wave

from .model import Score

try:
    import winsound as _winsound
except ImportError:  # pragma: no cover - 非 Windows
    _winsound = None  # type: ignore[assignment]

_SR = 16000  # サンプリングレート（確認用途には十分）
_MAX_AUDITION_SEC = 90.0  # 通し試聴の上限（レンダリング時間の暴走防止）

_tone_cache: dict[tuple[float, float], array.array] = {}


def is_available() -> bool:
    return _winsound is not None


def midi_to_freq(midi: int) -> float:
    return 440.0 * (2.0 ** ((midi - 69) / 12.0))


def _clamp16(value: int) -> int:
    if value > 32767:
        return 32767
    if value < -32768:
        return -32768
    return value


def _tone(freq: float, dur: float, amp: float = 0.28) -> array.array:
    """1 音のサイン波（+2倍音）をエンベロープ付きで生成。(freq,dur) でキャッシュ。"""
    key = (round(freq, 1), round(dur, 3))
    cached = _tone_cache.get(key)
    if cached is not None:
        return cached

    n = max(1, int(dur * _SR))
    attack = min(int(0.006 * _SR), n // 2)
    release = min(int(0.05 * _SR), n // 2)
    samples = array.array("h", bytes(2 * n))
    two_pi = 2.0 * math.pi
    for i in range(n):
        if attack and i < attack:
            env = i / attack
        elif release and i > n - release:
            env = (n - i) / release
        else:
            env = 1.0
        t = i / _SR
        s = math.sin(two_pi * freq * t) * 0.8 + math.sin(two_pi * 2 * freq * t) * 0.2
        samples[i] = _clamp16(int(s * amp * env * 32767))
    _tone_cache[key] = samples
    return samples


_click_cache: dict[bool, array.array] = {}


def _click(accent: bool = False) -> array.array:
    """メトロノームのクリック音（短い高音バースト・急速減衰）。"""
    cached = _click_cache.get(accent)
    if cached is not None:
        return cached
    freq = 2100.0 if accent else 1500.0
    amp = 0.55 if accent else 0.42
    dur = 0.028
    n = max(1, int(dur * _SR))
    samples = array.array("h", bytes(2 * n))
    two_pi = 2.0 * math.pi
    for i in range(n):
        env = (1.0 - i / n) ** 2  # 急速に減衰させてクリック感を出す
        s = math.sin(two_pi * freq * i / _SR)
        samples[i] = _clamp16(int(s * amp * env * 32767))
    _click_cache[accent] = samples
    return samples


def _chord(freqs: list[float], dur: float) -> array.array:
    tones = [_tone(f, dur) for f in freqs]
    n = len(tones[0]) if tones else 0
    out = array.array("h", bytes(2 * n))
    for tone in tones:
        for i in range(n):
            out[i] = _clamp16(out[i] + tone[i])
    return out


def _wav_bytes(pcm: bytes, sample_rate: int = _SR) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buf.getvalue()


def _mix(main: array.array, sound: array.array, start: int, total_n: int) -> None:
    for i in range(len(sound)):
        j = start + i
        if j < 0:
            continue
        if j >= total_n:
            break
        main[j] = _clamp16(main[j] + sound[i])


def render_score_pcm(
    score: Score,
    bpm: float,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    include_notes: bool = True,
    metronome: bool = False,
) -> bytes:
    """曲を 16bit mono PCM にレンダリングする。

    [start_sec, end_sec) の区間だけを出力する（end_sec=None なら曲末まで）。
    include_notes=False にすると音符を鳴らさず、metronome=True で各拍にクリックを混ぜる
    （winsound は 1 音源のみ再生できるため、メトロノームは曲に混ぜて 1 つの WAV にする）。
    """
    if bpm <= 0:
        bpm = 120.0
    seconds_per_beat = 60.0 / bpm
    start_sec = max(0.0, start_sec)
    total_sec = min(score.total_seconds(bpm) + 0.6, _MAX_AUDITION_SEC)
    if end_sec is not None:
        total_sec = min(total_sec, end_sec)
    render_sec = max(0.05, total_sec - start_sec)
    total_n = max(1, int(render_sec * _SR))
    main = array.array("h", bytes(2 * total_n))

    if include_notes:
        for event in score.events:
            if event.is_rest:
                continue
            dur = min(event.duration_beat * seconds_per_beat, 2.0)
            t = event.start_beat * seconds_per_beat - start_sec
            if t + dur < 0:
                continue  # シーク位置より前に鳴り終わる音
            freqs = [midi_to_freq(m) for m in event.midi_notes]
            _mix(main, _chord(freqs, dur), int(t * _SR), total_n)

    if metronome:
        beat = max(0, math.ceil(start_sec / seconds_per_beat - 1e-6))
        while True:
            t = beat * seconds_per_beat - start_sec
            if t >= render_sec:
                break
            if t >= -1e-3:
                _mix(main, _click(beat % 4 == 0), int(t * _SR), total_n)
            beat += 1

    return main.tobytes()


class AudioPlayer:
    """確認用の音を鳴らす。ゲームへの入力とは無関係。"""

    def __init__(self) -> None:
        self._ok = _winsound is not None

    def is_available(self) -> bool:
        return self._ok

    def _play_pcm(self, pcm: bytes) -> None:
        if not self._ok or not pcm:
            return
        try:
            _winsound.PlaySound(_wav_bytes(pcm), _winsound.SND_MEMORY | _winsound.SND_ASYNC)
        except Exception:
            pass

    def play_notes(self, midi_notes: tuple[int, ...], dur: float = 0.45) -> None:
        """単音/和音を鳴らす（編集中の確認用）。"""
        if not self._ok or not midi_notes:
            return
        freqs = [midi_to_freq(m) for m in midi_notes]
        self._play_pcm(_chord(freqs, dur).tobytes())

    def play_score(
        self,
        score: Score,
        bpm: float,
        start_sec: float = 0.0,
        end_sec: float | None = None,
        include_notes: bool = True,
        metronome: bool = False,
    ) -> float:
        """曲を鳴らす（[start_sec, end_sec) 区間）。戻り値は残り再生秒数。

        include_notes=False + metronome=True でメトロノームのみ鳴らせる。
        """
        if not self._ok:
            return 0.0
        if include_notes and not score.events and not metronome:
            return 0.0
        self._play_pcm(render_score_pcm(
            score, bpm, start_sec=start_sec, end_sec=end_sec,
            include_notes=include_notes, metronome=metronome,
        ))
        end = min(score.total_seconds(bpm), _MAX_AUDITION_SEC) if end_sec is None else min(end_sec, _MAX_AUDITION_SEC)
        return max(0.0, end - max(0.0, start_sec))

    def stop(self) -> None:
        if not self._ok:
            return
        try:
            _winsound.PlaySound(None, _winsound.SND_PURGE)
        except Exception:
            pass
