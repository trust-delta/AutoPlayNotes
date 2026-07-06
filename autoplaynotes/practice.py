"""音ゲー型の練習モード（2 モード）。

ゲーム本体には一切キーを送らない自己完結トレーナー。
- 曲で使うキーごとにレーンを作る
- この練習ウィンドウにフォーカスして自分でキーを押す

モード:
1) リズム: 楽譜どおりのテンポでノーツが落ちてくる。判定ライン到達の瞬間に叩く。
   Perfect / Good / Miss ＋ コンボ ＋ スコア。内蔵音声と同期再生。
2) ステップ（送り）: テンポ・リズムは不問。次に光ったキーを押すと譜面が 1 つ進む。
   指の送り順を覚えるための練習。
"""

from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

from .keymap import KeyMapping
from .model import Score
from .staff import StaffCanvas

# リズム: タイミング（秒）
_LEAD = 2.0          # 画面上端から判定ラインまで落ちる時間
_PERFECT = 0.05      # これ以内で Perfect
_GOOD = 0.13         # これ以内で Good（＝押下ヒットの許容窓）
_MISS_LATE = 0.16    # 判定ラインをこれ以上過ぎたら見逃し Miss

# ステップ: 表示
_STEP_GAP = 62       # ステップ間の縦間隔(px)

# 描画
_CANVAS_W = 760
_CANVAS_H = 340
_TOP_Y = 12
_HIT_Y = _CANVAS_H - 74
_LABEL_Y = _CANVAS_H - 44
_PAD = 12

_C_PENDING = "#42a5f5"
_C_HIT = "#43a047"
_C_MISS = "#9e9e9e"
_C_FUTURE = "#2a3a55"


