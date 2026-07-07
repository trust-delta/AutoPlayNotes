"""五線譜のプレビュー & 簡易エディタ（tkinter Canvas）。

- 音高＝縦位置・時間＝横位置で音符を描画（音の長さは右へ伸びる横バー）
- クリックで音符を追加・選択。ドラッグで矩形選択、Ctrl+クリックで選択に追加/除外
- 選択した音符（複数可）に一括で:
    ♯ / ♭ / ♮ の付与、音長の変更、半音・オクターブの上下、時間の移動、削除
    時間の移動は「以降も一緒に」でリップル移動（後続をまとめてずらす）できる
- すべての編集は Undo / Redo 可能（Ctrl+Z / Ctrl+Y）
- 再生中は「演奏済み＝水色」「発音中＝橙」に色が変わり、縦線カーソルが進む
- クリックモードを「ここから再生」にすると、クリック位置から途中再生できる
- 「テキストに反映」で編集結果をテキスト記譜へ変換

音高の縦位置は「幹音（白鍵）」基準で決め、# / b は音符左の記号で示す。
OMR（五線譜画像の認識）等で取り込んだ下書きの修正を想定した作りになっている。
"""

from __future__ import annotations

import time
import tkinter as tk
from typing import Callable

import customtkinter as ctk

from . import theme
from .keymap import KeyMapping
from .model import NoteEvent, Score

# 音高クラス -> (幹音インデックス C=0..B=6, 変化記号 -1/0/+1)
_PC_TO_STEP: list[tuple[int, int]] = [
    (0, 0), (0, 1), (1, 0), (1, 1), (2, 0), (3, 0),
    (3, 1), (4, 0), (4, 1), (5, 0), (5, 1), (6, 0),
]
_STEP_TO_PC = [0, 2, 4, 5, 7, 9, 11]  # C D E F G A B


def midi_to_staff(midi: int) -> tuple[int, int]:
    """MIDI ノート -> (五線ステップ, 変化記号)。ステップは幹音の通し番号。"""
    octave = midi // 12 - 1
    letter_index, accidental = _PC_TO_STEP[midi % 12]
    return octave * 7 + letter_index, accidental


def staff_to_midi(step: int, accidental: int = 0) -> int:
    octave = step // 7
    letter_index = step % 7
    return (octave + 1) * 12 + _STEP_TO_PC[letter_index] + accidental


# 描画定数
_LINE_GAP = 12          # 五線の線間隔(px)
_HALF = _LINE_GAP // 2  # 幹音 1 ステップ分の高さ(px)
_STAFF_TOP = 80         # 一番上の線(F5)の y
_LEFT = 70              # 五線の左端(ト音記号ぶん)
_NOTE_RX = 5
_NOTE_RY = 4

# 五線の各線の幹音ステップ（下から E4,G4,B4,D5,F5）
_TOP_STEP = 38   # F5
_BOTTOM_STEP = 30  # E4
_HEIGHT = 300

# 色はテーマのパレット（theme.palette()）から都度参照する（ライト/ダーク対応）


class _NoteItem:
    __slots__ = ("event", "midi", "x", "y", "x_end", "oval", "bar", "playable")

    def __init__(self, event, midi, x, y, x_end, oval, bar, playable):
        self.event = event
        self.midi = midi
        self.x = x
        self.y = y
        self.x_end = x_end
        self.oval = oval
        self.bar = bar
        self.playable = playable


