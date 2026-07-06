"""音ゲー型の練習モード（落ちてくるノーツ＋判定）。

ゲーム本体には一切キーを送らない自己完結トレーナー。
- 曲で使うキーごとにレーンを作り、ノーツが上から判定ラインへ落ちてくる
- この練習ウィンドウにフォーカスして自分でキーを押し、タイミングを判定
- Perfect / Good / Miss ＋ コンボ ＋ スコア
- 内蔵の音声プレビューと同期再生（見て・聴いて・叩く）
"""

from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

from .keymap import KeyMapping
from .model import Score

# タイミング（秒）
_LEAD = 2.0          # 画面上端から判定ラインまで落ちる時間
_PERFECT = 0.05      # これ以内で Perfect
_GOOD = 0.13         # これ以内で Good（＝押下ヒットの許容窓）
_MISS_LATE = 0.16    # 判定ラインをこれ以上過ぎたら見逃し Miss

# 描画
_CANVAS_W = 760
_CANVAS_H = 470
_TOP_Y = 12
_HIT_Y = _CANVAS_H - 74
_LABEL_Y = _CANVAS_H - 44
_PAD = 12

_C_PENDING = "#42a5f5"
_C_HIT = "#43a047"
_C_MISS = "#9e9e9e"


@dataclass
class _Note:
    lane: int
    beat: float
    dur_beat: float
    judged: bool = False
    hit: bool = False
    missed: bool = False
    item: int | None = None


