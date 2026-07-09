"""演奏範囲（窓）を選ぶダイアログ。

難易度＝自分で弾くキーの範囲。抽象的なスライダーではなく、**選んだ結果を先に見せる**ことで
音楽知識ゼロの人でも決められるようにする。

- 鍵盤の上に「その曲でそのキーが何回押されるか」を棒グラフと数字で重ねる。
  音が固まっているところが、その声部。**メロディ検出は要らない。人が見て決める。**
- ドラッグで連続したキー範囲を選ぶ。
- 選ぶそばから「鍵数 / 必要な指 / あなたが弾く音数」が更新される。
  窓は同時押しを許容するので、**代償を選ぶ前に見せなければ意味が無い**。
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

import customtkinter as ctk

from . import difficulty, theme
from .keymap import KeyMapping, note_name
from .model import Score

_BAR_H = 96          # 棒グラフの領域の高さ
_KEY_H = 58          # 鍵の高さ
_PAD = 12
_MAX_W = 900
_CELL_MIN, _CELL_MAX = 18, 40

# 幹音（白鍵）の音高クラス
_WHITE = {0, 2, 4, 5, 7, 9, 11}

# 鍵の色はテーマではなくピアノから取る。ライト/ダークどちらでも白鍵は白鍵、黒鍵は黒鍵。
# テーマ色を使うと、ダークテーマで「黒鍵のほうが明るい」という逆転が起きる。
_K_WHITE, _K_WHITE_ON = "#e8ebf1", "#a9c6ff"
_K_BLACK, _K_BLACK_ON = "#2a2f3a", "#31589e"
_K_TEXT_ON_WHITE, _K_TEXT_ON_BLACK = "#1f2530", "#e7eaf0"


class KeyWindowDialog(ctk.CTkToplevel):
    """連続したキー範囲を選ぶ。決定すると on_apply(KeySet) が呼ばれる。"""

    def __init__(
        self,
        parent: tk.Misc,
        score: Score,
        mapping: KeyMapping,
        on_apply: Callable[[frozenset[str]], None],
        initial: frozenset[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self.title("演奏範囲を選ぶ")
        self.score = score
        self.mapping = mapping
        self._on_apply = on_apply

        self.layout = difficulty.keyboard(mapping)          # [(キー, 音高)] 低い順
        self.usage = difficulty.key_usage(score, mapping)
        self._peak = max(self.usage.values(), default=0)
        self._index = {key: i for i, (key, _p) in enumerate(self.layout)}

        self._lo, self._hi = self._indices_of(initial) if initial else (0, len(self.layout) - 1)
        self._anchor: int | None = None

        self._cell = self._cell_width()
        self._stats = tk.StringVar(value="")
        self._build_ui()
        self._redraw()

        self.transient(parent)
        self.after(150, self._safe_grab)

    # --- 窓とキャンバス座標の変換 --------------------------------------------
    def _cell_width(self) -> int:
        n = max(1, len(self.layout))
        return max(_CELL_MIN, min(_CELL_MAX, (_MAX_W - 2 * _PAD) // n))

    def _indices_of(self, keys: frozenset[str]) -> tuple[int, int]:
        picked = sorted(self._index[k] for k in keys if k in self._index)
        return (picked[0], picked[-1]) if picked else (0, len(self.layout) - 1)

    def _window(self) -> frozenset[str]:
        return frozenset(key for key, _p in self.layout[self._lo:self._hi + 1])

    def _cell_at(self, x: float) -> int:
        i = int((x - _PAD) // self._cell)
        return max(0, min(len(self.layout) - 1, i))

    def _x(self, i: int) -> int:
        return _PAD + i * self._cell

    # --- UI ------------------------------------------------------------------
    def _build_ui(self) -> None:
        # 説明 2 行 + キャンバス + 集計 + プリセット行 + ボタン行 + 余白
        width = 2 * _PAD + self._cell * len(self.layout)
        self.geometry(f"{max(600, width + 28)}x{_BAR_H + _KEY_H + 220}")
        self.minsize(600, _BAR_H + _KEY_H + 220)

        ctk.CTkLabel(
            self, text_color=theme.pair("subtle"),
            text=("自分で弾くキーの範囲をドラッグで選びます。棒の高さは、その曲でそのキーが押される回数。"
                  "\n音が固まっているところが主旋律です。範囲の外はアプリが受け持ちます。"),
            justify="left",
        ).pack(anchor="w", padx=14, pady=(12, 6))

        pal = theme.palette()
        self.canvas = tk.Canvas(
            self, width=width, height=_BAR_H + _KEY_H + 8,
            background=pal["staff_bg"], highlightthickness=0,
        )
        self.canvas.pack(padx=14)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)

        ctk.CTkLabel(self, textvariable=self._stats,
                     font=ctk.CTkFont(size=14, weight="bold")).pack(pady=(10, 2))

        presets = ctk.CTkFrame(self, fg_color="transparent")
        presets.pack(pady=(2, 6))
        ctk.CTkButton(presets, text="おすすめ（指 1 本）", width=150,
                      command=lambda: self._select_keys(difficulty.suggest_window(self.score, self.mapping, 1))
                      ).pack(side="left", padx=4)
        ctk.CTkButton(presets, text="指 2 本まで", width=110,
                      command=lambda: self._select_keys(difficulty.suggest_window(self.score, self.mapping, 2))
                      ).pack(side="left", padx=4)
        ctk.CTkButton(presets, text="全部（原曲どおり）", width=150,
                      command=lambda: self._select_keys(difficulty.full_window(self.mapping))
                      ).pack(side="left", padx=4)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=14, pady=(6, 14))
        ctk.CTkButton(buttons, text="この範囲で練習", width=140, command=self._apply,
                      **theme.BTN_ACCENT).pack(side="right", padx=(6, 0))
        ctk.CTkButton(buttons, text="キャンセル", width=100, command=self.destroy).pack(side="right")

    def _safe_grab(self) -> None:
        try:
            self.grab_set()
        except tk.TclError:
            pass

    # --- 操作 -----------------------------------------------------------------
    def _on_press(self, event: tk.Event) -> None:
        self._anchor = self._cell_at(event.x)
        self._lo = self._hi = self._anchor
        self._redraw()

    def _on_drag(self, event: tk.Event) -> None:
        if self._anchor is None:
            return
        other = self._cell_at(event.x)
        self._lo, self._hi = min(self._anchor, other), max(self._anchor, other)
        self._redraw()

    def _select_keys(self, keys: frozenset[str]) -> None:
        if keys:
            self._lo, self._hi = self._indices_of(keys)
            self._anchor = None
            self._redraw()

    def _apply(self) -> None:
        self._on_apply(self._window())
        self.destroy()

    # --- 描画 -----------------------------------------------------------------
    def _redraw(self) -> None:
        pal = theme.palette()
        c = self.canvas
        c.delete("all")
        window = self._window()

        for i, (key, pitch) in enumerate(self.layout):
            x0, x1 = self._x(i), self._x(i) + self._cell - 1
            inside = self._lo <= i <= self._hi
            count = self.usage.get(key, 0)

            # 棒グラフ（押される回数）
            if count and self._peak:
                h = max(3, int(_BAR_H * 0.86 * count / self._peak))
                c.create_rectangle(
                    x0 + 2, _BAR_H - h, x1 - 2, _BAR_H,
                    fill=pal["note_active"] if inside else pal["staff_grid"], outline="",
                )
                if self._cell >= 22:
                    c.create_text((x0 + x1) // 2, _BAR_H - h - 8, text=str(count),
                                  fill=pal["text"] if inside else pal["subtle"],
                                  font=(theme.FONT_FAMILY, 8))

            # 鍵。白鍵は必ず黒鍵より明るい（ピアノとして読めること）。
            white = pitch % 12 in _WHITE
            if white:
                fill = _K_WHITE_ON if inside else _K_WHITE
                fg = _K_TEXT_ON_WHITE
            else:
                fill = _K_BLACK_ON if inside else _K_BLACK
                fg = _K_TEXT_ON_BLACK
            c.create_rectangle(x0, _BAR_H + 4, x1, _BAR_H + 4 + _KEY_H,
                               fill=fill, outline=pal["staff_line"])
            c.create_text((x0 + x1) // 2, _BAR_H + 24, text=key.upper(),
                          fill=fg, font=(theme.FONT_MONO, 10, "bold"))
            if self._cell >= 24:
                c.create_text((x0 + x1) // 2, _BAR_H + 46, text=note_name(pitch),
                              fill=fg, font=(theme.FONT_FAMILY, 7))

        # 窓の枠。色ではなく枠で範囲を示す（鍵の白黒を潰さないため）
        if self.layout:
            c.create_rectangle(
                self._x(self._lo) - 1, _BAR_H + 2,
                self._x(self._hi) + self._cell, _BAR_H + 6 + _KEY_H,
                outline=pal["accent"], width=3,
            )
        c.create_line(_PAD, _BAR_H, self._x(len(self.layout)), _BAR_H, fill=pal["staff_grid"])
        self._update_stats(window)

    def _update_stats(self, window: frozenset[str]) -> None:
        if not self.layout:
            self._stats.set("キー割り当てが空です。設定タブで割り当ててください。")
            return
        fingers = difficulty.fingers_needed(self.score, self.mapping, window)
        mine, total = difficulty.note_share(self.score, self.mapping, window)
        theirs = total - mine
        lo_name = note_name(self.layout[self._lo][1])
        hi_name = note_name(self.layout[self._hi][1])
        self._stats.set(
            f"{lo_name}〜{hi_name}　{len(window)} 鍵 ／ 必要な指 {fingers} 本 ／ "
            f"あなたが弾く音 {mine} ・ アプリ {theirs}"
        )