class StaffCanvas(ctk.CTkFrame):
    """スクロール可能な五線譜キャンバス。"""

    def __init__(
        self,
        parent: tk.Widget,
        mapping: KeyMapping | None = None,
        px_per_beat: int = 48,
        beats_per_bar: int = 4,
        editable: bool = True,
        on_play_from: Callable[[float], None] | None = None,
        audio=None,
        height: int = _HEIGHT,
    ) -> None:
        super().__init__(parent)
        self.score = Score()
        self.mapping = mapping
        self.px_per_beat = px_per_beat
        self.beats_per_bar = beats_per_bar
        self.on_play_from = on_play_from
        self.audio = audio
        self.preview_on = False
        self._height = height

        self.duration = 1.0            # 追加する音符の長さ(拍)
        self.add_accidental = 0        # 追加する音符の変化記号(-1/0/+1)
        self.click_mode = "edit"       # "edit" or "play"

        self._items: list[_NoteItem] = []
        self._cursor_id: int | None = None
        self._play_beat: float | None = None
        self._selection: list[tuple[NoteEvent, int]] = []
        self._undo_stack: list[list[NoteEvent]] = []
        self._redo_stack: list[list[NoteEvent]] = []
        # ドラッグ（矩形選択）の状態
        self._press_xy: tuple[float, float] | None = None
        self._press_hit: _NoteItem | None = None
        self._band_id: int | None = None
        self._dragging = False

        self.configure(fg_color="transparent")
        self.canvas = tk.Canvas(self, background=theme.palette()["staff_bg"],
                                height=self._height, highlightthickness=0)
        hbar = ctk.CTkScrollbar(self, orientation="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=hbar.set)
        self.canvas.pack(side="top", fill="both", expand=True)
        hbar.pack(side="bottom", fill="x")

        if editable:
            self.canvas.bind("<Button-1>", self._on_press)
            self.canvas.bind("<Control-Button-1>", self._on_ctrl_click)
            self.canvas.bind("<B1-Motion>", self._on_drag)
            self.canvas.bind("<ButtonRelease-1>", self._on_release)
            self.canvas.bind("<Button-3>", self._on_right_click)

    # --- 座標変換 -------------------------------------------------------------
    def _y(self, step: int) -> float:
        return _STAFF_TOP + (_TOP_STEP - step) * _HALF

    def _x(self, beat: float) -> float:
        return _LEFT + beat * self.px_per_beat

    def _beat_from_x(self, x: float, grid: float) -> float:
        raw = (x - _LEFT) / self.px_per_beat
        step = grid if grid > 0 else 1.0
        return max(0.0, round(raw / step) * step)

    def _step_from_y(self, y: float) -> int:
        return int(round(_TOP_STEP - (y - _STAFF_TOP) / _HALF))

    def _preview(self, midi_notes: tuple[int, ...]) -> None:
        if self.preview_on and self.audio is not None:
            self.audio.play_notes(midi_notes)

    # --- 楽譜の設定 -----------------------------------------------------------
    def set_score(self, score: Score) -> None:
        self.score = score
        self._selection = []
        self._undo_stack.clear()
        self._redo_stack.clear()
        self.redraw()

    def get_score(self) -> Score:
        return self.score

    # --- 描画 -----------------------------------------------------------------
    def redraw(self) -> None:
        c = self.canvas
        p = theme.palette()
        c.configure(background=p["staff_bg"])
        c.delete("all")
        self._items.clear()
        self._cursor_id = None

        total_beats = max(self.score.total_beats(), 8.0)
        width = self._x(total_beats + 2)
        c.configure(scrollregion=(0, 0, width, self._height))

        for step in range(_BOTTOM_STEP, _TOP_STEP + 1, 2):
            y = self._y(step)
            c.create_line(_LEFT, y, width - 10, y, fill=p["staff_line"])
        c.create_text(_LEFT - 34, self._y(34), text="\U0001D11E",
                      font=("Segoe UI Symbol", 34), fill=p["text"])

        if self.beats_per_bar > 0:
            bar = 0
            while self._x(bar) <= width - 10:
                x = self._x(bar)
                c.create_line(x, self._y(_TOP_STEP), x, self._y(_BOTTOM_STEP),
                              fill=p["staff_grid"])
                bar += self.beats_per_bar

        for event in self.score.events:
            if event.is_rest:
                continue
            x = self._x(event.start_beat)
            x_end = self._x(event.start_beat + event.duration_beat)
            for midi in event.midi_notes:
                self._draw_note(event, midi, x, x_end)

        self._apply_playback_colors()
        self._draw_cursor()

    def _draw_note(self, event: NoteEvent, midi: int, x: float, x_end: float) -> None:
        c = self.canvas
        p = theme.palette()
        step, accidental = midi_to_staff(midi)
        y = self._y(step)
        playable = self.mapping is None or self.mapping.resolve(midi) is not None
        color = p["note"] if playable else p["note_out"]

        if step > _TOP_STEP:
            for s in range(_TOP_STEP + 2, step + 1, 2):
                c.create_line(x - 9, self._y(s), x + 9, self._y(s), fill=p["staff_line"])
        elif step < _BOTTOM_STEP:
            for s in range(_BOTTOM_STEP - 2, step - 1, -2):
                c.create_line(x - 9, self._y(s), x + 9, self._y(s), fill=p["staff_line"])

        bar = None
        if x_end - x > 3:
            bar = c.create_line(x + _NOTE_RX, y, x_end - 2, y, fill=color, width=2)
        oval = c.create_oval(
            x - _NOTE_RX, y - _NOTE_RY, x + _NOTE_RX, y + _NOTE_RY, fill=color, outline=color
        )
        if accidental == 1:
            c.create_text(x - _NOTE_RX - 8, y, text="♯", font=("Segoe UI Symbol", 12), fill=color)
        elif accidental == -1:
            c.create_text(x - _NOTE_RX - 8, y, text="♭", font=("Segoe UI Symbol", 12), fill=color)

        if self._is_selected(event, midi):
            c.create_oval(
                x - _NOTE_RX - 3, y - _NOTE_RY - 3, x + _NOTE_RX + 3, y + _NOTE_RY + 3,
                outline=p["select"], width=2,
            )

        self._items.append(_NoteItem(event, midi, x, y, x_end, oval, bar, playable))

    # --- 再生ハイライト -------------------------------------------------------
    def _color_for(self, item: _NoteItem) -> str:
        p = theme.palette()
        pb = self._play_beat
        if pb is not None and pb >= 0:
            start = item.event.start_beat
            end = start + item.event.duration_beat
            if start <= pb < max(end, start + 1e-6):
                return p["note_active"]
            if end <= pb:
                return p["note_played"]
        return p["note"] if item.playable else p["note_out"]

    def _apply_playback_colors(self) -> None:
        for item in self._items:
            color = self._color_for(item)
            try:
                self.canvas.itemconfig(item.oval, fill=color, outline=color)
                if item.bar is not None:
                    self.canvas.itemconfig(item.bar, fill=color)
            except tk.TclError:
                pass

    # --- 再生カーソル ---------------------------------------------------------
    def _draw_cursor(self) -> None:
        if self._cursor_id is not None:
            self.canvas.delete(self._cursor_id)
            self._cursor_id = None
        if self._play_beat is None or self._play_beat < 0:
            return
        x = self._x(self._play_beat)
        self._cursor_id = self.canvas.create_line(
            x, self._y(_TOP_STEP) - 16, x, self._y(_BOTTOM_STEP) + 16,
            fill=theme.palette()["select"], width=2,
        )

    def set_cursor(self, beat: float) -> None:
        self._play_beat = None if beat < 0 else beat
        self._apply_playback_colors()
        self._draw_cursor()
        if self._play_beat is not None:
            region = self.canvas.cget("scrollregion").split()
            if region:
                total = float(region[2]) or 1.0
                self.canvas.xview_moveto(max(0.0, (self._x(self._play_beat) - 200) / total))

    # --- 選択の管理 -----------------------------------------------------------
    def _is_selected(self, event: NoteEvent, midi: int) -> bool:
        return any(e is event and m == midi for e, m in self._selection)

    def _selected_events(self) -> list[NoteEvent]:
        unique: list[NoteEvent] = []
        for e, _m in self._selection:
            if not any(e is u for u in unique):
                unique.append(e)
        return unique

    def clear_selection(self) -> None:
        self._selection = []

    def select_all(self) -> None:
        self._selection = [(e, m) for e in self.score.events for m in e.midi_notes]
        self.redraw()

    def has_selection(self) -> bool:
        return bool(self._selection)

    def selection_count(self) -> int:
        return len(self._selection)

    # --- 元に戻す / やり直す ----------------------------------------------------
    def _snapshot(self) -> list[NoteEvent]:
        return [
            NoteEvent(e.start_beat, e.duration_beat, tuple(e.midi_notes))
            for e in self.score.events
        ]

    def push_undo(self) -> None:
        """変更を加える直前に呼ぶ。"""
        self._undo_stack.append(self._snapshot())
        if len(self._undo_stack) > 200:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot())
        self.score.events[:] = self._undo_stack.pop()
        self.clear_selection()
        self.redraw()

    def redo(self) -> None:
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot())
        self.score.events[:] = self._redo_stack.pop()
        self.clear_selection()
        self.redraw()

    # --- クリック / ドラッグ処理 -------------------------------------------------
    def _on_press(self, event: tk.Event) -> None:
        self.canvas.focus_set()
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        self._press_xy = (x, y)
        self._press_hit = self._hit_test(x, y)
        self._dragging = False

    def _on_ctrl_click(self, event: tk.Event) -> None:
        """Ctrl+クリック: 選択に追加 / 選択から外す。"""
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        hit = self._hit_test(x, y)
        if hit is None:
            return
        if self._is_selected(hit.event, hit.midi):
            self._selection = [
                (e, m) for e, m in self._selection if not (e is hit.event and m == hit.midi)
            ]
        else:
            self._selection.append((hit.event, hit.midi))
            self._preview((hit.midi,))
        self.redraw()

    def _on_drag(self, event: tk.Event) -> None:
        if self._press_xy is None or self.click_mode == "play":
            return
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        if not self._dragging:
            if abs(x - self._press_xy[0]) < 4 and abs(y - self._press_xy[1]) < 4:
                return
            self._dragging = True
        if self._press_hit is not None:
            return  # 音符の上からのドラッグは矩形選択にしない（誤操作防止）
        x0, y0 = self._press_xy
        if self._band_id is None:
            self._band_id = self.canvas.create_rectangle(
                x0, y0, x, y, outline=theme.palette()["select"], dash=(3, 2)
            )
        else:
            self.canvas.coords(self._band_id, x0, y0, x, y)

    def _on_release(self, event: tk.Event) -> None:
        if self._press_xy is None:
            return
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        x0, y0 = self._press_xy
        press_hit = self._press_hit
        dragging = self._dragging
        self._press_xy = None
        self._press_hit = None
        self._dragging = False
        if self._band_id is not None:
            self.canvas.delete(self._band_id)
            self._band_id = None

        if self.click_mode == "play":
            beat = self._beat_from_x(x, 0.25)
            if self.on_play_from is not None:
                self.on_play_from(beat)
            return

        if dragging:
            if press_hit is None:  # 矩形選択の確定
                lo_x, hi_x = sorted((x0, x))
                lo_y, hi_y = sorted((y0, y))
                self._selection = [
                    (item.event, item.midi)
                    for item in self._items
                    if lo_x <= item.x <= hi_x and lo_y <= item.y <= hi_y
                ]
                self.redraw()
            return

        if press_hit is not None:  # クリック＝単独選択
            self._selection = [(press_hit.event, press_hit.midi)]
            self._preview((press_hit.midi,))
            self.redraw()
            return

        # 空き位置のクリック＝音符の追加
        beat = self._beat_from_x(x0, self.duration)
        step = self._step_from_y(y0)
        midi = staff_to_midi(step, self.add_accidental)
        self.push_undo()
        self._add_note(beat, midi)
        self._preview((midi,))
        self.redraw()

    def _on_right_click(self, event: tk.Event) -> None:
        x = self.canvas.canvasx(event.x)
        y = self.canvas.canvasy(event.y)
        hit = self._hit_test(x, y)
        if hit is not None:
            self.push_undo()
            self._remove(hit.event, hit.midi)
            self.redraw()

    def _hit_test(self, x: float, y: float) -> _NoteItem | None:
        best: _NoteItem | None = None
        best_dist = 14.0 ** 2
        for item in self._items:
            dist = (item.x - x) ** 2 + (item.y - y) ** 2
            if dist < best_dist:
                best_dist = dist
                best = item
        return best

    # --- 編集操作 -------------------------------------------------------------
    def _add_note(self, beat: float, midi: int) -> None:
        for e in self.score.events:
            if not e.is_rest and abs(e.start_beat - beat) < 1e-6:
                if midi not in e.midi_notes:
                    e.midi_notes = tuple(sorted(set(e.midi_notes) | {midi}))
                self._selection = [(e, midi)]
                return
        new_event = NoteEvent(start_beat=beat, duration_beat=self.duration, midi_notes=(midi,))
        self.score.events.append(new_event)
        self.score.events.sort(key=lambda e: e.start_beat)
        self._selection = [(new_event, midi)]

    def _remove(self, event: NoteEvent, midi: int) -> None:
        remaining = tuple(n for n in event.midi_notes if n != midi)
        if remaining:
            event.midi_notes = remaining
        else:
            # 同値の別イベントを消さないよう、同一性で取り除く
            self.score.events[:] = [e for e in self.score.events if e is not event]
        self._selection = [
            (e, m) for e, m in self._selection if not (e is event and m == midi)
        ]

    def _transform_selection(self, fn: Callable[[int], int]) -> None:
        """選択中の全音符の音高を fn で変換する（呼び出し側で push_undo 済み）。"""
        new_selection: list[tuple[NoteEvent, int]] = []
        for event, midi in self._selection:
            new_midi = max(0, min(127, fn(midi)))
            notes = set(event.midi_notes)
            notes.discard(midi)
            notes.add(new_midi)
            event.midi_notes = tuple(sorted(notes))
            new_selection.append((event, new_midi))
        self._selection = new_selection
        if len(new_selection) == 1:
            self._preview((new_selection[0][1],))
        self.redraw()

    # 以下はツールバー / キーから呼ばれる公開操作（複数選択に一括適用）
    def set_selected_accidental(self, accidental: int) -> None:
        if not self._selection:
            return
        self.push_undo()
        self._transform_selection(
            lambda midi: staff_to_midi(midi_to_staff(midi)[0], accidental)
        )

    def nudge_selected_semitone(self, delta: int) -> None:
        if not self._selection:
            return
        self.push_undo()
        self._transform_selection(lambda midi: midi + delta)

    def nudge_selected_octave(self, delta: int) -> None:
        self.nudge_selected_semitone(12 * delta)

    def move_selected_time(self, delta_beats: float, ripple: bool = False) -> None:
        """選択音符の時間移動。ripple=True なら選択位置以降の音符もまとめて動かす。"""
        events = self._selected_events()
        if not events:
            return
        if ripple:
            threshold = min(e.start_beat for e in events)
            targets = [e for e in self.score.events if e.start_beat >= threshold - 1e-9]
        else:
            targets = events
        shift = delta_beats
        if shift < 0:
            shift = max(shift, -min(e.start_beat for e in targets))
        if shift == 0:
            return
        self.push_undo()
        for e in targets:
            e.start_beat += shift
        self.score.events.sort(key=lambda ev: ev.start_beat)
        self.redraw()

    def apply_duration_to_selected(self) -> None:
        events = self._selected_events()
        if not events:
            return
        self.push_undo()
        for e in events:
            e.duration_beat = self.duration
        self.redraw()

    def delete_selected(self) -> None:
        if not self._selection:
            return
        self.push_undo()
        for event, midi in list(self._selection):
            self._remove(event, midi)
        self.redraw()