class PracticeWindow(tk.Toplevel):
    def __init__(self, parent: tk.Widget, score: Score, mapping: KeyMapping, audio=None) -> None:
        super().__init__(parent)
        self.title("練習モード（音ゲー）")
        self.resizable(False, False)
        self.score = score
        self.mapping = mapping
        self.audio = audio

        self._lanes: list[str] = []          # レーン -> キー
        self._char_to_lane: dict[str, int] = {}
        self._notes: list[_Note] = []
        self._build_lanes_and_notes()

        self._running = False
        self._t0 = 0.0
        self._after: str | None = None
        self._score = 0
        self._combo = 0
        self._max_combo = 0
        self._counts = {"Perfect": 0, "Good": 0, "Miss": 0}

        self._speed = tk.DoubleVar(value=1.0)
        self._audio_on = tk.BooleanVar(value=(audio is not None and audio.is_available()))
        self._score_var = tk.StringVar(value="Score 0")
        self._combo_var = tk.StringVar(value="")
        self._judge_var = tk.StringVar(value="")

        self._build_ui()
        self._draw_static()
        self.bind("<KeyPress>", self._on_key)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, lambda: self.focus_force())

    # --- セットアップ ---------------------------------------------------------
    def _build_lanes_and_notes(self) -> None:
        # レーン = 曲で使うキー。音高順（低→高）に並べる。
        key_pitch: dict[str, int] = {}
        raw: list[tuple[int, float, float]] = []  # (midi, beat, dur)
        for ev in self.score.events:
            if ev.is_rest:
                continue
            for midi in ev.midi_notes:
                key = self.mapping.resolve(midi)
                if key is None:
                    continue
                key_pitch.setdefault(key, midi)
                if midi < key_pitch[key]:
                    key_pitch[key] = midi
                raw.append((midi, ev.start_beat, ev.duration_beat))
        self._lanes = sorted(key_pitch, key=lambda k: key_pitch[k])
        lane_of_key = {k: i for i, k in enumerate(self._lanes)}
        self._char_to_lane = {k.lower(): i for k, i in lane_of_key.items()}
        for midi, beat, dur in raw:
            key = self.mapping.resolve(midi)
            if key is None:
                continue
            self._notes.append(_Note(lane=lane_of_key[key], beat=beat, dur_beat=dur))
        self._notes.sort(key=lambda n: n.beat)

    def _eff_bpm(self) -> float:
        bpm = self.score.tempo_bpm if self.score.tempo_bpm > 0 else 120.0
        return bpm * max(0.1, self._speed.get())

    def _spb(self) -> float:
        return 60.0 / self._eff_bpm()

    # --- UI -------------------------------------------------------------------
    def _build_ui(self) -> None:
        hud = ttk.Frame(self)
        hud.pack(fill="x", padx=10, pady=(8, 2))
        ttk.Label(hud, textvariable=self._score_var, font=("", 13, "bold")).pack(side="left")
        ttk.Label(hud, textvariable=self._combo_var, font=("", 12), foreground="#ef6c00").pack(side="left", padx=16)
        ttk.Label(hud, textvariable=self._judge_var, font=("", 13, "bold"), foreground="#1565c0").pack(side="right")

        self.canvas = tk.Canvas(self, width=_CANVAS_W, height=_CANVAS_H, background="#0f1420",
                                highlightthickness=0)
        self.canvas.pack(padx=10, pady=4)

        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=10, pady=(2, 10))
        self._start_btn = ttk.Button(controls, text="▶ スタート (Space)", command=self._start)
        self._start_btn.pack(side="left")
        ttk.Label(controls, text="速度:").pack(side="left", padx=(12, 2))
        ttk.OptionMenu(controls, self._speed, 1.0, 0.5, 0.75, 1.0, 1.25).pack(side="left")
        ttk.Checkbutton(controls, text="音を鳴らす", variable=self._audio_on).pack(side="left", padx=10)
        ttk.Label(controls, text="このウィンドウを選んで、ラインに来た瞬間にキーを叩く",
                  foreground="#666").pack(side="right")

    def _lane_w(self) -> float:
        n = max(1, len(self._lanes))
        return (_CANVAS_W - 2 * _PAD) / n

    def _lane_x(self, lane: int) -> float:
        return _PAD + lane * self._lane_w()

    def _y(self, t: float, now: float) -> float:
        return _HIT_Y - (t - now) / _LEAD * (_HIT_Y - _TOP_Y)

    def _draw_static(self) -> None:
        c = self.canvas
        c.delete("static")
        lw = self._lane_w()
        for i, key in enumerate(self._lanes):
            x = self._lane_x(i)
            if i % 2 == 0:
                c.create_rectangle(x, _TOP_Y, x + lw, _HIT_Y + 10, fill="#151b2b", outline="", tags="static")
            c.create_line(x, _TOP_Y, x, _HIT_Y + 10, fill="#263042", tags="static")
            c.create_text(x + lw / 2, _LABEL_Y, text=key, fill="#cfd8e3",
                          font=("Consolas", 12, "bold"), tags="static")
        c.create_line(_PAD, _HIT_Y, _CANVAS_W - _PAD, _HIT_Y, fill="#ffd54f", width=3, tags="static")
        if not self._notes:
            c.create_text(_CANVAS_W / 2, _CANVAS_H / 2,
                          text="演奏できる音がありません\n（マッピングを確認してください）",
                          fill="#cfd8e3", font=("", 12), justify="center", tags="static")

    # --- 進行 -----------------------------------------------------------------
    def _start(self) -> None:
        if self._running or not self._notes:
            return
        self._reset_state()
        self._start_btn.configure(state="disabled")
        self._countdown(3)

    def _reset_state(self) -> None:
        if self.audio is not None:
            self.audio.stop()
        for n in self._notes:
            n.judged = n.hit = n.missed = False
            if n.item is not None:
                self.canvas.delete(n.item)
                n.item = None
        self._score = 0
        self._combo = 0
        self._max_combo = 0
        self._counts = {"Perfect": 0, "Good": 0, "Miss": 0}
        self._update_hud()

    def _countdown(self, n: int) -> None:
        if not self.winfo_exists():
            return
        if n > 0:
            self._judge_var.set(f"{n} ...")
            self.after(700, lambda: self._countdown(n - 1))
        else:
            self._judge_var.set("START!")
            self._begin_run()

    def _begin_run(self) -> None:
        self._t0 = time.perf_counter()
        if self._audio_on.get() and self.audio is not None and self.audio.is_available():
            self.audio.play_score(self.score, self._eff_bpm())
        self._running = True
        self._tick()

    def _tick(self) -> None:
        if not self.winfo_exists() or not self._running:
            return
        now = time.perf_counter() - self._t0
        spb = self._spb()

        # 見逃し Miss 判定
        for note in self._notes:
            if not note.judged and now - note.beat * spb > _MISS_LATE:
                note.judged = True
                note.missed = True
                self._apply_judgment("Miss", 0)

        self._render(now, spb)

        last_hit = (self._notes[-1].beat + self._notes[-1].dur_beat) * spb if self._notes else 0
        if now > last_hit + 1.5:
            self._finish()
            return
        self._after = self.after(16, self._tick)

    def _render(self, now: float, spb: float) -> None:
        c = self.canvas
        lw = self._lane_w()
        for note in self._notes:
            t = note.beat * spb
            t_end = t + note.dur_beat * spb
            if (t - now >= _LEAD) or (now - t > 0.3):
                if note.item is not None:
                    c.delete(note.item)
                    note.item = None
                continue
            x0 = self._lane_x(note.lane) + lw * 0.16
            x1 = self._lane_x(note.lane) + lw * 0.84
            y_head = self._y(t, now)
            y_tail = self._y(t_end, now)
            ry1 = y_head
            ry0 = min(y_tail, y_head - 10)  # 最低高さ
            color = _C_HIT if note.hit else _C_MISS if note.missed else _C_PENDING
            if note.item is None:
                note.item = c.create_rectangle(x0, ry0, x1, ry1, fill=color, outline="")
            else:
                c.coords(note.item, x0, ry0, x1, ry1)
                c.itemconfig(note.item, fill=color)

    # --- 入力判定 -------------------------------------------------------------
    def _on_key(self, event: tk.Event) -> None:
        if event.keysym == "space" and not self._running:
            self._start()
            return
        if not self._running:
            return
        ch = event.char
        if not ch:
            return
        lane = self._char_to_lane.get(ch.lower())
        if lane is None:
            return
        now = time.perf_counter() - self._t0
        spb = self._spb()
        best: _Note | None = None
        best_dt = _GOOD
        for note in self._notes:
            if note.lane == lane and not note.judged:
                dt = abs(note.beat * spb - now)
                if dt < best_dt:
                    best_dt = dt
                    best = note
        if best is None:
            return
        best.judged = True
        best.hit = True
        if best_dt <= _PERFECT:
            self._apply_judgment("Perfect", 100)
        else:
            self._apply_judgment("Good", 50)
        self._flash_lane(lane)

    def _flash_lane(self, lane: int) -> None:
        lw = self._lane_w()
        x = self._lane_x(lane)
        fid = self.canvas.create_rectangle(x, _HIT_Y - 14, x + lw, _HIT_Y + 10,
                                           fill="#ffffff", outline="")
        self.canvas.after(70, lambda: self.canvas.delete(fid))

    def _apply_judgment(self, judgment: str, points: int) -> None:
        self._counts[judgment] += 1
        if judgment == "Miss":
            self._combo = 0
        else:
            self._combo += 1
            self._max_combo = max(self._max_combo, self._combo)
            self._score += points
        self._judge_var.set(judgment)
        self._update_hud()

    def _update_hud(self) -> None:
        self._score_var.set(f"Score {self._score}")
        self._combo_var.set(f"Combo {self._combo}" if self._combo > 1 else "")

    def _finish(self) -> None:
        self._running = False
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except Exception:
                pass
            self._after = None
        total = sum(self._counts.values())
        hits = self._counts["Perfect"] + self._counts["Good"]
        acc = (100.0 * hits / total) if total else 0.0
        c = self.canvas
        c.create_rectangle(_CANVAS_W / 2 - 180, _CANVAS_H / 2 - 90, _CANVAS_W / 2 + 180,
                           _CANVAS_H / 2 + 90, fill="#1c2333", outline="#ffd54f", width=2)
        text = (
            f"RESULT\n\nScore {self._score}\n"
            f"Perfect {self._counts['Perfect']}   Good {self._counts['Good']}   Miss {self._counts['Miss']}\n"
            f"Max Combo {self._max_combo}   Accuracy {acc:.1f}%"
        )
        c.create_text(_CANVAS_W / 2, _CANVAS_H / 2, text=text, fill="#e8eef7",
                      font=("", 12), justify="center")
        self._judge_var.set("FINISH")
        self._start_btn.configure(state="normal", text="▶ もう一度 (Space)")

    def _on_close(self) -> None:
        self._running = False
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except Exception:
                pass
        if self.audio is not None:
            self.audio.stop()
        self.destroy()
