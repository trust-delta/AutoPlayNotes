"""楽譜画像トレース入力（画像を下敷きになぞって音符を置く）。

OMR（自動認識）は使わず、人が画像の上を順にクリックして音符を入力する。
自動認識の品質・待ち時間に依存せず、手書き譜・低画質・简谱以外の楽譜でも
「音符の位置をタップしていくだけ」で音楽知識なしにデータ化できる。

流れ:
  1. 楽譜画像を下敷きに表示（Pillow で読み込み・拡大縮小可）
  2. 音高キャリブレーション: 五線の上下 2 本の線をクリックし、それぞれの音を指定
     → 画像の y ピクセルから音高（五線ステップ）への線形対応ができる
  3. 長さ・変化記号を選び、音符の位置をクリックしていく
     → 音高は画像から読み、拍は「クリック順＋選んだ長さ」で決まる（今の記譜と同じ）
  4. 「楽譜に反映」で Score を生成し、テキスト記譜としてアプリに渡す

複数段（折り返し）の楽譜は、段が変わるたびに「再キャリブレーション」する。
既に置いた音符は記録済みの音高を保持する（後からの再キャリブレーションの影響を受けない）。
"""

from __future__ import annotations

import os
import tkinter as tk
from typing import Callable

import customtkinter as ctk

from . import theme
from .model import NoteEvent, Score
from .staff import midi_to_staff, staff_to_midi

try:
    from PIL import Image, ImageTk

    _PIL_OK = True
except ImportError:  # pragma: no cover - Pillow 未導入環境
    _PIL_OK = False


def is_available() -> bool:
    return _PIL_OK


# 追加音の長さ（拍）と変化記号（半音）。staff.py の同名定義と揃える。
_DURATIONS = {
    "全音符 (4拍)": 4.0,
    "2分 (2拍)": 2.0,
    "4分 (1拍)": 1.0,
    "8分 (0.5拍)": 0.5,
    "16分 (0.25拍)": 0.25,
}
_ACCIDENTALS = {"♮ ナチュラル": 0, "♯ シャープ": 1, "♭ フラット": -1}

# キャリブレーション基準の音（五線の線）。既定はト音記号の上端 F5 / 下端 E4。
_LETTERS = ["C", "D", "E", "F", "G", "A", "B"]


def _pitch_to_step(name: str) -> int:
    """"F5" のような音名を五線ステップ（幹音の通し番号）へ変換する。"""
    letter = name[0].upper()
    octave = int(name[1:])
    return octave * 7 + _LETTERS.index(letter)


def _pitch_options() -> list[str]:
    names: list[str] = []
    for octave in range(2, 7):
        for letter in _LETTERS:
            names.append(f"{letter}{octave}")
    return names


_MAX_DISPLAY_W = 1000  # 初期フィット時の最大表示幅(px)
_ZOOMS = {"フィット": 1.0, "1.25x": 1.25, "1.5x": 1.5, "2x": 2.0, "0.75x": 0.75}