_DURATIONS = {
    "全音符 (4拍)": 4.0,
    "2分 (2拍)": 2.0,
    "4分 (1拍)": 1.0,
    "8分 (0.5拍)": 0.5,
    "16分 (0.25拍)": 0.25,
}
_ACCIDENTALS = {"♮ ナチュラル": 0, "♯ シャープ": 1, "♭ フラット": -1}


class StaffWindow(ctk.CTkToplevel):
    """五線譜プレビュー / エディタのウィンドウ。"""

    def __init__(
        self,
        parent: tk.Widget,
        score: Score,
        mapping: KeyMapping | None,
        on_reflect: Callable[[str], None],
        on_play: Callable[[Score, float], None],
        audio=None,
    ) -> None:
        super().__init__(parent)
        self.title("五線譜プレビュー / 編集")
        self.geometry("1120x520")
        theme.apply_titlebar(self)
        self._on_reflect = on_reflect
        self._on_play = on_play
        self._audio = audio
        self._audio_after: str | None = None
        self._audio_t0 = 0.0
        self._audio_total = 0.0
        self._audio_spb = 0.5

        self.staff = StaffCanvas(
            self, mapping=mapping, editable=True, on_play_from=self._play_from, audio=audio
        )

        # --- ツールバー 1 行目: 追加設定とモード ---
        bar1 = ctk.CTkFrame(self, fg_color="transparent")
        bar1.pack(fill="x", padx=10, pady=(10, 4))

        ctk.CTkLabel(bar1, text="追加音の長さ:").pack(side="left")
        self._dur = tk.StringVar(value="4分 (1拍)")
        ctk.CTkOptionMenu(bar1, variable=self._dur, values=list(_DURATIONS.keys()),
                          command=self._on_dur_change, width=120).pack(side="left", padx=6)

        ctk.CTkLabel(bar1, text="変化記号:").pack(side="left", padx=(8, 0))
        self._acc = tk.StringVar(value="♮ ナチュラル")
        ctk.CTkOptionMenu(bar1, variable=self._acc, values=list(_ACCIDENTALS.keys()),
                          command=self._on_acc_change, width=120).pack(side="left", padx=6)

        ctk.CTkLabel(bar1, text="クリック:").pack(side="left", padx=(12, 4))
        self._mode = tk.StringVar(value="edit")
        mode_seg = ctk.CTkSegmentedButton(bar1, values=["編集", "ここから再生"],
                                          command=self._on_mode_select)
        mode_seg.set("編集")
        mode_seg.pack(side="left")

        ctk.CTkButton(bar1, text="▶ 先頭から演奏", width=120, command=self._play_all,
                      **theme.BTN_ACCENT).pack(side="right", padx=(6, 0))

        audio_ok = audio is not None and audio.is_available()
        self._preview_var = tk.BooleanVar(value=audio_ok)
        ctk.CTkCheckBox(
            bar1, text="編集時に音を鳴らす", variable=self._preview_var,
            onvalue=True, offvalue=False,
            command=self._on_preview_toggle, state=("normal" if audio_ok else "disabled"),
        ).pack(side="right", padx=(12, 8))
        ctk.CTkButton(bar1, text="■", width=36, command=self._stop_audio,
                      state=("normal" if audio_ok else "disabled")).pack(side="right", padx=2)
        ctk.CTkButton(bar1, text="🔊 通し試聴", width=100, command=self._audition,
                      state=("normal" if audio_ok else "disabled")).pack(side="right", padx=2)
        self.staff.preview_on = audio_ok

        # --- ツールバー 2 行目: 選択中の音符への操作 ---
        bar2 = ctk.CTkFrame(self, fg_color="transparent")
        bar2.pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkButton(bar2, text="↶", width=36, command=self.staff.undo).pack(side="left", padx=2)
        ctk.CTkButton(bar2, text="↷", width=36, command=self.staff.redo).pack(side="left", padx=(2, 10))
        ctk.CTkLabel(bar2, text="選択中:").pack(side="left", padx=(0, 4))
        ctk.CTkButton(bar2, text="♯", width=36,
                      command=lambda: self.staff.set_selected_accidental(1)).pack(side="left", padx=2)
        ctk.CTkButton(bar2, text="♭", width=36,
                      command=lambda: self.staff.set_selected_accidental(-1)).pack(side="left", padx=2)
        ctk.CTkButton(bar2, text="♮", width=36,
                      command=lambda: self.staff.set_selected_accidental(0)).pack(side="left", padx=2)
        ctk.CTkButton(bar2, text="半音▲", width=60,
                      command=lambda: self.staff.nudge_selected_semitone(1)).pack(side="left", padx=2)
        ctk.CTkButton(bar2, text="半音▼", width=60,
                      command=lambda: self.staff.nudge_selected_semitone(-1)).pack(side="left", padx=2)
        ctk.CTkButton(bar2, text="8va▲", width=56,
                      command=lambda: self.staff.nudge_selected_octave(1)).pack(side="left", padx=2)
        ctk.CTkButton(bar2, text="8vb▼", width=56,
                      command=lambda: self.staff.nudge_selected_octave(-1)).pack(side="left", padx=2)
        self._ripple = tk.BooleanVar(value=False)
        ctk.CTkButton(bar2, text="◀", width=36,
                      command=lambda: self._move_time(-1)).pack(side="left", padx=(8, 2))
        ctk.CTkButton(bar2, text="▶", width=36,
                      command=lambda: self._move_time(1)).pack(side="left", padx=2)
        ctk.CTkCheckBox(bar2, text="以降も一緒に", variable=self._ripple,
                        onvalue=True, offvalue=False, width=110).pack(side="left", padx=4)
        ctk.CTkButton(bar2, text="長さを適用", width=90,
                      command=self.staff.apply_duration_to_selected).pack(side="left", padx=4)
        ctk.CTkButton(bar2, text="削除", width=60,
                      command=self.staff.delete_selected).pack(side="left", padx=2)

        ctk.CTkButton(bar2, text="テキストに反映", width=110,
                      command=self._reflect).pack(side="right", padx=(6, 0))
        ctk.CTkButton(bar2, text="全消去", width=70,
                      command=self._clear, **theme.BTN_DANGER).pack(side="right", padx=6)

        ctk.CTkLabel(
            self,
            text="クリック=追加/選択  ドラッグ=まとめて選択  Ctrl+クリック=選択に追加  右クリック=削除"
                 "  ｜  矢印キー=移動  Delete=削除  Ctrl+Z/Y=元に戻す/やり直す  Ctrl+A=全選択",
            text_color=theme.pair("subtle"),
        ).pack(anchor="w", padx=12)

        self.staff.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.staff.set_score(score)

        # キーボードショートカット（選択中の音符を操作）
        self.bind("<Up>", lambda e: self.staff.nudge_selected_semitone(1))
        self.bind("<Down>", lambda e: self.staff.nudge_selected_semitone(-1))
        self.bind("<Left>", lambda e: self._move_time(-1))
        self.bind("<Right>", lambda e: self._move_time(1))
        self.bind("<Delete>", lambda e: self.staff.delete_selected())
        self.bind("<BackSpace>", lambda e: self.staff.delete_selected())
        self.bind("<Control-z>", lambda e: self.staff.undo())
        self.bind("<Control-y>", lambda e: self.staff.redo())
        self.bind("<Control-a>", lambda e: self.staff.select_all())

    def _move_time(self, direction: int) -> None:
        self.staff.move_selected_time(direction * self.staff.duration, ripple=self._ripple.get())

    def _on_dur_change(self, label: str) -> None:
        self.staff.duration = _DURATIONS.get(label, 1.0)

    def _on_acc_change(self, label: str) -> None:
        self.staff.add_accidental = _ACCIDENTALS.get(label, 0)

    def _on_mode_select(self, label: str) -> None:
        self._mode.set("play" if label == "ここから再生" else "edit")
        self.staff.click_mode = self._mode.get()

    def refresh_theme(self) -> None:
        """テーマ切替時にキャンバスの配色を描き直す。"""
        try:
            self.staff.redraw()
        except tk.TclError:
            pass

    def _play_all(self) -> None:
        self._on_play(self.staff.get_score(), 0.0)

    def _play_from(self, beat: float) -> None:
        self._on_play(self.staff.get_score(), beat)

    def _on_preview_toggle(self) -> None:
        self.staff.preview_on = self._preview_var.get()

    def _audition(self) -> None:
        """曲全体を音で試聴（キー送出なし）。カーソルを同期させる。"""
        if self._audio is None or not self._audio.is_available():
            return
        self._stop_audio()
        score = self.staff.get_score()
        if not score.events:
            return
        bpm = score.tempo_bpm if score.tempo_bpm > 0 else 120.0
        total = self._audio.play_score(score, bpm)
        if total <= 0:
            return
        self._audio_spb = 60.0 / bpm
        self._audio_total = total
        self._audio_t0 = time.perf_counter()
        self._audio_tick()

    def _audio_tick(self) -> None:
        if not self.winfo_exists():
            return
        elapsed = time.perf_counter() - self._audio_t0
        if elapsed >= self._audio_total:
            self.staff.set_cursor(-1.0)
            self._audio_after = None
            return
        self.staff.set_cursor(elapsed / self._audio_spb)
        self._audio_after = self.after(50, self._audio_tick)

    def _stop_audio(self) -> None:
        if self._audio is not None:
            self._audio.stop()
        if self._audio_after is not None:
            try:
                self.after_cancel(self._audio_after)
            except Exception:
                pass
            self._audio_after = None
        self.staff.set_cursor(-1.0)

    def _reflect(self) -> None:
        from .text_parser import score_to_text

        self._on_reflect(score_to_text(self.staff.get_score()))

    def _clear(self) -> None:
        self.staff.push_undo()
        self.staff.get_score().events.clear()
        self.staff.clear_selection()
        self.staff.redraw()

    def set_cursor(self, beat: float) -> None:
        try:
            self.staff.set_cursor(beat)
        except tk.TclError:
            pass
