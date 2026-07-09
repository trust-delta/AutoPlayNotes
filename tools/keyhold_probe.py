"""SendInput が本当に音長ぶんキーを押し続けているかを、ゲーム無しで測る診断ツール。

自前のウィンドウを最前面で開き、そこへ向けて実際に自動演奏を流し、届いた
KeyPress / KeyRelease の時刻を記録して「意図した押下時間」と突き合わせる。

**安全装置**: 自分のウィンドウが最前面（フォアグラウンド）でなければ、キーを 1 つも
送らずに中止する。合成キー入力はフォーカスのあるウィンドウへ届くため、これが無いと
たまたま開いていたエディタへ文字を打ち込みかねない。

    python tools/keyhold_probe.py

分かること:
  - 押下時間が音長どおりか（＝ player + win_input の経路が正しいか）
  - 同じキーの鳴らし直しで、離してから押すまでの間隔が届いているか
  - 注入した keydown を押しっぱなしにしたとき、OS がオートリピートを出すか
    （出ないはず。メモ帳で文字が連続するなら、それは物理キーの操作）

分からないこと:
  - **ゲームがそれをどう解釈するか。** ここは実機でしか確かめられない。
"""

from __future__ import annotations

import ctypes
import os
import sys
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from autoplaynotes.keymap import KeyMapping  # noqa: E402
from autoplaynotes.model import NoteEvent, Score  # noqa: E402
from autoplaynotes.player import PlaybackOptions, Player  # noqa: E402
from autoplaynotes.win_input import KeySender  # noqa: E402

# BPM 60 → 1 拍 = 1 秒。秒と拍が一致するので読みやすい。
_SCORE = Score(tempo_bpm=60.0, title="probe", events=[
    NoteEvent(0.0, 1.5, (60,), (1.5,)),    # 1.5 秒の保続音
    NoteEvent(0.0, 0.3, (62,), (0.3,)),    # 0.3 秒
    NoteEvent(2.0, 0.5, (60,), (0.5,)),    # 同じキーを鳴らし直す
])
_MAPPING = KeyMapping(name="probe", note_to_key={60: "a", 62: "s"}, sustain=True)
_OPTIONS = PlaybackOptions(count_in_seconds=0.0, gate_ms=40.0, retrigger_gap_ms=25.0)


_GA_ROOT = 2


def _has_foreground(window: tk.Tk) -> bool:
    """自分のウィンドウが最前面か。合成キーの流出を防ぐための確認。

    tk の winfo_id() は内部の子ウィンドウの HWND なので、GetAncestor でトップレベルへ
    上げてから比較する。HWND は 64bit なので restype を明示しないと切り詰められ、
    たまたま一致してしまう危険がある（＝安全装置が壊れる）。
    """
    try:
        user32 = ctypes.WinDLL("user32")
    except OSError:  # pragma: no cover - Windows 以外
        return False
    user32.GetForegroundWindow.restype = ctypes.c_void_p
    user32.GetForegroundWindow.argtypes = []
    user32.GetAncestor.restype = ctypes.c_void_p
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]

    foreground = user32.GetForegroundWindow()
    ours = user32.GetAncestor(ctypes.c_void_p(window.winfo_id()), _GA_ROOT)
    return foreground is not None and ours is not None and int(foreground) == int(ours)


