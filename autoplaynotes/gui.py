"""tkinter による GUI。"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from . import midi_parser
from .audio import AudioPlayer
from .config import AppConfig
from .hotkey import HotkeyManager
from .keymap import KeyMapping
from .model import Score
from .number_parser import parse_numbers
from .player import PlaybackOptions, Player, preview_lines
from .staff import StaffWindow
from .text_parser import parse_text
from .win_input import KeySender

SAMPLE_NOTATION = """# title: きらきら星
# tempo: 120
# octave: 4
C C G G A A G:2
F F E E D D C:2
G G F F E E D:2
G G F F E E D:2
C C G G A A G:2
F F E E D D C:2
"""


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.config = AppConfig.load()
        self.sender = KeySender()
        self.player = Player(
            self.sender,
            on_status=self._status_threadsafe,
            on_done=self._done_threadsafe,
            on_progress=self._progress_threadsafe,
        )
        self.hotkeys = HotkeyManager()
        self.audio = AudioPlayer()
        self._staff_window: StaffWindow | None = None

        self._source = tk.StringVar(value="text")
        self._midi_path = tk.StringVar(value="")
        self._midi_info: object | None = None  # midi_parser.MidiInfo
        self._midi_selection: set[tuple[int, int]] | None = None
        self._midi_mono = False
        self._midi_octave = 0
        self._mapping_var = tk.StringVar(value=self.config.active_mapping)
        self._status_var = tk.StringVar(value="待機中")

        root.title("AutoPlayNotes - 楽譜オートプレイヤー")
        root.geometry("820x680")
        root.minsize(720, 560)

        self._build_ui()
        self._setup_hotkeys()
        self._log(
            "準備完了。ゲームを起動し楽器を構えたら、この画面で『演奏開始』"
            f"（{self.config.hotkey_start}）を押してください。"
        )
        self._log("音は鳴りません。設定した『音階→キー』に従いキー入力のみ送出します。")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # --- UI 構築 --------------------------------------------------------------
    def _build_ui(self) -> None:
        pad = {"padx": 6, "pady": 4}

        # 上部: マッピングと演奏パラメータ
        top = ttk.LabelFrame(self.root, text="演奏設定")
        top.pack(fill="x", **pad)

        ttk.Label(top, text="キー割り当て:").grid(row=0, column=0, sticky="w", padx=4, pady=4)
        self._mapping_menu = ttk.OptionMenu(
            top, self._mapping_var, self.config.active_mapping,
            *self.config.mapping_names(), command=self._on_mapping_change,
        )
        self._mapping_menu.grid(row=0, column=1, sticky="w", padx=4, pady=4)
        ttk.Button(top, text="割り当てを編集...", command=self._edit_mapping).grid(
            row=0, column=2, sticky="w", padx=4, pady=4
        )
        ttk.Button(top, text="割り当てを確認", command=self._show_mapping).grid(
            row=0, column=3, sticky="w", padx=4, pady=4
        )

        params = ttk.Frame(top)
        params.grid(row=1, column=0, columnspan=6, sticky="w")

        self._tempo = self._add_field(params, "テンポ(BPM)", self.config.tempo_bpm, 0)
        self._octave = self._add_field(params, "既定オクターブ", self.config.default_octave, 2)
        self._countin = self._add_field(params, "開始前カウント(秒)", self.config.count_in_seconds, 4)
        self._gate = self._add_field(params, "押下時間(ms)", self.config.gate_ms, 6)
        self._speed = self._add_field(params, "速度倍率", self.config.speed, 8)

        human = ttk.Frame(top)
        human.grid(row=2, column=0, columnspan=6, sticky="w")
        ttk.Label(human, text="自然さ:", foreground="#444").grid(
            row=0, column=0, sticky="e", padx=(4, 2), pady=4
        )
        self._jitter = self._add_field(human, "タイミング揺れ(±ms)", self.config.timing_jitter_ms, 1)
        self._gatejit = self._add_field(human, "音長揺れ(±%)", self.config.gate_jitter_pct, 3)
        self._roll = self._add_field(human, "和音ロール(ms)", self.config.chord_roll_ms, 5)

        # 中央: 楽譜ソース
        src = ttk.LabelFrame(self.root, text="楽譜")
        src.pack(fill="both", expand=True, **pad)

        radios = ttk.Frame(src)
        radios.pack(fill="x")
        ttk.Radiobutton(
            radios, text="テキスト記譜(CDE)", variable=self._source, value="text",
            command=self._update_source,
        ).pack(side="left", padx=4, pady=4)
        ttk.Radiobutton(
            radios, text="数字譜(1234567)", variable=self._source, value="number",
            command=self._update_source,
        ).pack(side="left", padx=4, pady=4)
        ttk.Radiobutton(
            radios, text="MIDI ファイル", variable=self._source, value="midi",
            command=self._update_source,
        ).pack(side="left", padx=4, pady=4)

        ttk.Button(radios, text="テキストを開く...", command=self._open_text).pack(side="left", padx=4)
        ttk.Button(radios, text="テキストを保存...", command=self._save_text).pack(side="left", padx=4)
        ttk.Button(radios, text="MIDI を選択...", command=self._open_midi).pack(side="left", padx=4)
        ttk.Button(radios, text="トラック...", command=self._open_midi_tracks).pack(side="left", padx=2)
        ttk.Button(radios, text="五線譜で表示/編集", command=self._open_staff).pack(side="left", padx=4)
        ttk.Button(radios, text="プレビュー", command=self._preview).pack(side="left", padx=4)

        midi_row = ttk.Frame(src)
        midi_row.pack(fill="x")
        ttk.Label(midi_row, text="MIDI:").pack(side="left", padx=4)
        ttk.Label(midi_row, textvariable=self._midi_path, foreground="#555").pack(side="left")

        self._notation = tk.Text(src, height=12, wrap="word", font=("Consolas", 11), undo=True)
        self._notation.pack(fill="both", expand=True, padx=4, pady=4)
        self._notation.insert("1.0", SAMPLE_NOTATION)

        # 下部: 操作とログ
        controls = ttk.Frame(self.root)
        controls.pack(fill="x", **pad)
        self._start_btn = ttk.Button(
            controls, text=f"演奏開始 ({self.config.hotkey_start})", command=self._on_start
        )
        self._start_btn.pack(side="left", padx=4)
        self._stop_btn = ttk.Button(
            controls, text=f"停止 ({self.config.hotkey_stop})", command=self._on_stop, state="disabled"
        )
        self._stop_btn.pack(side="left", padx=4)
        audio_state = "normal" if self.audio.is_available() else "disabled"
        ttk.Button(controls, text="🔊 音で試聴", command=self._audio_preview,
                   state=audio_state).pack(side="left", padx=4)
        ttk.Button(controls, text="■ 音停止", command=self.audio.stop,
                   state=audio_state).pack(side="left", padx=2)
        ttk.Label(controls, textvariable=self._status_var, font=("", 10, "bold")).pack(
            side="left", padx=16
        )

        log_frame = ttk.LabelFrame(self.root, text="ログ")
        log_frame.pack(fill="both", expand=True, **pad)
        self._log_text = tk.Text(log_frame, height=8, wrap="word", state="disabled",
                                 font=("Consolas", 10))
        scroll = ttk.Scrollbar(log_frame, command=self._log_text.yview)
        self._log_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self._log_text.pack(side="left", fill="both", expand=True)

        self._update_source()

    def _add_field(self, parent: ttk.Frame, label: str, value: object, col: int) -> ttk.Entry:
        ttk.Label(parent, text=label).grid(row=0, column=col, sticky="e", padx=(8, 2), pady=4)
        entry = ttk.Entry(parent, width=7)
        entry.insert(0, str(value))
        entry.grid(row=0, column=col + 1, sticky="w", pady=4)
        return entry

    # --- ホットキー -----------------------------------------------------------
    def _setup_hotkeys(self) -> None:
        try:
            self.hotkeys.register(
                self.config.hotkey_start, lambda: self.root.after(0, self._on_start)
            )
            self.hotkeys.register(
                self.config.hotkey_stop, lambda: self.root.after(0, self._on_stop)
            )
            self.hotkeys.start()
            if self.hotkeys.failed:
                self._log(
                    "警告: 一部のホットキー登録に失敗しました（他アプリと競合の可能性）。"
                    "画面のボタンからは操作できます。"
                )
        except Exception as exc:
            self._log(f"ホットキー初期化に失敗: {exc}")

    # --- 楽譜の取得 -----------------------------------------------------------
    def _build_score(self) -> Score | None:
        try:
            source = self._source.get()
            if source == "midi":
                path = self._midi_path.get().strip()
                if not path:
                    messagebox.showwarning("MIDI 未選択", "MIDI ファイルを選択してください。")
                    return None
                return midi_parser.build_score(
                    path,
                    selected_keys=self._midi_selection,
                    monophonic=self._midi_mono,
                    octave_shift=self._midi_octave,
                )
            text = self._notation.get("1.0", "end")
            if source == "number":
                return parse_numbers(
                    text,
                    default_tempo=self._read_float(self._tempo, 120.0),
                    default_octave=int(self._read_float(self._octave, 4)),
                )
            return parse_text(
                text,
                default_tempo=self._read_float(self._tempo, 120.0),
                default_octave=int(self._read_float(self._octave, 4)),
            )
        except Exception as exc:
            messagebox.showerror("楽譜の解析エラー", str(exc))
            self._log(f"解析エラー: {exc}")
            return None

    def _current_mapping(self) -> KeyMapping:
        self.config.active_mapping = self._mapping_var.get()
        return self.config.mapping()

    def _options(self, start_beat: float = 0.0) -> PlaybackOptions:
        tempo = self._read_float(self._tempo, 120.0)
        if self._source.get() == "midi":
            # MIDI は自身の BPM を優先。速度倍率のみ適用。
            tempo_override = None
        else:
            tempo_override = tempo
        return PlaybackOptions(
            tempo_bpm=tempo_override,
            count_in_seconds=max(0.0, self._read_float(self._countin, 3.0)),
            gate_ms=max(10.0, self._read_float(self._gate, 40.0)),
            speed=max(0.1, self._read_float(self._speed, 1.0)),
            timing_jitter_ms=max(0.0, self._read_float(self._jitter, 0.0)),
            gate_jitter_pct=max(0.0, self._read_float(self._gatejit, 0.0)),
            chord_roll_ms=max(0.0, self._read_float(self._roll, 0.0)),
            start_beat=max(0.0, start_beat),
        )

    # --- 操作 -----------------------------------------------------------------
    def _on_start(self) -> None:
        if self.player.is_playing:
            return
        score = self._build_score()
        if score is None:
            return
        self._play_score(score)

    def _play_score(self, score: Score, start_beat: float = 0.0) -> None:
        if self.player.is_playing:
            return
        if not score.events:
            messagebox.showwarning("空の楽譜", "演奏できる音がありません。")
            return
        mapping = self._current_mapping()
        try:
            keys = {k for k in mapping.note_to_key.values()}
            self.sender.validate(keys)
        except Exception as exc:
            messagebox.showerror("キー設定エラー", f"割り当てキーに問題があります: {exc}")
            return

        self._save_config_from_ui()
        title = score.title or "(無題)"
        where = f" / {start_beat:.2f}拍から" if start_beat > 0 else ""
        self._log(f"演奏準備: {title} / {len(score.events)} 音 / {score.tempo_bpm:.0f} BPM{where}")
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        try:
            self.player.play(score, mapping, self._options(start_beat))
        except Exception as exc:
            self._log(f"開始に失敗: {exc}")
            self._reset_buttons()

    def _open_staff(self) -> None:
        score = self._build_score()
        if score is None:
            return
        if self._staff_window is not None:
            try:
                self._staff_window.destroy()
            except tk.TclError:
                pass
        window = StaffWindow(
            self.root,
            score,
            self._current_mapping(),
            on_reflect=self._reflect_from_staff,
            on_play=self._play_score,
            audio=self.audio,
        )
        window.protocol("WM_DELETE_WINDOW", lambda: self._close_staff(window))
        self._staff_window = window

    def _close_staff(self, window: StaffWindow) -> None:
        if self._staff_window is window:
            self._staff_window = None
        try:
            window.destroy()
        except tk.TclError:
            pass

    def _reflect_from_staff(self, text: str) -> None:
        self._source.set("text")
        self._update_source()
        self._notation.delete("1.0", "end")
        self._notation.insert("1.0", text)
        self._log("五線譜の編集内容をテキスト記譜へ反映しました。")

    def _on_stop(self) -> None:
        self.audio.stop()
        if self.player.is_playing:
            self.player.stop()
            self._log("停止要求を送信しました。")

    def _audio_preview(self) -> None:
        """曲を音で試聴（キー送出なし・スピーカーから鳴らす）。"""
        if not self.audio.is_available():
            messagebox.showinfo("音声不可", "この環境では音声プレビューを利用できません。")
            return
        score = self._build_score()
        if score is None:
            return
        if not score.events:
            messagebox.showwarning("空の楽譜", "鳴らせる音がありません。")
            return
        if self._source.get() == "midi":
            bpm = score.tempo_bpm
        else:
            bpm = self._read_float(self._tempo, 120.0)
        self._log(f"🔊 音で試聴中（キー送出なし）: {score.title or '(無題)'}")
        self.audio.play_score(score, bpm)

    def _preview(self) -> None:
        score = self._build_score()
        if score is None:
            return
        mapping = self._current_mapping()
        lines = preview_lines(score, mapping)
        self._log(f"--- プレビュー: {score.title or '(無題)'} ({len(score.events)} 音) ---")
        for line in lines:
            self._log(line)

    # --- ファイル操作 ---------------------------------------------------------
    def _open_text(self) -> None:
        path = filedialog.askopenfilename(
            title="テキスト楽譜を開く",
            filetypes=[("テキスト", "*.txt"), ("すべて", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as exc:
            messagebox.showerror("読み込みエラー", str(exc))
            return
        self._notation.delete("1.0", "end")
        self._notation.insert("1.0", content)
        self._source.set("text")
        self._update_source()
        self._log(f"テキスト楽譜を読み込みました: {os.path.basename(path)}")

    def _save_text(self) -> None:
        path = filedialog.asksaveasfilename(
            title="テキスト楽譜を保存",
            defaultextension=".txt",
            filetypes=[("テキスト", "*.txt")],
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._notation.get("1.0", "end"))
        except Exception as exc:
            messagebox.showerror("保存エラー", str(exc))
            return
        self._log(f"保存しました: {os.path.basename(path)}")

    def _open_midi(self) -> None:
        if not midi_parser.is_available():
            messagebox.showinfo(
                "mido が必要です",
                "MIDI 読み込みには mido が必要です。\nコマンドプロンプトで\n\n    pip install mido\n\nを実行してください。",
            )
            return
        path = filedialog.askopenfilename(
            title="MIDI ファイルを開く",
            filetypes=[("MIDI", "*.mid *.midi"), ("すべて", "*.*")],
        )
        if not path:
            return
        try:
            info = midi_parser.inspect_midi(path)
        except Exception as exc:
            messagebox.showerror("MIDI 解析エラー", str(exc))
            return
        self._midi_path.set(path)
        self._midi_info = info
        # 既定選択: ドラム以外を全て
        self._midi_selection = {p.key for p in info.parts if not p.is_drum}
        self._midi_mono = False
        self._midi_octave = 0
        self._source.set("midi")
        self._update_source()
        self._log(
            f"MIDI を選択: {info.title} / パート数 {len(info.parts)} / {info.tempo_bpm:.0f} BPM"
        )
        self._open_midi_tracks()

    def _open_midi_tracks(self) -> None:
        if not self._midi_path.get().strip():
            messagebox.showinfo("MIDI 未選択", "先に「MIDI を選択...」で読み込んでください。")
            return
        info = self._midi_info
        if info is None:
            try:
                info = midi_parser.inspect_midi(self._midi_path.get())
                self._midi_info = info
            except Exception as exc:
                messagebox.showerror("MIDI 解析エラー", str(exc))
                return
        MidiTrackDialog(
            self.root, info,
            selected=self._midi_selection,
            monophonic=self._midi_mono,
            octave=self._midi_octave,
            on_ok=self._apply_midi_tracks,
        )

    def _apply_midi_tracks(self, selected: set, monophonic: bool, octave: int) -> None:
        self._midi_selection = selected
        self._midi_mono = monophonic
        self._midi_octave = octave
        self._source.set("midi")
        self._update_source()
        mono = "単音化" if monophonic else "和音そのまま"
        self._log(
            f"MIDIトラック設定: {len(selected)} パート選択 / {mono} / オクターブ {octave:+d}"
        )

    # --- マッピング編集 -------------------------------------------------------
    def _edit_mapping(self) -> None:
        mapping = self._current_mapping()
        MappingEditor(self.root, mapping, self._on_mapping_saved)

    def _on_mapping_saved(self, name: str, mapping: KeyMapping) -> None:
        self.config.custom_mappings[name] = mapping.to_dict()
        self.config.active_mapping = name
        self._mapping_var.set(name)
        self._refresh_mapping_menu()
        self.config.save()
        self._log(f"キー割り当て『{name}』を保存しました（{len(mapping.note_to_key)} 音）。")

    def _show_mapping(self) -> None:
        mapping = self._current_mapping()
        self._log(f"--- 現在の割り当て『{mapping.name}』/ 音域外: {mapping.out_of_range} ---")
        for line in mapping.as_text().splitlines():
            self._log(line)

    def _refresh_mapping_menu(self) -> None:
        menu = self._mapping_menu["menu"]
        menu.delete(0, "end")
        for name in self.config.mapping_names():
            menu.add_command(
                label=name, command=lambda n=name: self._select_mapping(n)
            )

    def _select_mapping(self, name: str) -> None:
        self._mapping_var.set(name)
        self._on_mapping_change(name)

    def _on_mapping_change(self, name: str) -> None:
        self.config.active_mapping = name
        self._log(f"キー割り当てを『{name}』に切り替えました。")

    # --- 状態同期 -------------------------------------------------------------
    def _update_source(self) -> None:
        # テキスト記譜・数字譜はテキスト欄を使う。MIDI のときだけ無効化。
        use_editor = self._source.get() in ("text", "number")
        self._notation.configure(state="normal" if use_editor else "disabled")

    def _read_float(self, entry: ttk.Entry, default: float) -> float:
        try:
            return float(entry.get().strip())
        except (ValueError, AttributeError):
            return default

    def _save_config_from_ui(self) -> None:
        self.config.active_mapping = self._mapping_var.get()
        self.config.tempo_bpm = self._read_float(self._tempo, 120.0)
        self.config.default_octave = int(self._read_float(self._octave, 4))
        self.config.count_in_seconds = self._read_float(self._countin, 3.0)
        self.config.gate_ms = self._read_float(self._gate, 40.0)
        self.config.speed = self._read_float(self._speed, 1.0)
        self.config.timing_jitter_ms = self._read_float(self._jitter, 0.0)
        self.config.gate_jitter_pct = self._read_float(self._gatejit, 0.0)
        self.config.chord_roll_ms = self._read_float(self._roll, 0.0)
        try:
            self.config.save()
        except Exception:
            pass

    def _reset_buttons(self) -> None:
        self._start_btn.configure(state="normal")
        self._stop_btn.configure(state="disabled")

    # --- スレッド安全なコールバック ------------------------------------------
    def _status_threadsafe(self, message: str) -> None:
        self.root.after(0, lambda: self._set_status(message))

    def _done_threadsafe(self, stopped: bool) -> None:
        self.root.after(0, self._reset_buttons)

    def _progress_threadsafe(self, beat: float, total_beats: float) -> None:
        self.root.after(0, lambda: self._update_cursor(beat))

    def _update_cursor(self, beat: float) -> None:
        if self._staff_window is not None:
            self._staff_window.set_cursor(beat)

    def _set_status(self, message: str) -> None:
        self._status_var.set(message)
        self._log(message)

    def _log(self, message: str) -> None:
        self._log_text.configure(state="normal")
        self._log_text.insert("end", message + "\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _on_close(self) -> None:
        try:
            self.audio.stop()
        except Exception:
            pass
        try:
            self.player.stop()
            self.player.wait(1.0)
        except Exception:
            pass
        try:
            self.sender.release_all()
        except Exception:
            pass
        self._save_config_from_ui()
        self.hotkeys.stop()
        self.root.destroy()


class MappingEditor(tk.Toplevel):
    """『音名 = キー』のテキストで割り当てを編集するダイアログ。"""

    def __init__(self, parent: tk.Tk, mapping: KeyMapping, on_save) -> None:
        super().__init__(parent)
        self.title("キー割り当ての編集")
        self.geometry("420x520")
        self._on_save = on_save

        ttk.Label(
            self, text="1 行に 1 つ『音名 = キー』を記入してください（例: C4 = a）。",
            wraplength=400,
        ).pack(anchor="w", padx=8, pady=(8, 2))

        name_row = ttk.Frame(self)
        name_row.pack(fill="x", padx=8)
        ttk.Label(name_row, text="名前:").pack(side="left")
        self._name = ttk.Entry(name_row)
        self._name.insert(0, mapping.name if mapping.name else "カスタム")
        self._name.pack(side="left", fill="x", expand=True, padx=4)

        oor_row = ttk.Frame(self)
        oor_row.pack(fill="x", padx=8, pady=4)
        ttk.Label(oor_row, text="音域外の扱い:").pack(side="left")
        self._oor = tk.StringVar(value=mapping.out_of_range)
        ttk.OptionMenu(
            oor_row, self._oor, mapping.out_of_range, "transpose", "nearest", "skip"
        ).pack(side="left", padx=4)
        ttk.Label(
            oor_row, text="transpose=移調 / nearest=最寄り音 / skip=無視", foreground="#666"
        ).pack(side="left")

        self._text = tk.Text(self, font=("Consolas", 11), undo=True)
        self._text.pack(fill="both", expand=True, padx=8, pady=4)
        self._text.insert("1.0", mapping.as_text())

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=8, pady=8)
        ttk.Button(buttons, text="保存", command=self._save).pack(side="right", padx=4)
        ttk.Button(buttons, text="キャンセル", command=self.destroy).pack(side="right")

        self.transient(parent)
        self.grab_set()

    def _save(self) -> None:
        name = self._name.get().strip() or "カスタム"
        try:
            mapping = KeyMapping.from_text(
                self._text.get("1.0", "end"), name=name, out_of_range=self._oor.get()  # type: ignore[arg-type]
            )
        except Exception as exc:
            messagebox.showerror("入力エラー", str(exc), parent=self)
            return
        if not mapping.note_to_key:
            messagebox.showwarning("空の割り当て", "少なくとも 1 つ割り当ててください。", parent=self)
            return
        self._on_save(name, mapping)
        self.destroy()


class MidiTrackDialog(tk.Toplevel):
    """MIDI のどのパートを鳴らすか選ぶダイアログ。"""

    def __init__(
        self,
        parent: tk.Tk,
        info,  # midi_parser.MidiInfo
        selected: set | None,
        monophonic: bool,
        octave: int,
        on_ok,
    ) -> None:
        super().__init__(parent)
        self.title("MIDI トラック選択")
        self.geometry("560x480")
        self._on_ok = on_ok
        self._vars: dict[tuple[int, int], tk.BooleanVar] = {}

        ttk.Label(
            self, text="演奏するパートを選んでください（ドラムは通常オフ）。",
            wraplength=520,
        ).pack(anchor="w", padx=10, pady=(10, 4))

        # スクロール可能なパート一覧
        container = ttk.Frame(self)
        container.pack(fill="both", expand=True, padx=10)
        canvas = tk.Canvas(container, highlightthickness=0)
        scroll = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        if not info.parts:
            ttk.Label(inner, text="演奏可能なパートがありません。").pack(anchor="w")
        for part in info.parts:
            default = (part.key in selected) if selected is not None else (not part.is_drum)
            var = tk.BooleanVar(value=default)
            self._vars[part.key] = var
            ttk.Checkbutton(inner, text=part.label(), variable=var).pack(anchor="w", pady=1)

        options = ttk.Frame(self)
        options.pack(fill="x", padx=10, pady=6)
        self._mono = tk.BooleanVar(value=monophonic)
        ttk.Checkbutton(
            options, text="単音化（各時点で最高音だけ＝メロディ抽出）", variable=self._mono
        ).pack(anchor="w")
        oct_row = ttk.Frame(options)
        oct_row.pack(anchor="w", pady=(4, 0))
        ttk.Label(oct_row, text="オクターブ移調:").pack(side="left")
        self._octave = ttk.Spinbox(oct_row, from_=-3, to=3, width=4)
        self._octave.set(str(octave))
        self._octave.pack(side="left", padx=4)
        ttk.Label(oct_row, text="（-3〜+3）", foreground="#666").pack(side="left")

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=10, pady=8)
        ttk.Button(buttons, text="全選択", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(buttons, text="全解除", command=lambda: self._set_all(False)).pack(side="left", padx=4)
        ttk.Button(buttons, text="OK", command=self._ok).pack(side="right", padx=4)
        ttk.Button(buttons, text="キャンセル", command=self.destroy).pack(side="right")

        self.transient(parent)
        self.grab_set()

    def _set_all(self, value: bool) -> None:
        for var in self._vars.values():
            var.set(value)

    def _ok(self) -> None:
        selected = {key for key, var in self._vars.items() if var.get()}
        if not selected:
            messagebox.showwarning("パート未選択", "少なくとも 1 つ選んでください。", parent=self)
            return
        try:
            octave = int(self._octave.get())
        except ValueError:
            octave = 0
        octave = max(-3, min(3, octave))
        self._on_ok(selected, self._mono.get(), octave)
        self.destroy()


def run() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()
