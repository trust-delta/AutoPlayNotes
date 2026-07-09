"""音ゲー型の練習モード（2 モード）。

ゲーム本体には一切キーを送らない自己完結トレーナー。
- 曲で使うキーごとにレーンを作る
- この練習ウィンドウにフォーカスして自分でキーを押す

モード:
1) リズム: 楽譜どおりのテンポでノーツが落ちてくる。判定ライン到達の瞬間に叩く。
   Perfect / Good / Miss ＋ コンボ ＋ スコア。内蔵音声と同期再生。
2) ステップ（送り）: テンポ・リズムは不問。次に光ったキーを押すと譜面が 1 つ進む。
   指の送り順を覚えるための練習。

対象のゲーム内楽器はキーを押している間だけ鳴るため、長い音は「叩く」だけでなく
「押し続けて、正しいところで離す」必要がある。リズムモードは押下と離鍵の両方を判定する。
"""

from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass

import customtkinter as ctk

from . import difficulty, practice_notes, theme
from .keymap import KeyMapping
from .model import Score
from .staff import StaffCanvas

# リズム: タイミング（秒）
_LEAD = 2.0          # 画面上端から判定ラインまで落ちる時間
_PERFECT = 0.05      # これ以内で Perfect
_GOOD = 0.13         # これ以内で Good（＝押下ヒットの許容窓）
_MISS_LATE = 0.16    # 判定ラインをこれ以上過ぎたら見逃し Miss
_LONG_MIN = 0.25     # これ以上の長さの音は「押し続けて離す」ノーツにする
_RELEASE_TOL = 0.15  # 音の終わりからこれ以内に離せば成功

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
_C_HOLD = "#8bc34a"   # 押し続けている最中
_C_MISS = "#9e9e9e"
_C_FUTURE = "#2a3a55"


def _fmt_time(sec: float) -> str:
    sec = max(0.0, sec)
    return f"{int(sec) // 60}:{int(sec) % 60:02d}"


def is_long_note(duration_seconds: float) -> bool:
    """離鍵まで判定する「ロングノート」か。短い音は叩くだけで完結する。"""
    return duration_seconds >= _LONG_MIN


def judge_release(dt: float) -> tuple[str, int]:
    """離鍵の判定。dt は音の終わりからのずれ（秒。負なら早く離した）。

    早く離せば音が途切れ、離し忘れれば鳴り続ける。どちらも Miss。
    """
    if abs(dt) > _RELEASE_TOL:
        return "Miss", 0
    if abs(dt) <= _PERFECT:
        return "Perfect", 100
    return "Good", 50


@dataclass
class _Note:
    lane: int
    beat: float
    dur_beat: float
    judged: bool = False       # 押下を判定済み
    hit: bool = False
    missed: bool = False
    hold_pending: bool = False  # 押下成功、離鍵待ち
    hold_ok: bool = False
    hold_failed: bool = False
    item: int | None = None

    def end_beat(self) -> float:
        return self.beat + self.dur_beat

    def clear_judgment(self) -> None:
        self.judged = self.hit = self.missed = False
        self.hold_pending = self.hold_ok = self.hold_failed = False