class Probe:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("keyhold probe — 触らずにお待ちください")
        self.root.geometry("560x160")
        self.root.attributes("-topmost", True)
        self.label = tk.Label(self.root, text="フォーカスを確認しています...", font=("Consolas", 11))
        self.label.pack(expand=True)
        self.events: list[tuple[float, bool, str]] = []
        self.t0 = 0.0
        self.root.bind("<KeyPress>", self._on_press)
        self.root.bind("<KeyRelease>", self._on_release)

    def _on_press(self, event: tk.Event) -> None:
        self.events.append((time.perf_counter(), True, (event.char or event.keysym).lower()))

    def _on_release(self, event: tk.Event) -> None:
        self.events.append((time.perf_counter(), False, (event.char or event.keysym).lower()))

    def _await_foreground(self, timeout: float = 8.0) -> bool:
        """最前面になるまで待つ。奪えないことがあるので、クリックを促して待機する。"""
        self.root.lift()
        try:
            self.root.focus_force()
        except tk.TclError:
            pass
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            self.root.update()
            if _has_foreground(self.root):
                return True
            remaining = int(deadline - time.perf_counter()) + 1
            self.label.configure(
                text=f"このウィンドウをクリックしてください（あと {remaining} 秒）\n"
                     f"クリック後はキーボードに触れないでください"
            )
            time.sleep(0.05)
        return False

    def run(self) -> int:
        if not self._await_foreground():
            self.root.destroy()
            print("中止: このウィンドウが最前面になりませんでした。")
            print("      合成キーが他のウィンドウへ流れるのを防ぐため、何も送っていません。")
            print("      ウィンドウをクリックしてフォーカスしてから、もう一度実行してください。")
            return 1
        # クリック直後だと押しっぱなしの物理キーが混ざるので、少し落ち着かせる
        time.sleep(0.3)
        self.root.update()
        self.events.clear()

        self.label.configure(text="測定中... キーボードに触れないでください")
        self.root.update()

        player = Player(KeySender())
        intended, _skipped = player.build_actions(_SCORE, _MAPPING, _OPTIONS)
        self.t0 = time.perf_counter()
        player.play(_SCORE, _MAPPING, _OPTIONS)

        deadline = self.t0 + 4.0
        while time.perf_counter() < deadline:
            self.root.update()
            time.sleep(0.002)
        player.stop()
        player.wait(1.0)
        self.root.destroy()

        return self._report(intended)

    def _report(self, intended: list) -> int:
        def spans(items: list[tuple[float, bool, str]], base: float) -> list[tuple[str, float, float]]:
            open_at: dict[str, float] = {}
            out: list[tuple[str, float, float]] = []
            for t, is_down, key in items:
                if is_down:
                    open_at.setdefault(key, t - base)
                elif key in open_at:
                    out.append((key, open_at.pop(key), t - base))
            return sorted(out, key=lambda s: (s[1], s[0]))

        want = spans([(a.at, a.is_down, a.keys[0]) for a in intended], 0.0)
        got = spans(self.events, self.t0)

        repeats = self._count_repeats()
        print(f"届いた KeyPress/KeyRelease: {len(self.events)} 件")
        print(f"押しっぱなしで観測したオートリピート: {repeats} 回 "
              f"({'想定どおり 0' if repeats == 0 else '⚠ 注入キーがリピートしている'})\n")

        if not got:
            print("⚠ キーイベントが 1 つも届きませんでした。フォーカスが外れた可能性があります。")
            return 1

        print(f"{'key':>4} {'意図(押下→解放)':>20} {'実測':>20} {'押下時間の誤差':>14}")
        for (k1, s1, e1), (k2, s2, e2) in zip(want, got):
            mark = "" if k1 == k2 else f"  ⚠ キー不一致({k1}/{k2})"
            print(f"{k2:>4}   {s1:6.3f} → {e1:6.3f}    {s2:6.3f} → {e2:6.3f}   "
                  f"{((e2 - s2) - (e1 - s1)) * 1000:+8.1f} ms{mark}")

        a_spans = [s for s in got if s[0] == "a"]
        if len(a_spans) >= 2:
            gap = (a_spans[1][1] - a_spans[0][2]) * 1000
            ok = gap >= _OPTIONS.retrigger_gap_ms * 0.5
            print(f"\n同じキーの鳴らし直し: 離してから押すまで {gap:.1f} ms "
                  f"(設定 {_OPTIONS.retrigger_gap_ms:.0f} ms) {'OK' if ok else '⚠ 潰れている'}")
        return 0

    def _count_repeats(self) -> int:
        """離鍵を挟まずに同じキーの押下が続いた回数。"""
        down: set[str] = set()
        repeats = 0
        for _t, is_down, key in self.events:
            if is_down:
                if key in down:
                    repeats += 1
                down.add(key)
            else:
                down.discard(key)
        return repeats


if __name__ == "__main__":
    raise SystemExit(Probe().run())
