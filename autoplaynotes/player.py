"""演奏エンジン。

楽譜（拍単位）を BPM で秒へ変換し、絶対時刻ベースで
キー押下 / 解放アクションをスケジュールして送出する。
別スレッドで動作し、いつでも停止できる。

ヒューマナイズ（タイミング揺れ・音長揺れ・和音ロール）に対応。
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from typing import Callable

from .keymap import KeyMapping, note_name
from .model import Score
from .win_input import KeySender, high_resolution_timer


# キーを押し下げる最小時間（秒）。これを下回るとゲーム側が取りこぼす。
_MIN_HOLD_SECONDS = 0.005


@dataclass(frozen=True)
class PlaybackOptions:
    tempo_bpm: float | None = None  # None なら楽譜の BPM を使う
    count_in_seconds: float = 3.0
    gate_ms: float = 40.0  # 最短の押し下げ時間。持続音楽器では音長がこれを上回る
    # 同じキーを鳴らし直すとき、離してから押すまでの間隔。60fps のゲームは 16.7ms ごとに
    # しかキー状態を見ないことがあるので、1 フレームより長く取る。
    retrigger_gap_ms: float = 25.0
    speed: float = 1.0  # 再生速度倍率
    start_beat: float = 0.0  # この拍から演奏を開始（途中再生）
    # ヒューマナイズ
    timing_jitter_ms: float = 0.0  # 各音の発音タイミングの揺れ（±ms）
    gate_jitter_pct: float = 0.0  # 押下時間の揺れ（±%）
    chord_roll_ms: float = 0.0  # 和音を低音から少しずつずらす（ms）
    seed: int | None = None  # 乱数シード（テスト再現用。None で毎回変化）


@dataclass(frozen=True)
class _Action:
    at: float  # 開始からの秒数
    is_down: bool
    keys: tuple[str, ...]
    beat: float  # 元の楽譜上の拍位置（再生カーソル用）


StatusCallback = Callable[[str], None]
DoneCallback = Callable[[bool], None]  # 引数: 停止で終わったか
ProgressCallback = Callable[[float, float], None]  # (現在拍, 総拍数)


class Player:
    def __init__(
        self,
        sender: KeySender,
        on_status: StatusCallback | None = None,
        on_done: DoneCallback | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> None:
        self._sender = sender
        self._on_status = on_status
        self._on_done = on_done
        self._on_progress = on_progress
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def is_playing(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _status(self, message: str) -> None:
        if self._on_status is not None:
            self._on_status(message)

    def build_actions(
        self, score: Score, mapping: KeyMapping, options: PlaybackOptions
    ) -> tuple[list[_Action], int]:
        """楽譜からアクション列を生成する。戻り値は (アクション列, スキップ音数)。

        持続音楽器（mapping.sustain）では音長どおりキーを押し続ける。同じキーが
        時間的に重なった場合は「後勝ち」——先行音を離してから鳴らし直す。物理キーは
        状態を 1 つしか持てないうえ、対象の楽器は押下エッジでしか発音しないため、
        離さずに押し直しても鳴らない。
        """
        bpm = options.tempo_bpm or score.tempo_bpm
        if bpm <= 0:
            raise ValueError("BPM は正の数にしてください")
        speed = options.speed if options.speed > 0 else 1.0
        seconds_per_beat = (60.0 / bpm) / speed
        min_hold = max(options.gate_ms / 1000.0, _MIN_HOLD_SECONDS)
        retrigger_gap = max(0.0, options.retrigger_gap_ms / 1000.0)

        rng = random.Random(options.seed)
        timing_jitter = max(0.0, options.timing_jitter_ms) / 1000.0
        gate_jitter = max(0.0, min(options.gate_jitter_pct, 50.0)) / 100.0
        roll = max(0.0, options.chord_roll_ms) / 1000.0
        start_beat = max(0.0, options.start_beat)

        # (key, onset秒, hold秒, 楽譜上の拍)
        notes: list[tuple[str, float, float, float]] = []
        skipped = 0
        for event in score.events:
            if event.is_rest:
                continue
            if event.start_beat < start_beat - 1e-9:
                continue

            base = (event.start_beat - start_beat) * seconds_per_beat
            if timing_jitter > 0:
                base += rng.uniform(-timing_jitter, timing_jitter)
            base = max(0.0, base)

            # 低音から順にキーへ解決。音域の折り返しで同じキーに落ちた音は長い方を残す。
            order: list[str] = []
            longest: dict[str, float] = {}
            for midi, dur in zip(event.midi_notes, event.note_durations()):
                key = mapping.resolve(midi)
                if key is None:
                    skipped += 1
                    continue
                seconds = dur * seconds_per_beat
                if key not in longest:
                    order.append(key)
                    longest[key] = seconds
                elif seconds > longest[key]:
                    longest[key] = seconds

            for i, key in enumerate(order):
                onset = base + (i * roll if roll > 0 else 0.0)
                hold = longest[key] if mapping.sustain else min_hold
                if gate_jitter > 0:
                    hold *= 1.0 + rng.uniform(-gate_jitter, gate_jitter)
                notes.append((key, onset, max(hold, min_hold), event.start_beat))

        actions = self._resolve_key_conflicts(notes, retrigger_gap)
        # 時刻順に整列。同時刻なら解放(up)を押下(down)より先に。
        actions.sort(key=lambda a: (a.at, a.is_down))
        return actions, skipped

    @staticmethod
    def _resolve_key_conflicts(
        notes: list[tuple[str, float, float, float]], retrigger_gap: float
    ) -> list[_Action]:
        """同じキーの押下が重なったら、先行音を次の押下の手前で離す（後勝ち）。"""
        by_key: dict[str, list[tuple[str, float, float, float]]] = {}
        for note in notes:
            by_key.setdefault(note[0], []).append(note)

        actions: list[_Action] = []
        for key, group in by_key.items():
            group.sort(key=lambda n: n[1])
            for i, (_key, onset, hold, beat) in enumerate(group):
                end = onset + hold
                if i + 1 < len(group):
                    next_onset = group[i + 1][1]
                    # 離してから押すまでに、ゲームが検知できる間隔を空ける
                    end = min(end, max(onset + _MIN_HOLD_SECONDS, next_onset - retrigger_gap))
                actions.append(_Action(onset, True, (key,), beat))
                actions.append(_Action(end, False, (key,), beat))
        return actions

    def play(self, score: Score, mapping: KeyMapping, options: PlaybackOptions) -> None:
        if self.is_playing:
            raise RuntimeError("すでに演奏中です")

        actions, skipped = self.build_actions(score, mapping, options)
        if not actions:
            self._status("演奏できる音がありません（マッピングを確認してください）")
            if self._on_done is not None:
                self._on_done(False)
            return

        total_beats = score.total_beats()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(actions, options, skipped, total_beats),
            daemon=True,
        )
        self._thread.start()

    def _run(
        self,
        actions: list[_Action],
        options: PlaybackOptions,
        skipped: int,
        total_beats: float,
    ) -> None:
        # 既定のタイマ分解能（約 15.6ms）では、押下・解放が 10ms 強ずつ遅れて
        # 再発音の間隔が潰れる。演奏中だけ 1ms へ上げる。
        with high_resolution_timer():
            self._schedule(actions, options, skipped, total_beats)

    def _schedule(
        self,
        actions: list[_Action],
        options: PlaybackOptions,
        skipped: int,
        total_beats: float,
    ) -> None:
        stopped = False
        try:
            if skipped > 0:
                self._status(f"注意: {skipped} 個の音は音域外/割り当て無しのためスキップします")

            remaining = options.count_in_seconds
            while remaining > 0:
                if self._stop.wait(min(1.0, remaining)):
                    stopped = True
                    return
                remaining -= 1.0
                if remaining > 0:
                    self._status(f"演奏開始まで {int(remaining) + 1}...")

            self._status("演奏中... (F10 で停止)")
            start_time = time.perf_counter()
            last_beat = -1.0

            for action in actions:
                target = start_time + action.at
                delay = target - time.perf_counter()
                if delay > 0 and self._stop.wait(delay):
                    stopped = True
                    break
                if self._stop.is_set():
                    stopped = True
                    break
                if action.is_down and self._on_progress is not None and action.beat != last_beat:
                    last_beat = action.beat
                    self._on_progress(action.beat, total_beats)
                try:
                    if action.is_down:
                        self._sender.down(action.keys)
                    else:
                        self._sender.up(action.keys)
                except Exception as exc:  # 送出失敗は致命的でないので継続
                    self._status(f"入力エラー: {exc}")
        finally:
            try:
                self._sender.release_all()
            except Exception:
                pass
            if self._on_progress is not None:
                self._on_progress(-1.0, total_beats)  # カーソル消去の合図
            self._status("停止しました" if stopped else "演奏完了")
            if self._on_done is not None:
                self._on_done(stopped)

    def stop(self) -> None:
        self._stop.set()

    def wait(self, timeout: float | None = None) -> None:
        if self._thread is not None:
            self._thread.join(timeout)


def preview_lines(score: Score, mapping: KeyMapping, limit: int = 60) -> list[str]:
    """演奏内容の確認用に「音名 -> キー」を人間可読で返す。"""
    lines: list[str] = []
    for event in score.events[:limit]:
        if event.is_rest:
            lines.append(f"@{event.start_beat:6.2f}  休符")
            continue
        parts = []
        for midi in event.midi_notes:
            key = mapping.resolve(midi)
            parts.append(f"{note_name(midi)}->{key or '×'}")
        lines.append(f"@{event.start_beat:6.2f}  " + "  ".join(parts))
    if len(score.events) > limit:
        lines.append(f"... 他 {len(score.events) - limit} 音")
    return lines