class TraceWindow(ctk.CTkToplevel):
    """楽譜画像を下敷きになぞって音符を入力するウィンドウ。"""

    def __init__(
        self,
        parent: tk.Misc,
        image_path: str,
        on_apply: Callable[[Score], None],
        audio=None,
    ) -> None:
        super().__init__(parent)
        self.title("楽譜画像をなぞって入力（トレース）")
        self.geometry("1180x760")
        theme.apply_titlebar(self)
        self._on_apply = on_apply
        self._audio = audio

        # 画像
        self._src = Image.open(image_path).convert("RGB")
        self._base_fit = min(_MAX_DISPLAY_W / self._src.width, 1.0)
        self._scale = self._base_fit
        self._photo: ImageTk.PhotoImage | None = None

        # キャリブレーション（画像座標）: (step, image_y) を 2 点
        self._cal_top: tuple[int, float] | None = None
        self._cal_bot: tuple[int, float] | None = None
        self._mode = "place"  # "place" / "calib_top" / "calib_bot"

        # 入力中の音符スロット（各要素 = 同時発音のまとまり）
        # {"beat": float, "dur": float, "notes": [(midi, img_x, img_y)]}
        self._slots: list[dict] = []
        self._beat = 0.0
        self._undo: list[tuple[list[dict], float]] = []

        self._dur = tk.StringVar(value="4分 (1拍)")
        self._acc = tk.StringVar(value="♮ ナチュラル")
        self._top_pitch = tk.StringVar(value="F5")
        self._bot_pitch = tk.StringVar(value="E4")
        self._zoom = tk.StringVar(value="フィット")
        self._chord = tk.BooleanVar(value=False)
        audio_ok = audio is not None and audio.is_available()
        self._sound = tk.BooleanVar(value=audio_ok)
        self._status = tk.StringVar()

        self._build_ui(audio_ok)
        self._render_image()
        self._set_status(
            "まず「① 音高キャリブレーション」を押し、五線の上端の線→下端の線の順にクリックしてください。"
        )

        self.transient(parent)
        self.after(200, self._safe_grab)

    def _safe_grab(self) -> None:
        try:
            self.grab_set()
        except tk.TclError:
            pass

    # --- UI -------------------------------------------------------------------
    def _build_ui(self, audio_ok: bool) -> None:
        bar1 = ctk.CTkFrame(self, fg_color="transparent")
        bar1.pack(fill="x", padx=10, pady=(10, 2))
        self._calib_btn = ctk.CTkButton(bar1, text="① 音高キャリブレーション", width=170,
                                        command=self._begin_calibration, **theme.BTN_ACCENT)
        self._calib_btn.pack(side="left")
        ctk.CTkLabel(bar1, text="上端の線=").pack(side="left", padx=(12, 2))
        ctk.CTkOptionMenu(bar1, variable=self._top_pitch, width=72,
                          values=_pitch_options(),
                          command=lambda _v: self._recompute_grid()).pack(side="left")
        ctk.CTkLabel(bar1, text="下端の線=").pack(side="left", padx=(8, 2))
        ctk.CTkOptionMenu(bar1, variable=self._bot_pitch, width=72,
                          values=_pitch_options(),
                          command=lambda _v: self._recompute_grid()).pack(side="left")
        ctk.CTkLabel(bar1, text="表示:").pack(side="left", padx=(12, 2))
        ctk.CTkOptionMenu(bar1, variable=self._zoom, width=90,
                          values=list(_ZOOMS.keys()),
                          command=self._on_zoom).pack(side="left")
        ctk.CTkButton(bar1, text="別の画像...", width=90,
                      command=self._change_image).pack(side="right")

        bar2 = ctk.CTkFrame(self, fg_color="transparent")
        bar2.pack(fill="x", padx=10, pady=(0, 2))
        ctk.CTkLabel(bar2, text="② 音の長さ:").pack(side="left")
        ctk.CTkOptionMenu(bar2, variable=self._dur, width=120,
                          values=list(_DURATIONS.keys())).pack(side="left", padx=6)
        ctk.CTkLabel(bar2, text="変化記号:").pack(side="left", padx=(8, 0))
        ctk.CTkOptionMenu(bar2, variable=self._acc, width=120,
                          values=list(_ACCIDENTALS.keys())).pack(side="left", padx=6)
        ctk.CTkCheckBox(bar2, text="和音として重ねる", variable=self._chord,
                        onvalue=True, offvalue=False, width=120).pack(side="left", padx=8)
        ctk.CTkButton(bar2, text="休符（送る）", width=100,
                      command=self._add_rest).pack(side="left", padx=4)
        ctk.CTkButton(bar2, text="↶ 元に戻す", width=90,
                      command=self._undo_last).pack(side="left", padx=4)
        ctk.CTkCheckBox(bar2, text="音を鳴らす", variable=self._sound,
                        onvalue=True, offvalue=False,
                        state=("normal" if audio_ok else "disabled")).pack(side="left", padx=8)
        ctk.CTkButton(bar2, text="全消去", width=70,
                      command=self._clear_all, **theme.BTN_DANGER).pack(side="right")

        ctk.CTkLabel(self, textvariable=self._status,
                     text_color=theme.pair("subtle")).pack(anchor="w", padx=12, pady=(2, 0))
        ctk.CTkLabel(
            self,
            text="音符の位置をクリック=入力  右クリック=近くの音符を削除  "
                 "｜ 音高は画像から・拍はクリック順×選んだ長さで決まります",
            text_color=theme.pair("subtle"),
        ).pack(anchor="w", padx=12)

        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=10, pady=6)
        self.canvas = tk.Canvas(wrap, background=theme.palette()["staff_bg"],
                                highlightthickness=0)
        vbar = ctk.CTkScrollbar(wrap, orientation="vertical", command=self.canvas.yview)
        hbar = ctk.CTkScrollbar(wrap, orientation="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        vbar.pack(side="right", fill="y")
        hbar.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Button-3>", self._on_right_click)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(buttons, text="楽譜に反映", width=130, command=self._apply,
                      **theme.BTN_ACCENT).pack(side="left")
        ctk.CTkButton(buttons, text="閉じる", width=80,
                      command=self.destroy).pack(side="right")

    # --- 座標変換 -------------------------------------------------------------
    def _to_img(self, cx: float, cy: float) -> tuple[float, float]:
        return cx / self._scale, cy / self._scale

    def _cal_ready(self) -> bool:
        return self._cal_top is not None and self._cal_bot is not None

    def _step_from_img_y(self, img_y: float) -> int:
        top_step, top_y = self._cal_top  # type: ignore[misc]
        bot_step, bot_y = self._cal_bot  # type: ignore[misc]
        if abs(bot_y - top_y) < 1e-6:
            return top_step
        t = (img_y - top_y) / (bot_y - top_y)
        step = top_step - t * (top_step - bot_step)
        return int(round(step))

    def _img_y_from_step(self, step: int) -> float:
        top_step, top_y = self._cal_top  # type: ignore[misc]
        bot_step, bot_y = self._cal_bot  # type: ignore[misc]
        if top_step == bot_step:
            return top_y
        t = (top_step - step) / (top_step - bot_step)
        return top_y + t * (bot_y - top_y)

    # --- 画像描画 -------------------------------------------------------------
    def _render_image(self) -> None:
        w = max(1, int(self._src.width * self._scale))
        h = max(1, int(self._src.height * self._scale))
        resized = self._src.resize((w, h), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(resized)
        self.canvas.delete("all")
        self.canvas.configure(scrollregion=(0, 0, w, h))
        self.canvas.create_image(0, 0, anchor="nw", image=self._photo, tags="img")
        self._draw_grid()
        self._draw_marks()

    def _draw_grid(self) -> None:
        self.canvas.delete("grid")
        if not self._cal_ready():
            return
        p = theme.palette()
        w = self._src.width * self._scale
        top_step = self._cal_top[0]  # type: ignore[index]
        bot_step = self._cal_bot[0]  # type: ignore[index]
        for step in range(bot_step - 6, top_step + 7):
            y = self._img_y_from_step(step) * self._scale
            if step % 2 == 0:  # 線（幹音の偶数ステップ）
                self.canvas.create_line(0, y, w, y, fill=p["select"], width=1,
                                        stipple="gray50", tags="grid")

    def _draw_marks(self) -> None:
        self.canvas.delete("mark")
        p = theme.palette()
        for slot in self._slots:
            for _midi, img_x, img_y in slot["notes"]:
                x = img_x * self._scale
                y = img_y * self._scale
                self.canvas.create_oval(x - 6, y - 5, x + 6, y + 5,
                                        outline=p["note_active"], width=2, tags="mark")
                self.canvas.create_oval(x - 2, y - 2, x + 2, y + 2,
                                        fill=p["note_active"], outline="", tags="mark")

    # --- 入力操作 -------------------------------------------------------------
    def _on_zoom(self, label: str) -> None:
        self._scale = self._base_fit * _ZOOMS.get(label, 1.0)
        self._render_image()

    def _change_image(self) -> None:
        from tkinter import filedialog

        path = filedialog.askopenfilename(
            title="楽譜画像を開く", parent=self,
            filetypes=[("画像", "*.png *.jpg *.jpeg *.bmp *.gif"), ("すべて", "*.*")],
        )
        if not path:
            return
        try:
            self._src = Image.open(path).convert("RGB")
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"画像を開けませんでした: {exc}")
            return
        self._base_fit = min(_MAX_DISPLAY_W / self._src.width, 1.0)
        self._scale = self._base_fit * _ZOOMS.get(self._zoom.get(), 1.0)
        self._cal_top = self._cal_bot = None
        self._render_image()
        self._set_status("画像を差し替えました。音高キャリブレーションからやり直してください。")

    def _begin_calibration(self) -> None:
        self._mode = "calib_top"
        self._set_status("五線の【上端の線】をクリックしてください。")

    def _recompute_grid(self) -> None:
        if self._cal_top is not None:
            self._cal_top = (_pitch_to_step(self._top_pitch.get()), self._cal_top[1])
        if self._cal_bot is not None:
            self._cal_bot = (_pitch_to_step(self._bot_pitch.get()), self._cal_bot[1])
        self._draw_grid()

    def _on_click(self, event: tk.Event) -> None:
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        _img_x, img_y = self._to_img(cx, cy)

        if self._mode == "calib_top":
            self._cal_top = (_pitch_to_step(self._top_pitch.get()), img_y)
            self._mode = "calib_bot"
            self._set_status("次に五線の【下端の線】をクリックしてください。")
            self._draw_grid()
            return
        if self._mode == "calib_bot":
            self._cal_bot = (_pitch_to_step(self._bot_pitch.get()), img_y)
            self._mode = "place"
            self._set_status("キャリブレーション完了。長さを選んで音符をクリックしていってください。")
            self._draw_grid()
            return

        if not self._cal_ready():
            self._set_status("先に「① 音高キャリブレーション」をしてください。")
            return
        self._place_note(cx, cy)

    def _place_note(self, cx: float, cy: float) -> None:
        img_x, img_y = self._to_img(cx, cy)
        step = self._step_from_img_y(img_y)
        acc = _ACCIDENTALS.get(self._acc.get(), 0)
        midi = staff_to_midi(step, acc)
        midi = max(0, min(127, midi))
        # 表示はキャリブレーション上の音高線に吸着させる（どの音になったか分かるように）
        snap_y = self._img_y_from_step(midi_to_staff(midi)[0])

        self._push_undo()
        if self._chord.get() and self._slots:
            self._slots[-1]["notes"].append((midi, img_x, snap_y))
        else:
            dur = _DURATIONS.get(self._dur.get(), 1.0)
            self._slots.append({
                "beat": self._beat, "dur": dur,
                "notes": [(midi, img_x, snap_y)],
            })
            self._beat += dur
        self._preview((midi,))
        self._draw_marks()
        self._update_count()

    def _add_rest(self) -> None:
        self._push_undo()
        self._beat += _DURATIONS.get(self._dur.get(), 1.0)
        self._update_count()

    def _on_right_click(self, event: tk.Event) -> None:
        cx = self.canvas.canvasx(event.x)
        cy = self.canvas.canvasy(event.y)
        best = None
        best_d = 14.0 ** 2
        for si, slot in enumerate(self._slots):
            for ni, (_midi, img_x, img_y) in enumerate(slot["notes"]):
                dx = img_x * self._scale - cx
                dy = img_y * self._scale - cy
                d = dx * dx + dy * dy
                if d < best_d:
                    best_d = d
                    best = (si, ni)
        if best is None:
            return
        self._push_undo()
        si, ni = best
        del self._slots[si]["notes"][ni]
        if not self._slots[si]["notes"]:
            del self._slots[si]
        self._draw_marks()
        self._update_count()

    # --- Undo / 消去 ----------------------------------------------------------
    def _snapshot(self) -> list[dict]:
        return [
            {"beat": s["beat"], "dur": s["dur"], "notes": list(s["notes"])}
            for s in self._slots
        ]

    def _push_undo(self) -> None:
        self._undo.append((self._snapshot(), self._beat))
        if len(self._undo) > 200:
            self._undo.pop(0)

    def _undo_last(self) -> None:
        if not self._undo:
            return
        self._slots, self._beat = self._undo.pop()
        self._draw_marks()
        self._update_count()

    def _clear_all(self) -> None:
        self._push_undo()
        self._slots = []
        self._beat = 0.0
        self._draw_marks()
        self._update_count()

    # --- 補助 -----------------------------------------------------------------
    def _preview(self, midis: tuple[int, ...]) -> None:
        if self._sound.get() and self._audio is not None and self._audio.is_available():
            self._audio.play_notes(midis)

    def _set_status(self, text: str) -> None:
        self._status.set(text)

    def _update_count(self) -> None:
        n = sum(len(s["notes"]) for s in self._slots)
        self._set_status(f"入力済み: {n} 音 / {len(self._slots)} 拍位置 / 現在 {self._beat:.2f} 拍")

    def _build_score(self) -> Score:
        events: list[NoteEvent] = []
        for slot in sorted(self._slots, key=lambda s: s["beat"]):
            midis = tuple(sorted(m for m, _x, _y in slot["notes"]))
            if midis:
                events.append(NoteEvent(slot["beat"], slot["dur"], midis))
        return Score(tempo_bpm=120.0, events=events, title="トレース入力")

    def _apply(self) -> None:
        score = self._build_score()
        if not score.events:
            self._set_status("まだ音符がありません。画像をクリックして入力してください。")
            return
        self._on_apply(score)
        self.destroy()