class PracticeWindow(ctk.CTkToplevel):
    def __init__(self, parent: tk.Widget, score: Score, mapping: KeyMapping, audio=None,
                 config=None, range_label: str = "", accompaniment: Score | None = None) -> None:
        super().__init__(parent)
        self.title(f"練習モード — {range_label}" if range_label else "練習モード")
        self._range_label = range_label
        # 演奏範囲の外の音。あなたは弾かないが、スピーカーで一緒に鳴らせる。
        # ゲームへは一切送らないので、これはホワイト側の機能。
        self.accompaniment = accompaniment
        self._has_accomp = bool(
            accompaniment is not None
            and any(not e.is_rest for e in accompaniment.events)
        )
        self._merged: Score | None = None
        self.resizable(False, False)
        theme.apply_titlebar(self)
        self.score = score
        self.mapping = mapping
        self.audio = audio
        # 練習メモ（ユーザーの練習メモ＋作り手の気づき backlog の二役）。
        # config があれば practice_notes に永続化、無ければセッション内のみ保持。
        self.config = config
        self._notes_store: dict = config.practice_notes if config is not None else {}
        self._song_key = practice_notes.song_key(getattr(score, "title", ""), len(score.events))

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
        # メトロノームと A-B ループ（リズムモード用）
        self._metro = tk.BooleanVar(value=False)
        self._accomp_on = tk.BooleanVar(value=False)  # 実値は _build_ui で決める
        self._loop_on = tk.BooleanVar(value=False)
        self._loop_a: float | None = None
        self._loop_b: float | None = None
        self._loop_var = tk.StringVar(value="A–B: 未設定")
        self._score_var = tk.StringVar(value="Score 0")
        self._combo_var = tk.StringVar(value="")
        self._judge_var = tk.StringVar(value="")
        self._pos_var = tk.StringVar(value="")
        self._instr = tk.StringVar(value="")

        # ロングノート: レーン -> 離鍵待ちのノーツ。押されているレーンキーの集合。
        self._held: dict[int, _Note] = {}
        self._down_chars: set[str] = set()

        self._build_ui()
        self._draw_static()
        self._apply_mode_text()
        self.bind("<KeyPress>", self._on_key)
        self.bind("<KeyRelease>", self._on_key_release)
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
            # 音域の折り返しで複数の音が同じレーンに落ちることがある。長い方を残す
            # （player と同じ規則。1 レーンに重なったノーツを 2 つ置くと判定が二重になる）。
            longest: dict[int, float] = {}
            for midi, dur in zip(ev.midi_notes, ev.note_durations()):
                key = self.mapping.resolve(midi)
                if key is None:
                    continue
                lane = self._lane_of_key(key)
                if dur > longest.get(lane, -1.0):
                    longest[lane] = dur
            for lane, dur in longest.items():
                notes.append(_Note(lane=lane, beat=ev.start_beat, dur_beat=dur))
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
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(12, 0))
        ctk.CTkLabel(top, text="モード:").pack(side="left", padx=(0, 8))
        mode_seg = ctk.CTkSegmentedButton(top, values=["リズム", "ステップ（送り）"],
                                          command=self._on_mode_select)
        mode_seg.set("リズム")
        mode_seg.pack(side="left")

        hud = ctk.CTkFrame(self, fg_color="transparent")
        hud.pack(fill="x", padx=14, pady=(8, 2))
        ctk.CTkLabel(hud, textvariable=self._score_var,
                     font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")
        ctk.CTkLabel(hud, textvariable=self._combo_var,
                     font=ctk.CTkFont(size=13),
                     text_color=theme.pair("note_active")).pack(side="left", padx=16)
        ctk.CTkLabel(hud, textvariable=self._judge_var,
                     font=ctk.CTkFont(size=15, weight="bold"),
                     text_color=theme.pair("accent")).pack(side="right")
        ctk.CTkLabel(hud, textvariable=self._pos_var,
                     text_color=theme.pair("subtle")).pack(side="right", padx=12)

        self.canvas = tk.Canvas(self, width=_CANVAS_W, height=_CANVAS_H, background="#0f1420",
                                highlightthickness=0)
        self.canvas.pack(padx=14, pady=6)

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=14, pady=(2, 4))
        self._start_btn = ctk.CTkButton(controls, text="▶ スタート (Space)", width=150,
                                        command=self._start, **theme.BTN_ACCENT)
        self._start_btn.pack(side="left")
        ctk.CTkButton(controls, text="⏪", width=36,
                      command=lambda: self._seek(-self._seek_amt.get())).pack(side="left", padx=(12, 2))
        seek_menu = ctk.CTkOptionMenu(controls, width=64, values=["1", "3", "5", "10"],
                                      command=lambda v: self._seek_amt.set(float(v)))
        seek_menu.set("3")
        seek_menu.pack(side="left")
        ctk.CTkLabel(controls, text="秒").pack(side="left", padx=(4, 0))
        ctk.CTkButton(controls, text="⏩", width=36,
                      command=lambda: self._seek(self._seek_amt.get())).pack(side="left", padx=2)
        ctk.CTkLabel(controls, text="速度:").pack(side="left", padx=(12, 4))
        speed_menu = ctk.CTkOptionMenu(controls, width=76, values=["0.5", "0.75", "1.0", "1.25"],
                                       command=lambda v: self._speed.set(float(v)))
        speed_menu.set("1.0")
        speed_menu.pack(side="left")
        ctk.CTkCheckBox(controls, text="音を鳴らす", variable=self._audio_on,
                        onvalue=True, offvalue=False).pack(side="left", padx=12)
        aud_available = self.audio is not None and self.audio.is_available()
        self._accomp_on.set(self._has_accomp and aud_available)
        ctk.CTkCheckBox(
            controls, text="🎹 伴奏（範囲外の音）", variable=self._accomp_on,
            onvalue=True, offvalue=False,
            state=("normal" if (self._has_accomp and aud_available) else "disabled"),
        ).pack(side="left")

        # 練習補助（リズムモード）: メトロノーム + A-B ループ
        aids = ctk.CTkFrame(self, fg_color="transparent")
        aids.pack(fill="x", padx=14, pady=(0, 2))
        aud_ok = self.audio is not None and self.audio.is_available()
        ctk.CTkCheckBox(aids, text="🎵 メトロノーム", variable=self._metro,
                        onvalue=True, offvalue=False,
                        state=("normal" if aud_ok else "disabled")).pack(side="left")
        ctk.CTkLabel(aids, text="｜ A-B ループ:").pack(side="left", padx=(12, 4))
        ctk.CTkButton(aids, text="A設定", width=64,
                      command=lambda: self._set_loop_point("a")).pack(side="left", padx=2)
        ctk.CTkButton(aids, text="B設定", width=64,
                      command=lambda: self._set_loop_point("b")).pack(side="left", padx=2)
        ctk.CTkSwitch(aids, text="ループ", variable=self._loop_on,
                      onvalue=True, offvalue=False, width=70).pack(side="left", padx=6)
        ctk.CTkButton(aids, text="解除", width=54,
                      command=self._clear_loop).pack(side="left", padx=2)
        ctk.CTkLabel(aids, textvariable=self._loop_var,
                     text_color=theme.pair("subtle")).pack(side="left", padx=8)

        # 練習メモ（両モード共通）
        memo_row = ctk.CTkFrame(self, fg_color="transparent")
        memo_row.pack(fill="x", padx=14, pady=(0, 2))
        self._memo_btn = ctk.CTkButton(memo_row, text=self._memo_btn_text(), width=150,
                                       command=self._add_memo)
        self._memo_btn.pack(side="left")
        ctk.CTkButton(memo_row, text="📝 メモ一覧", width=110,
                      command=self._show_memos).pack(side="left", padx=8)
        ctk.CTkLabel(memo_row, text="練習中の気づき（難所・指使い等）を残せます",
                     text_color=theme.pair("subtle")).pack(side="left", padx=8)

        ctk.CTkLabel(self, textvariable=self._instr,
                     text_color=theme.pair("subtle")).pack(anchor="w", padx=16, pady=(0, 4))

        # 下部: 実際の五線譜（参照用・編集不可）。再生位置に合わせてカーソルが動く。
        staff_frame = ctk.CTkFrame(self)
        staff_frame.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        ctk.CTkLabel(staff_frame, text="五線譜", anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=theme.pair("subtle")).pack(fill="x", padx=12, pady=(6, 0))
        self.staff = StaffCanvas(staff_frame, mapping=self.mapping, editable=False, height=200)
        self.staff.pack(fill="both", expand=True, padx=8, pady=(2, 8))
        self.staff.set_score(self.score)

    def _on_mode_select(self, label: str) -> None:
        self._mode.set("step" if label.startswith("ステップ") else "rhythm")
        self._on_mode_change()

    def _apply_mode_text(self) -> None:
        if self._mode.get() == "step":
            text = "次に光ったキーを押すと譜面が進みます（テンポ・リズムは自由）。和音は全部押すと進む。 ← / → で送り・戻し"
        else:
            text = ("ノーツが判定ラインに来た瞬間にキーを叩く。長いノーツは押し続けて、"
                    "終わりで離す。 ← / → で秒数の送り・戻し")
        if self._range_label:
            text += f"　｜　演奏範囲: {self._range_label}"
        self._instr.set(text)

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
    def _lane_char(self, event: tk.Event) -> str | None:
        """イベントがレーンのキーなら、その文字を返す。"""
        ch = (event.char or event.keysym or "").lower()
        return ch if ch in self._char_to_lane else None

    def _on_key(self, event: tk.Event) -> None:
        if event.keysym == "space" and not self._running:
            self._start()
            return
        if event.keysym in ("Left", "Right"):
            amt = self._seek_amt.get()
            self._seek(-amt if event.keysym == "Left" else amt)
            return
        ch = self._lane_char(event)
        if ch is not None:
            # 押しっぱなしにすると OS がキーリピートを送ってくる。ロングノートは
            # 押し続けるのが正解なので、リピートを打鍵として扱ってはいけない。
            if ch in self._down_chars:
                return
            self._down_chars.add(ch)
        if self._mode.get() == "step":
            self._on_key_step(event)
        else:
            self._on_key_rhythm(event)

    def _on_key_release(self, event: tk.Event) -> None:
        ch = self._lane_char(event)
        if ch is None:
            return
        self._down_chars.discard(ch)
        if self._mode.get() != "step":
            self._on_release_rhythm(self._char_to_lane[ch])

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
            self._held.clear()
            for n in self._notes:
                t = n.beat * spb
                n.clear_judgment()
                if t < new_now - _MISS_LATE:
                    n.judged = True
            self._rhythm_audio(new_now, self._loop_b if self._loop_active() else None)
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
        self._held.clear()
        self._down_chars.clear()
        for n in self._notes:
            n.clear_judgment()
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
        end_sec = None
        if self._loop_active():
            start_sec = self._loop_a  # type: ignore[assignment]
            end_sec = self._loop_b
        spb = self._spb()
        self._t0 = time.perf_counter() - start_sec
        for n in self._notes:
            before = n.beat * spb < start_sec - _MISS_LATE
            n.judged = before
            n.hit = False
            n.missed = False
        self._rhythm_audio(start_sec, end_sec)
        self._running = True
        self._tick()

    # --- メトロノーム / A-B ループ --------------------------------------------
    def _audio_score(self, notes: bool, accomp: bool) -> Score:
        """鳴らす譜面を選ぶ。あなたの担当と伴奏（範囲外）の組み合わせ。"""
        if notes and accomp and self.accompaniment is not None:
            if self._merged is None:
                self._merged = difficulty.merge(self.score, self.accompaniment)
            return self._merged
        if accomp and self.accompaniment is not None:
            return self.accompaniment
        return self.score

    def _rhythm_audio(self, start_sec: float, end_sec: float | None = None) -> None:
        """リズムモードの音（あなたの担当＋伴奏＋メトロノーム）。すべてオフなら無音。"""
        if self.audio is None or not self.audio.is_available():
            return
        notes = self._audio_on.get()
        accomp = self._accomp_on.get() and self._has_accomp
        metro = self._metro.get()
        if not (notes or accomp or metro):
            return
        self.audio.play_score(
            self._audio_score(notes, accomp), self._eff_bpm(),
            start_sec=start_sec, end_sec=end_sec,
            include_notes=notes or accomp, metronome=metro,
        )

    def _loop_active(self) -> bool:
        return (self._loop_on.get() and self._loop_a is not None
                and self._loop_b is not None)

    def _cur_pos(self) -> float:
        return (time.perf_counter() - self._t0) if self._running else self._start_sec

    def _set_loop_point(self, which: str) -> None:
        pos = max(0.0, self._cur_pos())
        if which == "a":
            self._loop_a = pos
        else:
            self._loop_b = pos
        if (self._loop_a is not None and self._loop_b is not None
                and self._loop_b <= self._loop_a):
            self._loop_a, self._loop_b = self._loop_b, self._loop_a
        self._update_loop_label()

    def _clear_loop(self) -> None:
        self._loop_a = self._loop_b = None
        self._loop_on.set(False)
        self._update_loop_label()

    def _update_loop_label(self) -> None:
        a = f"{self._loop_a:.1f}" if self._loop_a is not None else "—"
        b = f"{self._loop_b:.1f}" if self._loop_b is not None else "—"
        if self._loop_a is None and self._loop_b is None:
            self._loop_var.set("A–B: 未設定")
        else:
            self._loop_var.set(f"A–B: {a}s – {b}s")

    def _loop_back(self) -> None:
        a = self._loop_a or 0.0
        b = self._loop_b or 0.0
        spb = self._spb()
        self._t0 = time.perf_counter() - a
        self._held.clear()
        for n in self._notes:
            t = n.beat * spb
            if t < a - _MISS_LATE:
                n.clear_judgment()
                n.judged = True
            elif t < b:
                n.clear_judgment()
        self._rhythm_audio(a, b)
        self._after = self.after(16, self._tick)

    def _tick(self) -> None:
        if not self.winfo_exists() or not self._running:
            return
        now = time.perf_counter() - self._t0
        spb = self._spb()
        if self._loop_active() and now >= self._loop_b - 1e-3:  # type: ignore[operator]
            self._loop_back()
            return
        for note in self._notes:
            if not note.judged and now - note.beat * spb > _MISS_LATE:
                note.judged = True
                note.missed = True
                self._apply_judgment("Miss", 0)
        # 離し忘れ（押しっぱなしのまま音の終わりを過ぎた）
        for lane, note in list(self._held.items()):
            if now - note.end_beat() * spb > _RELEASE_TOL:
                del self._held[lane]
                note.hold_pending = False
                note.hold_failed = True
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
            if note.hold_pending:
                color = _C_HOLD
            elif note.missed or note.hold_failed:
                color = _C_MISS
            elif note.hit:
                color = _C_HIT
            else:
                color = _C_PENDING
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
        if is_long_note(best.dur_beat * spb):
            best.hold_pending = True
            self._held[lane] = best

    def _on_release_rhythm(self, lane: int) -> None:
        """ロングノートの離鍵を判定する。短い音は押下だけで完結しているので何もしない。"""
        if not self._running:
            return
        note = self._held.pop(lane, None)
        if note is None:
            return
        note.hold_pending = False
        now = time.perf_counter() - self._t0
        dt = now - note.end_beat() * self._spb()
        judgment, points = judge_release(dt)
        if judgment == "Miss":
            note.hold_failed = True
        else:
            note.hold_ok = True
        self._apply_judgment(judgment, points)

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
        self._held.clear()
        self._down_chars.clear()
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

    # --- 練習メモ -------------------------------------------------------------
    def _current_beat(self) -> float:
        """現在の練習位置（拍）。メモをどこに紐づけるか。無ければ -1。"""
        if self._mode.get() == "step":
            if self._steps:
                return self._step_beats[min(self._cur, len(self._steps) - 1)]
            return -1.0
        spb = self._spb()
        return max(0.0, self._cur_pos() / spb) if spb > 0 else -1.0

    def _memo_btn_text(self) -> str:
        n = practice_notes.note_count(self._notes_store, self._song_key)
        return f"💡 メモ ({n})" if n else "💡 メモ"

    def _refresh_memo_btn(self) -> None:
        if hasattr(self, "_memo_btn"):
            self._memo_btn.configure(text=self._memo_btn_text())

    def _save_notes(self) -> None:
        if self.config is not None:
            self.config.save()

    def _add_memo(self) -> None:
        MemoDialog(self, self._current_beat(), self._on_memo_saved)

    def _on_memo_saved(self, beat: float, tag: str, text: str) -> None:
        note = practice_notes.PracticeNote(
            beat=beat, tag=tag, text=text, created=time.strftime("%Y-%m-%d %H:%M"))
        practice_notes.add_note(self._notes_store, self._song_key, note)
        self._save_notes()
        self._refresh_memo_btn()

    def _show_memos(self) -> None:
        MemoListDialog(self, self._notes_store, self._song_key,
                       on_change=self._refresh_memo_btn, save=self._save_notes)

    def _on_close(self) -> None:
        self._running = False
        self._stop_loop()
        if self.audio is not None:
            self.audio.stop()
        self.destroy()


