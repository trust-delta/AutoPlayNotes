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


def render_score_pcm(score: Score, bpm: float) -> bytes:
    """曲全体を 16bit mono PCM にレンダリングする。"""
    if bpm <= 0:
        bpm = 120.0
    seconds_per_beat = 60.0 / bpm
    total_sec = min(score.total_seconds(bpm) + 0.6, _MAX_AUDITION_SEC)
    total_n = max(1, int(total_sec * _SR))
    main = array.array("h", bytes(2 * total_n))

    for event in score.events:
        if event.is_rest:
            continue
        dur = min(event.duration_beat * seconds_per_beat, 2.0)
        freqs = [midi_to_freq(m) for m in event.midi_notes]
        chord = _chord(freqs, dur)
        start = int(event.start_beat * seconds_per_beat * _SR)
        for i in range(len(chord)):
            j = start + i
            if j >= total_n:
                break
            main[j] = _clamp16(main[j] + chord[i])

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

    def play_score(self, score: Score, bpm: float) -> float:
        """曲全体を鳴らす。戻り値は再生秒数（カーソル同期用）。"""
        if not self._ok or not score.events:
            return 0.0
        self._play_pcm(render_score_pcm(score, bpm))
        return min(score.total_seconds(bpm), _MAX_AUDITION_SEC)

    def stop(self) -> None:
        if not self._ok:
            return
        try:
            _winsound.PlaySound(None, _winsound.SND_PURGE)
        except Exception:
            pass