def _fmt_time(sec: float) -> str:
    sec = max(0.0, sec)
    return f"{int(sec) // 60}:{int(sec) % 60:02d}"


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
        self.title("練習モード")
        self.resizable(False, False)
        self.score = score
        self.mapping = mapping
        self.audio = audio

        self._lanes: list[str] = []
        self._char_to_lane: dict[str, int] = {}
        self._label_items: dict[int, int] = {}
        self._build_lanes()
        self._notes: list[_Note] = self._build_notes()
        self._steps: list[dict[int, int]] = []
        self._step_beats: list[float] = []
        self._build_steps()

        # 共通状態
        self._running = False
        self._t0 = 0.0
        self._after: str | None = None
        # リズム状態
        self._score = 0
        self._combo = 0
        self._max_combo = 0
        self._counts = {"Perfect": 0, "Good": 0, "Miss": 0}
        # ステップ状態
        self._cur = 0
        self._pressed: set[int] = set()
        self._progress = 0.0
        # 開始位置マーカー（停止中にシークで設定）
        self._start_sec = 0.0
        self._start_idx = 0

        self._mode = tk.StringVar(value="rhythm")
        self._speed = tk.DoubleVar(value=1.0)
        self._seek_amt = tk.DoubleVar(value=3.0)
        self._audio_on = tk.BooleanVar(value=(audio is not None and audio.is_available()))
        self._score_var = tk.StringVar(value="Score 0")
        self._combo_var = tk.StringVar(value="")
        self._judge_var = tk.StringVar(value="")
        self._pos_var = tk.StringVar(value="")
        self._instr = tk.StringVar(value="")

        self._build_ui()
        self._draw_static()
        self._apply_mode_text()
        self.bind("<KeyPress>", self._on_key)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, lambda: self.focus_force())

    # --- セットアップ ---------------------------------------------------------
    def _build_lanes(self) -> None:
        key_pitch: dict[str, int] = {}
        for ev in self.score.events:
            if ev.is_rest:
                continue
            for midi in ev.midi_notes:
                key = self.mapping.resolve(midi)
                if key is None:
                    continue
                if key not in key_pitch or midi < key_pitch[key]:
                    key_pitch[key] = midi
        self._lanes = sorted(key_pitch, key=lambda k: key_pitch[k])
        self._char_to_lane = {k.lower(): i for i, k in enumerate(self._lanes)}

    def _lane_of_key(self, key: str) -> int:
        return self._lanes.index(key)

    def _build_notes(self) -> list[_Note]:
        notes: list[_Note] = []
        for ev in self.score.events:
            if ev.is_rest:
                continue
            for midi in ev.midi_notes:
                key = self.mapping.resolve(midi)
                if key is None:
                    continue
                notes.append(_Note(lane=self._lane_of_key(key), beat=ev.start_beat, dur_beat=ev.duration_beat))
        notes.sort(key=lambda n: n.beat)
        return notes

    def _build_steps(self) -> None:
        """各ステップ = そのイベントで同時に押すキー（lane -> 代表 midi）と拍位置。"""
        for ev in self.score.events:
            if ev.is_rest:
                continue
            step: dict[int, int] = {}
            for midi in ev.midi_notes:
                key = self.mapping.resolve(midi)
                if key is None:
                    continue
                step[self._lane_of_key(key)] = midi
            if step:
                self._steps.append(step)
                self._step_beats.append(ev.start_beat)

    def _eff_bpm(self) -> float:
        bpm = self.score.tempo_bpm if self.score.tempo_bpm > 0 else 120.0
        return bpm * max(0.1, self._speed.get())

    def _spb(self) -> float:
        return 60.0 / self._eff_bpm()

    # --- UI -------------------------------------------------------------------
    def _build_ui(self) -> None:
        top = ttk.Frame(self)
        top.pack(fill="x", padx=10, pady=(8, 0))
        ttk.Label(top, text="モード:").pack(side="left")
        ttk.Radiobutton(top, text="リズム", variable=self._mode, value="rhythm",
                        command=self._on_mode_change).pack(side="left")
        ttk.Radiobutton(top, text="ステップ（送り）", variable=self._mode, value="step",
                        command=self._on_mode_change).pack(side="left")

        hud = ttk.Frame(self)
        hud.pack(fill="x", padx=10, pady=(4, 2))
        ttk.Label(hud, textvariable=self._score_var, font=("", 13, "bold")).pack(side="left")
        ttk.Label(hud, textvariable=self._combo_var, font=("", 12), foreground="#ef6c00").pack(side="left", padx=16)
        ttk.Label(hud, textvariable=self._judge_var, font=("", 13, "bold"), foreground="#1565c0").pack(side="right")
        ttk.Label(hud, textvariable=self._pos_var, foreground="#888").pack(side="right", padx=12)

        self.canvas = tk.Canvas(self, width=_CANVAS_W, height=_CANVAS_H, background="#0f1420",
                                highlightthickness=0)
        self.canvas.pack(padx=10, pady=4)

        controls = ttk.Frame(self)
        controls.pack(fill="x", padx=10, pady=(2, 4))
        self._start_btn = ttk.Button(controls, text="▶ スタート (Space)", command=self._start)
        self._start_btn.pack(side="left")
        ttk.Button(controls, text="⏪", width=3, command=lambda: self._seek(-self._seek_amt.get())).pack(side="left", padx=(10, 1))
        ttk.OptionMenu(controls, self._seek_amt, 3.0, 1.0, 3.0, 5.0, 10.0).pack(side="left")
        ttk.Label(controls, text="秒").pack(side="left")
        ttk.Button(controls, text="⏩", width=3, command=lambda: self._seek(self._seek_amt.get())).pack(side="left", padx=1)
        ttk.Label(controls, text="速度:").pack(side="left", padx=(12, 2))
        ttk.OptionMenu(controls, self._speed, 1.0, 0.5, 0.75, 1.0, 1.25).pack(side="left")
        ttk.Checkbutton(controls, text="音を鳴らす", variable=self._audio_on).pack(side="left", padx=10)

        ttk.Label(self, textvariable=self._instr, foreground="#666").pack(anchor="w", padx=12, pady=(0, 4))

        # 下部: 実際の五線譜（参照用・編集不可）。再生位置に合わせてカーソルが動く。
        staff_frame = ttk.LabelFrame(self, text="五線譜")
        staff_frame.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.staff = StaffCanvas(staff_frame, mapping=self.mapping, editable=False, height=200)
        self.staff.pack(fill="both", expand=True)
        self.staff.set_score(self.score)

    def _apply_mode_text(self) -> None:
        if self._mode.get() == "step":
            self._instr.set("次に光ったキーを押すと譜面が進みます（テンポ・リズムは自由）。和音は全部押すと進む。 ← / → で送り・戻し")
        else:
            self._instr.set("ノーツが判定ラインに来た瞬間にキーを叩く。 ← / → で秒数の送り・戻し")

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
        self._label_items.clear()
        lw = self._lane_w()
        for i, key in enumerate(self._lanes):
            x = self._lane_x(i)
            if i % 2 == 0:
                c.create_rectangle(x, _TOP_Y, x + lw, _HIT_Y + 10, fill="#151b2b", outline="", tags="static")
            c.create_line(x, _TOP_Y, x, _HIT_Y + 10, fill="#263042", tags="static")
            self._label_items[i] = c.create_text(
                x + lw / 2, _LABEL_Y, text=key, fill="#cfd8e3", font=("Consolas", 12, "bold"), tags="static"
            )
        c.create_line(_PAD, _HIT_Y, _CANVAS_W - _PAD, _HIT_Y, fill="#ffd54f", width=3, tags="static")
        if not self._lanes:
            c.create_text(_CANVAS_W / 2, _CANVAS_H / 2,
                          text="演奏できる音がありません\n（マッピングを確認してください）",
                          fill="#cfd8e3", font=("", 12), justify="center", tags="static")

    # --- モード切替 -----------------------------------------------------------
    def _on_mode_change(self) -> None:
        self._stop_loop()
        self._running = False
        if self.audio is not None:
            self.audio.stop()
        self.canvas.delete("note")
        self._reset_rhythm_items()
        self._draw_static()
        self._apply_mode_text()
        self._start_sec = 0.0
        self._start_idx = 0
        if self._mode.get() == "step":
            self._reset_step_state()
            self._score_var.set(f"0 / {len(self._steps)}")
            self._combo_var.set("")
            self._judge_var.set("")
            self._render_step()
        else:
            self._score_var.set("Score 0")
            self._combo_var.set("")
            self._judge_var.set("")
            self._staff_cursor(-1.0)
        self._pos_var.set("")

    def _stop_loop(self) -> None:
        if self._after is not None:
            try:
                self.after_cancel(self._after)
            except Exception:
                pass
            self._after = None

    def _start(self) -> None:
        if self._mode.get() == "step":
            self._start_step()
        else:
            self._start_rhythm()

    # --- 共通キー入力ディスパッチ --------------------------------------------
    def _on_key(self, event: tk.Event) -> None:
        if event.keysym == "space" and not self._running:
            self._start()
            return
        if event.keysym in ("Left", "Right"):
            amt = self._seek_amt.get()
            self._seek(-amt if event.keysym == "Left" else amt)
            return
        if self._mode.get() == "step":
            self._on_key_step(event)
        else:
            self._on_key_rhythm(event)

    # --- シーク（両モード共通） ----------------------------------------------
    def _seek(self, delta_sec: float) -> None:
        if self._mode.get() == "step":
            self._seek_step(delta_sec)
        else:
            self._seek_rhythm(delta_sec)

    def _staff_cursor(self, beat: float) -> None:
        try:
            self.staff.set_cursor(beat)
        except Exception:
            pass

    def _seek_rhythm(self, delta_sec: float) -> None:
        if not self._notes:
            return
        spb = self._spb()
        total = (self._notes[-1].beat + self._notes[-1].dur_beat) * spb
        if self._running:
            now = time.perf_counter() - self._t0
            new_now = max(0.0, min(now + delta_sec, total))
            self._t0 = time.perf_counter() - new_now
            for n in self._notes:
                t = n.beat * spb
                if t < new_now - _MISS_LATE:
                    n.judged = True
                else:
                    n.judged = False
                    n.hit = False
                    n.missed = False
            if self._audio_on.get() and self.audio is not None and self.audio.is_available():
                self.audio.play_score(self.score, self._eff_bpm(), start_sec=new_now)
            self._pos_var.set(f"{_fmt_time(new_now)} / {_fmt_time(total)}")
            self._staff_cursor(new_now / spb)
        else:
            # 停止中: 開始位置マーカーを動かしてプレビュー
            self.canvas.delete("note")
            self._start_sec = max(0.0, min(self._start_sec + delta_sec, total))
            self._render(self._start_sec, spb)
            self._pos_var.set(f"開始 {_fmt_time(self._start_sec)} / {_fmt_time(total)}")
            self._staff_cursor(self._start_sec / spb)

    def _seek_step(self, delta_sec: float) -> None:
        if not self._steps:
            return
        bpm = self.score.tempo_bpm if self.score.tempo_bpm > 0 else 120.0
        delta_beats = delta_sec * bpm / 60.0
        if self._running:
            base = min(self._cur, len(self._steps) - 1)
            target = self._step_beats[base] + delta_beats
            idx = min(range(len(self._steps)), key=lambda i: abs(self._step_beats[i] - target))
            self._cur = idx
            self._pressed = set()
            self._progress = float(idx)
            self._render_step()
        else:
            base = min(self._start_idx, len(self._steps) - 1)
            target = self._step_beats[base] + delta_beats
            idx = min(range(len(self._steps)), key=lambda i: abs(self._step_beats[i] - target))
            self._start_idx = idx
            self._cur = idx
            self._progress = float(idx)
            self._pressed = set()
            self._render_step()
            self._pos_var.set(f"開始ステップ {idx + 1} / {len(self._steps)}")

    # =====================================================================
    # リズムモード
    # =====================================================================
    def _start_rhythm(self) -> None:
        if self._running or not self._notes:
            return
        self._reset_rhythm_state()
        self._start_btn.configure(state="disabled")
        self._countdown(3)

    def _reset_rhythm_items(self) -> None:
        for n in self._notes:
            if n.item is not None:
                self.canvas.delete(n.item)
                n.item = None

    def _reset_rhythm_state(self) -> None:
        if self.audio is not None:
            self.audio.stop()
        self.canvas.delete("note")  # リザルト等の残りを消す
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

    # 後方互換（テスト等）
    def _reset_state(self) -> None:
        self._reset_rhythm_state()

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
        start_sec = self._start_sec
        spb = self._spb()
        self._t0 = time.perf_counter() - start_sec
        for n in self._notes:
            before = n.beat * spb < start_sec - _MISS_LATE
            n.judged = before
            n.hit = False
            n.missed = False
        if self._audio_on.get() and self.audio is not None and self.audio.is_available():
            self.audio.play_score(self.score, self._eff_bpm(), start_sec=start_sec)
        self._running = True
        self._tick()

    def _tick(self) -> None:
        if not self.winfo_exists() or not self._running:
            return
        now = time.perf_counter() - self._t0
        spb = self._spb()
        for note in self._notes:
            if not note.judged and now - note.beat * spb > _MISS_LATE:
                note.judged = True
                note.missed = True
                self._apply_judgment("Miss", 0)
        self._render(now, spb)
        last_hit = (self._notes[-1].beat + self._notes[-1].dur_beat) * spb if self._notes else 0
        self._pos_var.set(f"{_fmt_time(min(now, last_hit))} / {_fmt_time(last_hit)}")
        self._staff_cursor(now / spb)
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
            ry0 = min(y_tail, y_head - 10)
            color = _C_HIT if note.hit else _C_MISS if note.missed else _C_PENDING
            if note.item is None:
                note.item = c.create_rectangle(x0, ry0, x1, ry1, fill=color, outline="")
            else:
                c.coords(note.item, x0, ry0, x1, ry1)
                c.itemconfig(note.item, fill=color)

    def _on_key_rhythm(self, event: tk.Event) -> None:
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
        self._apply_judgment("Perfect" if best_dt <= _PERFECT else "Good", 100 if best_dt <= _PERFECT else 50)
        self._flash_lane(lane)

    def _flash_lane(self, lane: int) -> None:
        lw = self._lane_w()
        x = self._lane_x(lane)
        fid = self.canvas.create_rectangle(x, _HIT_Y - 14, x + lw, _HIT_Y + 10, fill="#ffffff", outline="")
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
        self._stop_loop()
        total = sum(self._counts.values())
        hits = self._counts["Perfect"] + self._counts["Good"]
        acc = (100.0 * hits / total) if total else 0.0
        self._result_box(
            f"RESULT\n\nScore {self._score}\n"
            f"Perfect {self._counts['Perfect']}   Good {self._counts['Good']}   Miss {self._counts['Miss']}\n"
            f"Max Combo {self._max_combo}   Accuracy {acc:.1f}%"
        )
        self._judge_var.set("FINISH")
        self._start_btn.configure(state="normal", text="▶ もう一度 (Space)")

    # =====================================================================
    # ステップ（送り）モード
    # =====================================================================
    def _reset_step_state(self) -> None:
        self._cur = 0
        self._pressed = set()
        self._progress = 0.0

    def _start_step(self) -> None:
        if not self._steps:
            return
        self._stop_loop()
        self._cur = min(self._start_idx, len(self._steps) - 1)
        self._pressed = set()
        self._progress = float(self._cur)
        self._running = True
        self._judge_var.set("")
        self._start_btn.configure(text="▶ 最初から")
        self._render_step()

    def _on_key_step(self, event: tk.Event) -> None:
        if not self._running or self._cur >= len(self._steps):
            return
        ch = event.char
        if not ch:
            return
        lane = self._char_to_lane.get(ch.lower())
        if lane is None:
            return
        step = self._steps[self._cur]
        if lane in step and lane not in self._pressed:
            self._pressed.add(lane)
            if self._audio_on.get() and self.audio is not None and self.audio.is_available():
                self.audio.play_notes((step[lane],))
            if set(step.keys()) <= self._pressed:
                self._advance_step()
            else:
                self._render_step()

    def _advance_step(self) -> None:
        self._cur += 1
        self._pressed = set()
        if self._cur >= len(self._steps):
            self._finish_step()
        else:
            self._animate_scroll()

    def _animate_scroll(self) -> None:
        if not self.winfo_exists():
            return
        target = float(self._cur)
        diff = target - self._progress
        if abs(diff) < 0.02:
            self._progress = target
            self._render_step()
            return
        self._progress += diff * 0.35
        self._render_step()
        self._after = self.after(16, self._animate_scroll)

    def _render_step(self) -> None:
        c = self.canvas
        c.delete("note")
        lw = self._lane_w()
        cur_lanes = set(self._steps[self._cur].keys()) if self._cur < len(self._steps) else set()
        for lane, item in self._label_items.items():
            c.itemconfig(item, fill="#ffd54f" if lane in cur_lanes else "#cfd8e3")

        lo = max(0, self._cur - 2)
        hi = min(len(self._steps), self._cur + 8)
        for i in range(lo, hi):
            y = _HIT_Y - (i - self._progress) * _STEP_GAP
            if y < _TOP_Y - 20 or y > _HIT_Y + 30:
                continue
            is_cur = i == self._cur
            for lane, midi in self._steps[i].items():
                x0 = self._lane_x(lane) + lw * 0.16
                x1 = self._lane_x(lane) + lw * 0.84
                if is_cur:
                    color = _C_HIT if lane in self._pressed else _C_PENDING
                    c.create_oval(x0, y - 13, x1, y + 13, fill=color, outline="#ffffff", width=2, tags="note")
                else:
                    c.create_oval(x0, y - 10, x1, y + 10, fill=_C_FUTURE, outline="", tags="note")

        self._score_var.set(f"{min(self._cur, len(self._steps))} / {len(self._steps)}")
        self._combo_var.set("")
        if self._steps:
            self._staff_cursor(self._step_beats[min(self._cur, len(self._steps) - 1)])

    def _finish_step(self) -> None:
        self._running = False
        self._stop_loop()
        self.canvas.delete("note")
        self._result_box(f"完了！\n\n{len(self._steps)} ステップを弾き切りました。")
        self._judge_var.set("完了！")
        self._start_btn.configure(text="▶ もう一度 (Space)")

    # --- 共通 -----------------------------------------------------------------
    def _result_box(self, text: str) -> None:
        c = self.canvas
        c.create_rectangle(_CANVAS_W / 2 - 190, _CANVAS_H / 2 - 80, _CANVAS_W / 2 + 190,
                           _CANVAS_H / 2 + 80, fill="#1c2333", outline="#ffd54f", width=2, tags="note")
        c.create_text(_CANVAS_W / 2, _CANVAS_H / 2, text=text, fill="#e8eef7",
                      font=("", 12), justify="center", tags="note")

    def _on_close(self) -> None:
        self._running = False
        self._stop_loop()
        if self.audio is not None:
            self.audio.stop()
        self.destroy()