class MemoDialog(ctk.CTkToplevel):
    """練習メモを1件追加する小ダイアログ（クイックタグ＋自由文）。"""

    def __init__(self, parent: tk.Widget, beat: float, on_save) -> None:
        super().__init__(parent)
        self.title("練習メモを追加")
        self.resizable(False, False)
        theme.apply_titlebar(self)
        self._beat = beat
        self._on_save = on_save
        pos = f"♪ {beat:.1f} 拍あたり" if beat >= 0 else "位置情報なし"
        ctk.CTkLabel(self, text=f"この位置にメモ（{pos}）").pack(
            padx=16, pady=(14, 6), anchor="w")
        self._tag = ctk.CTkSegmentedButton(self, values=list(practice_notes.QUICK_TAGS))
        self._tag.set(practice_notes.QUICK_TAGS[0])
        self._tag.pack(padx=16, pady=4, fill="x")
        self._entry = ctk.CTkEntry(
            self, width=380,
            placeholder_text="気づいたこと（例: ここ指またぎ／テンポ0.75で／サビ暗譜）")
        self._entry.pack(padx=16, pady=8, fill="x")
        self._entry.bind("<Return>", lambda e: self._save())
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(padx=16, pady=(4, 14), fill="x")
        ctk.CTkButton(row, text="保存", command=self._save, **theme.BTN_ACCENT).pack(side="right")
        ctk.CTkButton(row, text="キャンセル", command=self.destroy).pack(side="right", padx=8)
        self.after(120, lambda: (self.focus_force(), self._entry.focus_set()))

    def _save(self) -> None:
        self._on_save(self._beat, self._tag.get(), self._entry.get().strip())
        self.destroy()


class MemoListDialog(ctk.CTkToplevel):
    """現在の曲の練習メモ一覧（削除可）。"""

    def __init__(self, parent: tk.Widget, store: dict, key: str, on_change, save) -> None:
        super().__init__(parent)
        self.title("練習メモ一覧")
        self.geometry("470x430")
        theme.apply_titlebar(self)
        self._store = store
        self._key = key
        self._on_change = on_change
        self._save = save
        ctk.CTkLabel(self, text="この曲の練習メモ",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            padx=14, pady=(12, 4), anchor="w")
        self._list = ctk.CTkScrollableFrame(self)
        self._list.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.after(120, self.focus_force)
        self._render()

    def _render(self) -> None:
        for widget in self._list.winfo_children():
            widget.destroy()
        notes = practice_notes.get_notes(self._store, self._key)
        if not notes:
            ctk.CTkLabel(self._list,
                         text="まだメモはありません。\n練習中に「💡 メモ」で残せます。",
                         text_color=theme.pair("subtle"), justify="left").pack(
                anchor="w", padx=8, pady=8)
            return
        for index, note in enumerate(notes):
            row = ctk.CTkFrame(self._list)
            row.pack(fill="x", pady=3, padx=2)
            ctk.CTkLabel(row, text=note.summary(), anchor="w", justify="left",
                         wraplength=340).pack(side="left", fill="x", expand=True,
                                              padx=(8, 4), pady=6)
            ctk.CTkButton(row, text="削除", width=52,
                          command=lambda i=index: self._delete(i),
                          **theme.BTN_DANGER).pack(side="right", padx=6)

    def _delete(self, index: int) -> None:
        if practice_notes.delete_note(self._store, self._key, index):
            self._save()
            self._on_change()
            self._render()
