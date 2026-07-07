"""customtkinter による GUI。"""

from __future__ import annotations

import os
import tempfile
import threading
import time
import tkinter as tk
from dataclasses import replace
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import midi_parser, musicxml_parser, ocr, omr, theme, trace
from .resources import icon_path
from .audio import AudioPlayer
from .config import AppConfig
from .convert import score_to_keys, score_to_numbers, score_to_text
from .hotkey import HotkeyManager
from .keymap import KeyMapping
from .model import Score
from .number_parser import parse_numbers
from .player import PlaybackOptions, Player, preview_lines
from .playlist import Playlist, PlaylistItem
from .practice import PracticeWindow
from .staff import StaffWindow
from .text_parser import parse_text
from .win_input import KeySender

# プレイリストで曲間に挟む待ち時間（秒）
_BETWEEN_SONGS_GAP = 1.5

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

# 同梱サンプル曲（すべてパブリックドメインの童謡）
SAMPLES: dict[str, str] = {
    "きらきら星": SAMPLE_NOTATION,
    "かえるのうた": """# title: かえるのうた
# tempo: 120
# octave: 4
C D E F E D C R
E F G A G F E R
C R C R C R C R
C:0.5 C:0.5 D:0.5 D:0.5 E:0.5 E:0.5 F:0.5 F:0.5 E D C R
""",
    "メリーさんのひつじ": """# title: メリーさんのひつじ
# tempo: 110
# octave: 4
E D C D E E E:2
D D D:2 E G G:2
E D C D E E E E
D D E D C:4
""",
}

# 楽譜ソースの内部値と表示ラベル
_SOURCE_LABELS = {"text": "テキスト記譜", "number": "数字譜", "midi": "MIDI / MusicXML"}
_LABEL_SOURCES = {v: k for k, v in _SOURCE_LABELS.items()}


class App:
    def __init__(self, root: ctk.CTk, config: AppConfig | None = None) -> None:
        self.root = root
        self.config = config or AppConfig.load()
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

        # プレイリスト状態
        self.playlist = Playlist()
        for item_dict in self.config.playlist:
            try:
                self.playlist.add(PlaylistItem.from_dict(item_dict))
            except Exception:
                pass
        self._playlist_active = False
        self._miniplayer: "MiniPlayerWindow | None" = None

        self._source = tk.StringVar(value="text")
        self._midi_path = tk.StringVar(value="")
        self._midi_info: object | None = None  # midi_parser.MidiInfo
        self._midi_selection: set[tuple[int, int]] | None = None
        self._midi_mono = False
        self._midi_octave = 0
        self._omr_last_progress = 0.0
        self._mapping_var = tk.StringVar(value=self.config.active_mapping)
        self._status_var = tk.StringVar(value="待機中")
        self._loop_var = tk.BooleanVar(value=self.config.loop)
        self._tempo_var = tk.StringVar(value=f"{self.config.tempo_bpm:g}")

        root.title("AutoPlayNotes - 楽譜オートプレイヤー")
        root.geometry("920x900")
        root.minsize(820, 740)
        self._set_window_icon(root)
        theme.apply_titlebar(root)

        self._dark = tk.BooleanVar(value=self.config.dark)
        theme.apply_menu_defaults(root)

        self._build_ui()
        self._apply_tk_palette()
        self._setup_hotkeys()
        self._log(
            "準備完了。ゲームを起動し楽器を構えたら、この画面で『演奏開始』"
            f"（{self.config.hotkey_start}）を押してください。"
        )
        self._log("音は鳴りません。設定した『音階→キー』に従いキー入力のみ送出します。")
        root.protocol("WM_DELETE_WINDOW", self._on_close)

        if self.config.first_run:
            self.config.first_run = False
            try:
                self.config.save()
            except Exception:
                pass
            root.after(300, lambda: WelcomeDialog(root))

    @staticmethod
    def _set_window_icon(window: tk.Misc) -> None:
        path = icon_path()
        if path is None:
            return
        try:
            window.iconbitmap(path)
        except Exception:
            pass
        # CTkToplevel は生成 200ms 後に既定アイコンを設定するため上書きし直す
        try:
            window.after(350, lambda: window.iconbitmap(path))
        except Exception:
            pass

    # --- UI 構築 --------------------------------------------------------------
    def _build_ui(self) -> None:
        # ヘッダ
        header = ctk.CTkFrame(self.root, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 2))
        titles = ctk.CTkFrame(header, fg_color="transparent")
        titles.pack(side="left")
        ctk.CTkLabel(titles, text="AutoPlayNotes",
                     font=ctk.CTkFont(size=22, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(titles, text="楽譜オートプレイヤー ＆ 練習トレーナー",
                     text_color=theme.pair("subtle")).pack(anchor="w")
        ctk.CTkSwitch(header, text="🌙 ダーク", variable=self._dark,
                      onvalue=True, offvalue=False,
                      command=self._toggle_theme).pack(side="right", pady=8)

        # ステータスバー（最下部・タブ外）
        status_bar = ctk.CTkFrame(self.root, corner_radius=0,
                                  fg_color=theme.pair("surface_alt"))
        status_bar.pack(side="bottom", fill="x")
        ctk.CTkLabel(status_bar, textvariable=self._status_var, anchor="w",
                     text_color=theme.pair("subtle")).pack(
            side="left", fill="x", expand=True, padx=12, pady=2)
        ctk.CTkLabel(status_bar,
                     text=f"{self.config.hotkey_start} 開始 ／ {self.config.hotkey_stop} 停止",
                     text_color=theme.pair("subtle")).pack(side="right", padx=12)

        # タブ
        tabs = ctk.CTkTabview(self.root, anchor="w", fg_color="transparent")
        tabs.pack(fill="both", expand=True, padx=12, pady=(0, 4))
        self._tabs = tabs
        tab_play = tabs.add("🎹 演奏")
        tab_playlist = tabs.add("🎵 プレイリスト")
        tab_settings = tabs.add("⚙ 設定")
        tab_log = tabs.add("📄 ログ")

        self._build_play_tab(tab_play)
        self._build_playlist_tab(tab_playlist)
        self._build_settings_tab(tab_settings)
        self._build_log_tab(tab_log)

        self._update_source()

    def _section(self, parent: ctk.CTkFrame, title: str) -> ctk.CTkFrame:
        """角丸カード + 小見出しのセクション枠を作る。"""
        box = ctk.CTkFrame(parent)
        ctk.CTkLabel(box, text=title, anchor="w",
                     font=ctk.CTkFont(size=12, weight="bold"),
                     text_color=theme.pair("subtle")).pack(fill="x", padx=14, pady=(8, 0))
        return box

    def _build_play_tab(self, parent: ctk.CTkFrame) -> None:
        # 楽譜ソースと入力
        src = self._section(parent, "楽譜")
        src.pack(fill="both", expand=True, pady=(4, 8))

        row1 = ctk.CTkFrame(src, fg_color="transparent")
        row1.pack(fill="x", padx=12, pady=(8, 2))
        self._source_seg = ctk.CTkSegmentedButton(
            row1, values=list(_SOURCE_LABELS.values()), command=self._on_source_select)
        self._source_seg.set(_SOURCE_LABELS[self._source.get()])
        self._source_seg.pack(side="left")
        self._sample_menu = tk.Menu(self.root, tearoff=0)
        for name in SAMPLES:
            self._sample_menu.add_command(
                label=name, command=lambda n=name: self._load_sample(n))
        self._sample_btn = ctk.CTkButton(row1, text="🎵 サンプル曲 ▾", width=120,
                                         command=self._post_sample_menu)
        self._sample_btn.pack(side="right")

        files = ctk.CTkFrame(src, fg_color="transparent")
        files.pack(fill="x", padx=12, pady=4)
        ctk.CTkButton(files, text="テキストを開く...", width=120,
                      command=self._open_text).pack(side="left", padx=(0, 6))
        ctk.CTkButton(files, text="保存...", width=70,
                      command=self._save_text).pack(side="left", padx=(0, 6))
        ctk.CTkButton(files, text="MIDI/XML を選択...", width=140,
                      command=self._open_midi).pack(side="left", padx=(0, 6))
        ctk.CTkButton(files, text="パート...", width=80,
                      command=self._open_midi_tracks).pack(side="left", padx=(0, 6))
        ctk.CTkLabel(files, text="ファイル:",
                     text_color=theme.pair("subtle")).pack(side="left", padx=(8, 2))
        ctk.CTkLabel(files, textvariable=self._midi_path, anchor="w",
                     text_color=theme.pair("subtle")).pack(side="left")

        tools = ctk.CTkFrame(src, fg_color="transparent")
        tools.pack(fill="x", padx=12, pady=4)
        self._ocr_menu = tk.Menu(self.root, tearoff=0)
        self._ocr_menu.add_command(label="数字譜の画像ファイルを開く...", command=self._ocr_from_file)
        self._ocr_menu.add_command(label="クリップボードの画像から (Win+Shift+S)",
                                   command=self._ocr_from_clipboard)
        self._ocr_menu.add_separator()
        self._ocr_menu.add_command(label="楽譜画像をなぞって入力（トレース）...",
                                   command=self._trace_from_file)
        self._ocr_menu.add_command(label="五線譜の画像から (OMR・要 oemer)...",
                                   command=self._omr_from_file)
        self._ocr_btn = ctk.CTkButton(tools, text="📷 画像から取り込み ▾", width=160,
                                      command=self._post_ocr_menu)
        self._ocr_btn.pack(side="left", padx=(0, 6))
        ctk.CTkButton(tools, text="五線譜で表示/編集", width=140,
                      command=self._open_staff).pack(side="left", padx=(0, 6))
        ctk.CTkButton(tools, text="🎮 練習モード", width=110,
                      command=self._open_practice).pack(side="left", padx=(0, 6))
        ctk.CTkButton(tools, text="エクスポート/変換", width=130,
                      command=self._open_export).pack(side="left", padx=(0, 6))
        ctk.CTkButton(tools, text="プレビュー", width=90,
                      command=self._preview).pack(side="left")

        self._notation = ctk.CTkTextbox(src, wrap="word",
                                        font=(theme.FONT_MONO, 13), undo=True)
        self._notation.pack(fill="both", expand=True, padx=12, pady=(6, 12))
        self._notation.insert("1.0", SAMPLE_NOTATION)

        # 操作
        controls = ctk.CTkFrame(parent, fg_color="transparent")
        controls.pack(fill="x", pady=(0, 4))
        self._start_btn = ctk.CTkButton(
            controls, text=f"▶ 演奏開始 ({self.config.hotkey_start})", command=self._on_start,
            width=180, height=36, font=ctk.CTkFont(size=14, weight="bold"),
            **theme.BTN_ACCENT,
        )
        self._start_btn.pack(side="left", padx=(0, 6))
        self._stop_btn = ctk.CTkButton(
            controls, text=f"■ 停止 ({self.config.hotkey_stop})", command=self._on_stop,
            state="disabled", width=130, height=36, **theme.BTN_DANGER,
        )
        self._stop_btn.pack(side="left", padx=(0, 6))
        audio_state = "normal" if self.audio.is_available() else "disabled"
        ctk.CTkButton(controls, text="🔊 音で試聴", width=110, height=36,
                      command=self._audio_preview, state=audio_state).pack(side="left", padx=(0, 6))
        ctk.CTkButton(controls, text="■ 音停止", width=90, height=36,
                      command=self.audio.stop, state=audio_state).pack(side="left")

        # テンポ常設（設定タブのテンポと連動）
        tempo_bar = ctk.CTkFrame(controls, fg_color="transparent")
        tempo_bar.pack(side="right")
        ctk.CTkLabel(tempo_bar, text="テンポ(BPM)").pack(side="left", padx=(0, 6))
        ctk.CTkEntry(tempo_bar, width=64, justify="center",
                     textvariable=self._tempo_var).pack(side="left")

    def _on_source_select(self, label: str) -> None:
        self._source.set(_LABEL_SOURCES.get(label, "text"))
        self._update_source()

    def _post_sample_menu(self) -> None:
        self._post_menu(self._sample_btn, self._sample_menu)

    def _post_ocr_menu(self) -> None:
        self._post_menu(self._ocr_btn, self._ocr_menu)

    @staticmethod
    def _post_menu(button: ctk.CTkButton, menu: tk.Menu) -> None:
        menu.tk_popup(button.winfo_rootx(),
                      button.winfo_rooty() + button.winfo_height() + 2)

    def _load_sample(self, name: str) -> None:
        self._source.set("text")
        self._update_source()
        self._notation.delete("1.0", "end")
        self._notation.insert("1.0", SAMPLES[name])
        self._log(f"サンプル曲『{name}』を読み込みました。『🔊 音で試聴』ですぐ確認できます。")

    def _build_playlist_tab(self, parent: ctk.CTkFrame) -> None:
        pl = self._section(parent, "プレイリスト")
        pl.pack(fill="both", expand=True, pady=(4, 8))
        list_row = ctk.CTkFrame(pl, fg_color="transparent")
        list_row.pack(fill="both", expand=True, padx=12, pady=(8, 2))
        self._pl_list = tk.Listbox(list_row, activestyle="none")
        pl_scroll = ctk.CTkScrollbar(list_row, command=self._pl_list.yview)
        self._pl_list.configure(yscrollcommand=pl_scroll.set)
        pl_scroll.pack(side="right", fill="y")
        self._pl_list.pack(side="left", fill="both", expand=True)
        self._pl_list.bind("<Double-Button-1>", lambda e: self._pl_play_selected())

        pl_btns = ctk.CTkFrame(pl, fg_color="transparent")
        pl_btns.pack(fill="x", padx=12, pady=(6, 12))
        ctk.CTkButton(pl_btns, text="＋現在の楽譜", width=110,
                      command=self._pl_add_current).pack(side="left", padx=(0, 4))
        ctk.CTkButton(pl_btns, text="＋ファイル", width=90,
                      command=self._pl_add_files).pack(side="left", padx=4)
        ctk.CTkButton(pl_btns, text="削除", width=60,
                      command=self._pl_remove).pack(side="left", padx=4)
        ctk.CTkButton(pl_btns, text="↑", width=36,
                      command=lambda: self._pl_move(-1)).pack(side="left", padx=4)
        ctk.CTkButton(pl_btns, text="↓", width=36,
                      command=lambda: self._pl_move(1)).pack(side="left", padx=4)
        ctk.CTkButton(pl_btns, text="クリア", width=60,
                      command=self._pl_clear).pack(side="left", padx=4)
        ctk.CTkButton(pl_btns, text="⏮", width=36,
                      command=lambda: self._goto_relative(-1)).pack(side="left", padx=(14, 4))
        ctk.CTkButton(pl_btns, text="▶ 再生", width=90, command=self._pl_play_selected,
                      **theme.BTN_ACCENT).pack(side="left", padx=4)
        ctk.CTkButton(pl_btns, text="⏭", width=36,
                      command=lambda: self._goto_relative(1)).pack(side="left", padx=4)
        ctk.CTkSwitch(pl_btns, text="ループ", variable=self._loop_var,
                      onvalue=True, offvalue=False, width=80).pack(side="left", padx=10)
        ctk.CTkButton(pl_btns, text="ミニプレイヤー", width=110,
                      command=self._open_miniplayer).pack(side="right")
        self._refresh_playlist_listbox()

    def _build_settings_tab(self, parent: ctk.CTkFrame) -> None:
        mapping_box = self._section(parent, "キー割り当て")
        mapping_box.pack(fill="x", pady=(4, 8))
        row = ctk.CTkFrame(mapping_box, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=(6, 12))
        ctk.CTkLabel(row, text="プリセット:").pack(side="left")
        self._mapping_menu = ctk.CTkOptionMenu(
            row, variable=self._mapping_var, values=self.config.mapping_names(),
            command=self._on_mapping_change, width=180,
        )
        self._mapping_menu.pack(side="left", padx=8)
        ctk.CTkButton(row, text="割り当てを編集...", width=130,
                      command=self._edit_mapping).pack(side="left", padx=4)
        ctk.CTkButton(row, text="割り当てを確認", width=120,
                      command=self._show_mapping).pack(side="left", padx=4)

        params_box = self._section(parent, "演奏パラメータ")
        params_box.pack(fill="x", pady=(0, 8))
        params = ctk.CTkFrame(params_box, fg_color="transparent")
        params.pack(fill="x", padx=12, pady=(6, 12))
        self._tempo = self._add_field(params, "テンポ(BPM)", self.config.tempo_bpm, 0, var=self._tempo_var)
        self._octave = self._add_field(params, "既定オクターブ", self.config.default_octave, 2)
        self._countin = self._add_field(params, "開始前カウント(秒)", self.config.count_in_seconds, 4)
        self._gate = self._add_field(params, "押下時間(ms)", self.config.gate_ms, 6)
        self._speed = self._add_field(params, "速度倍率", self.config.speed, 8)

        human_box = self._section(parent, "自然さ（ヒューマナイズ）")
        human_box.pack(fill="x", pady=(0, 8))
        human = ctk.CTkFrame(human_box, fg_color="transparent")
        human.pack(fill="x", padx=12, pady=(6, 12))
        self._jitter = self._add_field(human, "タイミング揺れ(±ms)", self.config.timing_jitter_ms, 0)
        self._gatejit = self._add_field(human, "音長揺れ(±%)", self.config.gate_jitter_pct, 2)
        self._roll = self._add_field(human, "和音ロール(ms)", self.config.chord_roll_ms, 4)

        ctk.CTkLabel(parent, text_color=theme.pair("subtle"),
                     text=(f"ホットキー: {self.config.hotkey_start} 開始 / {self.config.hotkey_stop} 停止"
                           "（ゲーム画面のままでも操作可）  ｜  外観は右上のスイッチで切替")
                     ).pack(anchor="w", padx=6, pady=(4, 0))

    def _build_log_tab(self, parent: ctk.CTkFrame) -> None:
        self._log_text = ctk.CTkTextbox(parent, wrap="word", state="disabled",
                                        font=(theme.FONT_MONO, 12))
        self._log_text.pack(fill="both", expand=True, pady=(4, 8))

    # --- テーマ ---------------------------------------------------------------
    def _apply_tk_palette(self) -> None:
        """customtkinter 対象外（Listbox / tk.Menu）の色をパレットに合わせる。"""
        theme.style_listbox(self._pl_list)
        theme.apply_menu_defaults(self.root)
        p = theme.palette()
        for menu in (getattr(self, "_ocr_menu", None), getattr(self, "_sample_menu", None)):
            if menu is not None:
                menu.configure(bg=p["surface"], fg=p["text"],
                               activebackground=p["accent"], activeforeground=p["accent_fg"])

    def _toggle_theme(self) -> None:
        self.config.dark = bool(self._dark.get())
        theme.set_appearance(self.config.dark)
        self._apply_tk_palette()
        theme.apply_titlebar(self.root)
        if self._staff_window is not None:
            try:
                self._staff_window.refresh_theme()
            except Exception:
                pass
        try:
            self.config.save()
        except Exception:
            pass

    def _add_field(self, parent: ctk.CTkFrame, label: str, value: object, col: int,
                   var: tk.StringVar | None = None) -> ctk.CTkEntry:
        ctk.CTkLabel(parent, text=label).grid(row=0, column=col, sticky="e", padx=(14, 4), pady=4)
        if var is not None:
            entry = ctk.CTkEntry(parent, width=64, justify="center", textvariable=var)
        else:
            entry = ctk.CTkEntry(parent, width=64, justify="center")
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
                    messagebox.showwarning("ファイル未選択", "MIDI / MusicXML ファイルを選択してください。")
                    return None
                build = (musicxml_parser.build_score
                         if musicxml_parser.is_musicxml_path(path) else midi_parser.build_score)
                return build(
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
        """単曲を再生（エディタ/五線譜から）。プレイリスト再生ではない。"""
        if self.player.is_playing:
            return
        if not score.events:
            messagebox.showwarning("空の楽譜", "演奏できる音がありません。")
            return
        self._playlist_active = False
        title = score.title or "(無題)"
        where = f" / {start_beat:.2f}拍から" if start_beat > 0 else ""
        self._log(f"演奏準備: {title} / {len(score.events)} 音 / {score.tempo_bpm:.0f} BPM{where}")
        self._begin(score, self._options(start_beat))

    def _begin(self, score: Score, options: PlaybackOptions) -> bool:
        """検証してプレイヤーを起動する共通処理。成功なら True。"""
        mapping = self._current_mapping()
        try:
            self.sender.validate(set(mapping.note_to_key.values()))
        except Exception as exc:
            messagebox.showerror("キー設定エラー", f"割り当てキーに問題があります: {exc}")
            return False
        self._save_config_from_ui()
        self._start_btn.configure(state="disabled")
        self._stop_btn.configure(state="normal")
        try:
            self.player.play(score, mapping, options)
        except Exception as exc:
            self._log(f"開始に失敗: {exc}")
            self._reset_buttons()
            return False
        self._notify_mini()
        return True

    # --- プレイリスト ---------------------------------------------------------
    def _refresh_playlist_listbox(self) -> None:
        self._pl_list.delete(0, "end")
        for i, item in enumerate(self.playlist.items):
            marker = "▶ " if (i == self.playlist.index and self._playlist_active) else "   "
            kind = {"text": "CDE", "number": "数字", "midi": "MIDI"}.get(item.kind, item.kind)
            self._pl_list.insert("end", f"{marker}{i + 1}. {item.name}  [{kind}]")
        if self.playlist.items:
            self._pl_list.selection_clear(0, "end")
            self._pl_list.selection_set(self.playlist.index)

    def _selected_index(self) -> int:
        sel = self._pl_list.curselection()
        return sel[0] if sel else self.playlist.index

    def _pl_add_current(self) -> None:
        source = self._source.get()
        if source == "midi":
            path = self._midi_path.get().strip()
            if not path:
                messagebox.showwarning("MIDI 未選択", "先に MIDI を選択してください。")
                return
            name = os.path.splitext(os.path.basename(path))[0]
            item = PlaylistItem(
                name=name, kind="midi", midi_path=path,
                midi_selection=list(self._midi_selection) if self._midi_selection else None,
                midi_mono=self._midi_mono, midi_octave=self._midi_octave,
            )
        else:
            text = self._notation.get("1.0", "end")
            tempo = self._read_float(self._tempo, 120.0)
            octave = int(self._read_float(self._octave, 4))
            item = PlaylistItem(
                name="(名称未設定)", kind=("number" if source == "number" else "text"),
                text=text, tempo=tempo, octave=octave,
            )
            item.name = self._guess_name(item)
        self.playlist.add(item)
        self._persist_playlist()
        self._refresh_playlist_listbox()
        self._log(f"プレイリストに追加: {item.name}")

    def _guess_name(self, item: PlaylistItem) -> str:
        try:
            title = item.build_score().title
        except Exception:
            title = ""
        return title or f"曲{len(self.playlist.items) + 1}"

    def _pl_add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="プレイリストに追加",
            filetypes=[("楽譜/MIDI/MusicXML", "*.txt *.mid *.midi *.musicxml *.xml *.mxl"),
                       ("テキスト", "*.txt"), ("MIDI", "*.mid *.midi"),
                       ("MusicXML", "*.musicxml *.xml *.mxl"), ("すべて", "*.*")],
        )
        for path in paths:
            ext = os.path.splitext(path)[1].lower()
            name = os.path.splitext(os.path.basename(path))[0]
            if ext in (".mid", ".midi") or musicxml_parser.is_musicxml_path(path):
                if ext in (".mid", ".midi") and not midi_parser.is_available():
                    messagebox.showinfo("mido が必要です", "MIDI には 'pip install mido' が必要です。")
                    continue
                self.playlist.add(PlaylistItem(name=name, kind="midi", midi_path=path))
            else:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = f.read()
                except Exception as exc:
                    self._log(f"読み込み失敗: {os.path.basename(path)} ({exc})")
                    continue
                self.playlist.add(PlaylistItem(name=name, kind="text", text=content))
        self._persist_playlist()
        self._refresh_playlist_listbox()

    def _pl_remove(self) -> None:
        i = self._selected_index()
        if self.playlist.items:
            self.playlist.remove(i)
            self._persist_playlist()
            self._refresh_playlist_listbox()

    def _pl_move(self, delta: int) -> None:
        i = self._selected_index()
        j = self.playlist.move(i, delta)
        if j != i:
            self._persist_playlist()
            self._refresh_playlist_listbox()
            self._pl_list.selection_clear(0, "end")
            self._pl_list.selection_set(j)

    def _pl_clear(self) -> None:
        self.playlist.clear()
        self._persist_playlist()
        self._refresh_playlist_listbox()

    def _pl_play_selected(self) -> None:
        if not self.playlist.items:
            messagebox.showinfo("プレイリスト空", "先に曲を追加してください。")
            return
        if self.player.is_playing:
            return
        self.playlist.set_index(self._selected_index())
        self._playlist_active = True
        self._play_current_item(first=True)

    def _play_current_item(self, first: bool) -> None:
        item = self.playlist.current()
        if item is None:
            self._end_playlist()
            return
        try:
            score = item.build_score()
        except Exception as exc:
            self._log(f"スキップ（{item.name}）: {exc}")
            self._after_song()
            return
        if not score.events:
            self._log(f"空のためスキップ: {item.name}")
            self._after_song()
            return
        count_in = max(0.0, self._read_float(self._countin, 3.0)) if first else _BETWEEN_SONGS_GAP
        options = replace(self._options(), tempo_bpm=None, count_in_seconds=count_in)
        total = len(self.playlist.items)
        self._log(f"▶ [{self.playlist.index + 1}/{total}] {item.name}（{len(score.events)} 音）")
        self._refresh_playlist_listbox()
        if not self._begin(score, options):
            self._end_playlist()

    def _after_song(self) -> None:
        """1 曲終了後、次へ進む / ループ / 終了。"""
        if self.playlist.has_next():
            self.playlist.advance()
            self._play_current_item(first=False)
        elif self._loop_var.get() and self.playlist.items:
            self.playlist.set_index(0)
            self._play_current_item(first=False)
        else:
            self._end_playlist()

    def _end_playlist(self) -> None:
        self._playlist_active = False
        self._log("プレイリスト再生を終了しました。")
        self._refresh_playlist_listbox()
        self._notify_mini()

    def _goto_relative(self, delta: int) -> None:
        """再生中/停止中を問わず、前後の曲へ移動して再生する。"""
        if not self.playlist.items:
            return
        target = self.playlist.index + delta
        if target < 0:
            target = len(self.playlist.items) - 1 if self._loop_var.get() else 0
        elif target >= len(self.playlist.items):
            target = 0 if self._loop_var.get() else len(self.playlist.items) - 1
        self.player.stop()
        self.player.wait(0.7)
        self.audio.stop()
        self.playlist.set_index(target)
        self._playlist_active = True
        self._play_current_item(first=False)

    def _open_miniplayer(self) -> None:
        if self._miniplayer is not None and self._miniplayer.winfo_exists():
            self._miniplayer.lift()
            return
        self._miniplayer = MiniPlayerWindow(
            self.root,
            on_prev=lambda: self._goto_relative(-1),
            on_next=lambda: self._goto_relative(1),
            on_toggle=self._mini_toggle,
            on_stop=self._on_stop,
            loop_var=self._loop_var,
        )
        self._notify_mini()

    def _mini_toggle(self) -> None:
        if self.player.is_playing:
            self._on_stop()
        elif self.playlist.items:
            self._pl_play_selected()
        else:
            self._on_start()

    def _notify_mini(self) -> None:
        if self._miniplayer is None or not self._miniplayer.winfo_exists():
            return
        item = self.playlist.current()
        name = item.name if item else "(なし)"
        pos = f"{self.playlist.index + 1}/{len(self.playlist.items)}" if self.playlist.items else "-"
        self._miniplayer.update_state(name, pos, self.player.is_playing, self._status_var.get())

    def _persist_playlist(self) -> None:
        self.config.playlist = [it.to_dict() for it in self.playlist.items]
        self.config.loop = self._loop_var.get()
        try:
            self.config.save()
        except Exception:
            pass

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

    def _open_practice(self) -> None:
        score = self._build_score()
        if score is None:
            return
        if not score.events:
            messagebox.showwarning("空の楽譜", "練習できる音がありません。")
            return
        PracticeWindow(self.root, score, self._current_mapping(), audio=self.audio)

    def _open_export(self) -> None:
        score = self._build_score()
        if score is None:
            return
        if not score.events:
            messagebox.showwarning("空の楽譜", "変換できる音がありません。")
            return
        ExportDialog(self.root, score, self._current_mapping(), on_reflect=self._reflect_export)

    def _reflect_export(self, content: str, mode: str) -> None:
        self._source.set(mode)
        self._update_source()
        self._notation.delete("1.0", "end")
        self._notation.insert("1.0", content)
        self._log(f"変換結果を{'数字譜' if mode == 'number' else 'テキスト'}欄に読み込みました。")

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

    # --- 画像からの数字譜取り込み ----------------------------------------------
    def _ocr_from_file(self) -> None:
        if not self._ocr_ready():
            return
        path = filedialog.askopenfilename(
            title="数字譜の画像を開く",
            filetypes=[("画像", "*.png *.jpg *.jpeg *.bmp *.gif"), ("すべて", "*.*")],
        )
        if not path:
            return

        def work() -> None:
            try:
                raw = ocr.ocr_image(path)
            except ocr.OcrError as exc:
                self._ocr_failed_threadsafe(str(exc))
                return
            self.root.after(0, lambda: self._ocr_done(path, raw))

        self._ocr_begin(work)

    def _ocr_from_clipboard(self) -> None:
        if not self._ocr_ready():
            return
        dest = os.path.join(tempfile.gettempdir(), "autoplaynotes_clipboard.png")

        def work() -> None:
            try:
                if not ocr.grab_clipboard_image(dest):
                    self._ocr_failed_threadsafe(
                        "クリップボードに画像がありません。\n"
                        "Win+Shift+S などで数字譜部分をコピーしてから実行してください。"
                    )
                    return
                raw = ocr.ocr_image(dest)
            except ocr.OcrError as exc:
                self._ocr_failed_threadsafe(str(exc))
                return
            self.root.after(0, lambda: self._ocr_done(dest, raw))

        self._ocr_begin(work)

    def _ocr_ready(self) -> bool:
        if ocr.is_available():
            return True
        messagebox.showinfo(
            "利用できません",
            "画像からの取り込みは Windows (PowerShell 内蔵環境) でのみ利用できます。",
        )
        return False

    def _ocr_begin(self, work) -> None:
        self._ocr_btn.configure(state="disabled")
        self._set_status("画像を認識中...")
        threading.Thread(target=work, daemon=True).start()

    def _ocr_failed_threadsafe(self, message: str) -> None:
        self.root.after(0, lambda: self._ocr_failed(message))

    def _ocr_failed(self, message: str) -> None:
        self._ocr_btn.configure(state="normal")
        self._set_status("待機中")
        messagebox.showerror("画像の認識エラー", message)
        self._log(f"画像の認識エラー: {message.splitlines()[0]}")

    def _ocr_done(self, path: str, raw: str) -> None:
        self._ocr_btn.configure(state="normal")
        if not raw.strip():
            self._set_status("待機中")
            messagebox.showinfo(
                "認識結果なし",
                "画像から文字を認識できませんでした。\n"
                "数字部分を大きめに切り取った、文字のはっきりした画像で試してください。",
            )
            return
        cleaned = ocr.clean_number_text(raw)
        tokens = len(cleaned.split())
        self._set_status(f"認識完了: {tokens} トークン")
        self._log(f"画像から数字譜を認識: {tokens} トークン ({os.path.basename(path)})")
        OcrImportDialog(self.root, path, raw, cleaned, on_apply=self._apply_ocr)

    def _apply_ocr(self, text: str) -> None:
        self._notation.delete("1.0", "end")
        self._notation.insert("1.0", text)
        self._source.set("number")
        self._update_source()
        self._log("認識した数字譜を楽譜欄に反映し、ソースを『数字譜』に切り替えました。")

    # --- 楽譜画像トレース入力 --------------------------------------------------
    def _trace_from_file(self) -> None:
        if not trace.is_available():
            messagebox.showinfo(
                "利用できません",
                "画像トレース入力には画像ライブラリ Pillow が必要です。\n"
                "コマンドプロンプトで\n\n    pip install pillow\n\nを実行してください。",
            )
            return
        path = filedialog.askopenfilename(
            title="なぞる楽譜画像を開く",
            filetypes=[("画像", "*.png *.jpg *.jpeg *.bmp *.gif"), ("すべて", "*.*")],
        )
        if not path:
            return
        try:
            trace.TraceWindow(self.root, path, on_apply=self._apply_trace, audio=self.audio)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("画像を開けません", str(exc))

    def _apply_trace(self, score: Score) -> None:
        from .text_parser import score_to_text

        self._source.set("text")
        self._update_source()
        self._notation.delete("1.0", "end")
        self._notation.insert("1.0", score_to_text(score))
        self._log(
            f"画像トレースから {len(score.events)} 音を取り込み、テキスト記譜に反映しました。"
            "「五線譜で表示/編集」で微調整できます。"
        )

    # --- 五線譜画像の取り込み（OMR） -------------------------------------------
    def _omr_from_file(self) -> None:
        if not omr.is_available():
            messagebox.showinfo(
                "oemer が必要です",
                "五線譜画像の読み取りには外部ツール oemer (MIT License) が必要です。\n"
                "Python 環境で\n\n    pip install oemer\n\n"
                "を実行してください（初回の認識時にモデルを自動取得します）。",
            )
            return
        path = filedialog.askopenfilename(
            title="五線譜の画像を開く",
            filetypes=[("画像", "*.png *.jpg *.jpeg *.bmp"), ("すべて", "*.*")],
        )
        if not path:
            return
        if not messagebox.askokcancel(
            "五線譜の認識",
            "五線譜の認識には数分かかることがあります（その間 CPU 使用率が上がります）。\n"
            "結果は下書き品質です。取り込み後に五線譜エディタで修正してください。\n\n"
            "認識結果の MusicXML は画像と同じフォルダに保存されます。開始しますか？",
        ):
            return

        def work() -> None:
            try:
                xml_path = omr.transcribe(path, on_progress=self._omr_progress_threadsafe)
            except omr.OmrError as exc:
                self._ocr_failed_threadsafe(str(exc))
                return
            self.root.after(0, lambda: self._omr_done(xml_path))

        self._ocr_begin(work)

    def _omr_progress_threadsafe(self, line: str) -> None:
        # oemer のログは非常に高頻度（モデル DL 中は毎行）なので間引く
        now = time.monotonic()
        if now - self._omr_last_progress < 0.2:
            return
        self._omr_last_progress = now
        text = line[-60:]
        self.root.after(0, lambda: self._set_status(f"五線譜を認識中... {text}"))

    def _omr_done(self, xml_path: str) -> None:
        self._ocr_btn.configure(state="normal")
        self._set_status("五線譜の認識が完了しました")
        self._log(f"五線譜画像を MusicXML 化: {os.path.basename(xml_path)}（画像と同じフォルダに保存）")
        self._load_score_file(xml_path)

    def _open_midi(self) -> None:
        path = filedialog.askopenfilename(
            title="MIDI / MusicXML ファイルを開く",
            filetypes=[("MIDI / MusicXML", "*.mid *.midi *.musicxml *.xml *.mxl"),
                       ("MIDI", "*.mid *.midi"),
                       ("MusicXML", "*.musicxml *.xml *.mxl"),
                       ("すべて", "*.*")],
        )
        if not path:
            return
        self._load_score_file(path)

    def _load_score_file(self, path: str) -> None:
        """MIDI / MusicXML ファイルを読み込み、パート選択ダイアログを開く。"""
        if not musicxml_parser.is_musicxml_path(path) and not midi_parser.is_available():
            messagebox.showinfo(
                "mido が必要です",
                "MIDI 読み込みには mido が必要です。\nコマンドプロンプトで\n\n    pip install mido\n\nを実行してください。",
            )
            return
        try:
            info = self._inspect_score_file(path)
        except Exception as exc:
            messagebox.showerror("楽譜ファイルの解析エラー", str(exc))
            return
        self._midi_path.set(path)
        self._midi_info = info
        # 既定選択: ドラム/打楽器以外を全て
        self._midi_selection = {p.key for p in info.parts if not p.is_drum}
        self._midi_mono = False
        self._midi_octave = 0
        self._source.set("midi")
        self._update_source()
        self._log(
            f"楽譜ファイルを選択: {info.title} / パート数 {len(info.parts)} / {info.tempo_bpm:.0f} BPM"
        )
        self._open_midi_tracks()

    @staticmethod
    def _inspect_score_file(path: str):
        if musicxml_parser.is_musicxml_path(path):
            return musicxml_parser.inspect_musicxml(path)
        return midi_parser.inspect_midi(path)

    def _open_midi_tracks(self) -> None:
        if not self._midi_path.get().strip():
            messagebox.showinfo("ファイル未選択", "先に「MIDI/XML を選択...」で読み込んでください。")
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
        self._mapping_menu.configure(values=self.config.mapping_names())

    def _on_mapping_change(self, name: str) -> None:
        self.config.active_mapping = name
        self._log(f"キー割り当てを『{name}』に切り替えました。")

    # --- 状態同期 -------------------------------------------------------------
    def _update_source(self) -> None:
        # テキスト記譜・数字譜はテキスト欄を使う。MIDI のときだけ無効化。
        self._source_seg.set(_SOURCE_LABELS[self._source.get()])
        use_editor = self._source.get() in ("text", "number")
        self._notation.configure(state="normal" if use_editor else "disabled")

    def _read_float(self, entry: ctk.CTkEntry, default: float) -> float:
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
        self.config.loop = self._loop_var.get()
        self.config.playlist = [it.to_dict() for it in self.playlist.items]
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
        self.root.after(0, lambda: self._on_done(stopped))

    def _on_done(self, stopped: bool) -> None:
        # 手動 next/prev で既に次曲が始まっている場合は二重進行させない
        if self.player.is_playing:
            self._notify_mini()
            return
        self._reset_buttons()
        self._notify_mini()
        if stopped:
            self._playlist_active = False
            self._refresh_playlist_listbox()
            return
        if self._playlist_active:
            self._after_song()

    def _progress_threadsafe(self, beat: float, total_beats: float) -> None:
        self.root.after(0, lambda: self._update_cursor(beat))

    def _update_cursor(self, beat: float) -> None:
        if self._staff_window is not None:
            self._staff_window.set_cursor(beat)

    def _set_status(self, message: str) -> None:
        self._status_var.set(message)
        self._log(message)
        self._notify_mini()

    def _log(self, message: str) -> None:
        self._log_text.configure(state="normal")
        self._log_text.insert("end", message + "\n")
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _on_close(self) -> None:
        self._playlist_active = False
        try:
            self.audio.stop()
        except Exception:
            pass
        try:
            self.player.stop()
            self.player.wait(1.0)
        except Exception:
            pass
        if self._miniplayer is not None:
            try:
                self._miniplayer.destroy()
            except Exception:
                pass
        try:
            self.sender.release_all()
        except Exception:
            pass
        self._save_config_from_ui()
        self.hotkeys.stop()
        self.root.destroy()


class MappingEditor(ctk.CTkToplevel):
    """『音名 = キー』のテキストで割り当てを編集するダイアログ。"""

    def __init__(self, parent: tk.Misc, mapping: KeyMapping, on_save) -> None:
        super().__init__(parent)
        self.title("キー割り当ての編集")
        self.geometry("480x560")
        theme.apply_titlebar(self)
        self._on_save = on_save

        ctk.CTkLabel(
            self, text="1 行に 1 つ『音名 = キー』を記入してください（例: C4 = a）。",
            wraplength=440, justify="left",
        ).pack(anchor="w", padx=14, pady=(12, 4))

        name_row = ctk.CTkFrame(self, fg_color="transparent")
        name_row.pack(fill="x", padx=14)
        ctk.CTkLabel(name_row, text="名前:").pack(side="left")
        self._name = ctk.CTkEntry(name_row)
        self._name.insert(0, mapping.name if mapping.name else "カスタム")
        self._name.pack(side="left", fill="x", expand=True, padx=6)

        oor_row = ctk.CTkFrame(self, fg_color="transparent")
        oor_row.pack(fill="x", padx=14, pady=6)
        ctk.CTkLabel(oor_row, text="音域外の扱い:").pack(side="left")
        self._oor = tk.StringVar(value=mapping.out_of_range)
        ctk.CTkOptionMenu(oor_row, variable=self._oor, width=120,
                          values=["transpose", "nearest", "skip"]).pack(side="left", padx=6)
        ctk.CTkLabel(oor_row, text="transpose=移調 / nearest=最寄り音 / skip=無視",
                     text_color=theme.pair("subtle")).pack(side="left")

        self._text = ctk.CTkTextbox(self, font=(theme.FONT_MONO, 13), undo=True)
        self._text.pack(fill="both", expand=True, padx=14, pady=6)
        self._text.insert("1.0", mapping.as_text())

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=14, pady=(4, 14))
        ctk.CTkButton(buttons, text="保存", width=90, command=self._save,
                      **theme.BTN_ACCENT).pack(side="right", padx=(6, 0))
        ctk.CTkButton(buttons, text="キャンセル", width=90,
                      command=self.destroy).pack(side="right")

        self.transient(parent)
        self.after(150, self._safe_grab)

    def _safe_grab(self) -> None:
        try:
            self.grab_set()
        except tk.TclError:
            pass

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


class MidiTrackDialog(ctk.CTkToplevel):
    """MIDI / MusicXML のどのパートを鳴らすか選ぶダイアログ。"""

    def __init__(
        self,
        parent: tk.Misc,
        info,  # midi_parser.MidiInfo | musicxml_parser.XmlInfo
        selected: set | None,
        monophonic: bool,
        octave: int,
        on_ok,
    ) -> None:
        super().__init__(parent)
        self.title("パート選択")
        self.geometry("600x520")
        theme.apply_titlebar(self)
        self._on_ok = on_ok
        self._vars: dict[tuple[int, int], tk.BooleanVar] = {}

        ctk.CTkLabel(
            self, text="演奏するパートを選んでください（ドラムは通常オフ）。",
            wraplength=560, justify="left",
        ).pack(anchor="w", padx=14, pady=(12, 4))

        # スクロール可能なパート一覧
        inner = ctk.CTkScrollableFrame(self)
        inner.pack(fill="both", expand=True, padx=14)

        if not info.parts:
            ctk.CTkLabel(inner, text="演奏可能なパートがありません。").pack(anchor="w")
        for part in info.parts:
            default = (part.key in selected) if selected is not None else (not part.is_drum)
            var = tk.BooleanVar(value=default)
            self._vars[part.key] = var
            ctk.CTkCheckBox(inner, text=part.label(), variable=var,
                            onvalue=True, offvalue=False).pack(anchor="w", pady=3, padx=4)

        options = ctk.CTkFrame(self, fg_color="transparent")
        options.pack(fill="x", padx=14, pady=6)
        self._mono = tk.BooleanVar(value=monophonic)
        ctk.CTkCheckBox(
            options, text="単音化（各時点で最高音だけ＝メロディ抽出）", variable=self._mono,
            onvalue=True, offvalue=False,
        ).pack(anchor="w")
        oct_row = ctk.CTkFrame(options, fg_color="transparent")
        oct_row.pack(anchor="w", pady=(8, 0))
        ctk.CTkLabel(oct_row, text="オクターブ移調:").pack(side="left")
        self._octave = ctk.CTkOptionMenu(
            oct_row, width=80, values=["+3", "+2", "+1", "0", "-1", "-2", "-3"])
        self._octave.set(f"{octave:+d}" if octave else "0")
        self._octave.pack(side="left", padx=6)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=14, pady=(6, 14))
        ctk.CTkButton(buttons, text="全選択", width=80,
                      command=lambda: self._set_all(True)).pack(side="left")
        ctk.CTkButton(buttons, text="全解除", width=80,
                      command=lambda: self._set_all(False)).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="OK", width=90, command=self._ok,
                      **theme.BTN_ACCENT).pack(side="right", padx=(6, 0))
        ctk.CTkButton(buttons, text="キャンセル", width=90,
                      command=self.destroy).pack(side="right")

        self.transient(parent)
        self.after(150, self._safe_grab)

    def _safe_grab(self) -> None:
        try:
            self.grab_set()
        except tk.TclError:
            pass

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


class MiniPlayerWindow(ctk.CTkToplevel):
    """常に手前に表示される小さな操作パネル（プレイリスト操作用）。"""

    def __init__(self, parent: tk.Misc, on_prev, on_next, on_toggle, on_stop, loop_var: tk.BooleanVar) -> None:
        super().__init__(parent)
        self.title("ミニプレイヤー")
        self.geometry("380x160")
        self.resizable(False, False)
        theme.apply_titlebar(self)
        self._on_toggle = on_toggle

        self._topmost = tk.BooleanVar(value=True)
        self.attributes("-topmost", True)

        self._name_var = tk.StringVar(value="(なし)")
        self._pos_var = tk.StringVar(value="-")
        self._status_var = tk.StringVar(value="待機中")

        ctk.CTkLabel(self, textvariable=self._name_var, anchor="w",
                     font=ctk.CTkFont(size=14, weight="bold")).pack(
            fill="x", padx=14, pady=(10, 0)
        )
        info = ctk.CTkFrame(self, fg_color="transparent")
        info.pack(fill="x", padx=14)
        ctk.CTkLabel(info, textvariable=self._pos_var,
                     text_color=theme.pair("subtle")).pack(side="left")
        ctk.CTkLabel(info, textvariable=self._status_var,
                     text_color=theme.pair("accent")).pack(side="right")

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(pady=8)
        ctk.CTkButton(controls, text="⏮", width=44, command=on_prev).pack(side="left", padx=3)
        self._toggle_btn = ctk.CTkButton(controls, text="▶ 再生", width=90,
                                         command=on_toggle, **theme.BTN_ACCENT)
        self._toggle_btn.pack(side="left", padx=3)
        ctk.CTkButton(controls, text="■", width=44, command=on_stop).pack(side="left", padx=3)
        ctk.CTkButton(controls, text="⏭", width=44, command=on_next).pack(side="left", padx=3)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.pack(fill="x", padx=14, pady=(0, 8))
        ctk.CTkSwitch(bottom, text="ループ", variable=loop_var,
                      onvalue=True, offvalue=False, width=80).pack(side="left")
        ctk.CTkSwitch(
            bottom, text="常に手前", variable=self._topmost,
            onvalue=True, offvalue=False, command=self._toggle_topmost,
        ).pack(side="right")

    def _toggle_topmost(self) -> None:
        self.attributes("-topmost", self._topmost.get())

    def update_state(self, name: str, pos: str, playing: bool, status: str) -> None:
        self._name_var.set(name)
        self._pos_var.set(pos)
        self._status_var.set(status)
        self._toggle_btn.configure(text="■ 停止" if playing else "▶ 再生")


class OcrImportDialog(ctk.CTkToplevel):
    """画像から認識した数字譜を確認・修正して楽譜欄へ反映するダイアログ。"""

    def __init__(self, parent: tk.Misc, image_path: str, raw_text: str,
                 cleaned_text: str, on_apply) -> None:
        super().__init__(parent)
        self.title("画像から数字譜を取り込み")
        self.geometry("680x720")
        theme.apply_titlebar(self)
        self._on_apply = on_apply
        self._photo: tk.PhotoImage | None = self._load_preview(image_path)
        if self._photo is not None:
            tk.Label(self, image=self._photo, bd=0,
                     bg=theme.palette()["bg"]).pack(padx=14, pady=(12, 2))

        ctk.CTkLabel(self, text="認識した数字譜（ここで修正できます）:").pack(
            anchor="w", padx=14, pady=(8, 0))
        self._text = ctk.CTkTextbox(self, wrap="word", font=(theme.FONT_MONO, 13),
                                    height=200, undo=True)
        self._text.pack(fill="both", expand=True, padx=14, pady=6)
        self._text.insert("1.0", cleaned_text)

        ctk.CTkLabel(self, text="生の認識結果（参考）:",
                     text_color=theme.pair("subtle")).pack(anchor="w", padx=14)
        raw_widget = ctk.CTkTextbox(self, wrap="word", font=(theme.FONT_MONO, 12),
                                    height=80, fg_color=theme.pair("log_bg"))
        raw_widget.pack(fill="x", padx=14, pady=4)
        raw_widget.insert("1.0", raw_text)
        raw_widget.configure(state="disabled")

        self._status = tk.StringVar(
            value=f"{len(cleaned_text.split())} トークンを認識。『解析チェック』で確認できます。")
        ctk.CTkLabel(self, textvariable=self._status,
                     text_color=theme.pair("subtle")).pack(anchor="w", padx=14)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=14, pady=(6, 14))
        ctk.CTkButton(buttons, text="解析チェック", width=110,
                      command=self._check).pack(side="left")
        ctk.CTkButton(buttons, text="楽譜欄へ反映", width=120, command=self._apply,
                      **theme.BTN_ACCENT).pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="閉じる", width=80,
                      command=self.destroy).pack(side="right")

        self.transient(parent)

    def _load_preview(self, path: str) -> tk.PhotoImage | None:
        # tk.PhotoImage が対応する形式のみ（クリップボード経由は常に PNG）
        if os.path.splitext(path)[1].lower() not in (".png", ".gif"):
            return None
        try:
            photo = tk.PhotoImage(file=path)
        except tk.TclError:
            return None
        factor = max(1, -(-photo.width() // 600), -(-photo.height() // 220))
        return photo.subsample(factor, factor) if factor > 1 else photo

    def _check(self) -> None:
        try:
            score = parse_numbers(self._text.get("1.0", "end"))
        except Exception as exc:
            self._status.set(f"解析エラー: {exc}")
            return
        beats = max((e.start_beat + e.duration_beat for e in score.events), default=0.0)
        self._status.set(f"解析 OK: {len(score.events)} 音 / 約 {beats:.0f} 拍")

    def _apply(self) -> None:
        self._on_apply(self._text.get("1.0", "end").rstrip("\n") + "\n")
        self.destroy()


_EXPORT_LABELS = {"text": "テキスト(CDE)", "number": "数字譜(1-7)", "keys": "キー文字譜(共有用)"}
_LABEL_EXPORTS = {v: k for k, v in _EXPORT_LABELS.items()}


class ExportDialog(ctk.CTkToplevel):
    """楽譜を別形式へ変換 / 共有用にエクスポートするダイアログ。"""

    def __init__(self, parent: tk.Misc, score: Score, mapping: KeyMapping, on_reflect) -> None:
        super().__init__(parent)
        self.title("エクスポート / 変換")
        self.geometry("620x560")
        theme.apply_titlebar(self)
        self._score = score
        self._mapping = mapping
        self._on_reflect = on_reflect

        self._format = tk.StringVar(value="text")
        self._tonic = tk.StringVar(value="C")
        self._keys_rhythm = tk.BooleanVar(value=True)

        opt = ctk.CTkFrame(self, fg_color="transparent")
        opt.pack(fill="x", padx=14, pady=(12, 4))
        ctk.CTkLabel(opt, text="出力形式:").pack(side="left", padx=(0, 8))
        seg = ctk.CTkSegmentedButton(opt, values=list(_EXPORT_LABELS.values()),
                                     command=self._on_format_select)
        seg.set(_EXPORT_LABELS["text"])
        seg.pack(side="left")

        key_row = ctk.CTkFrame(self, fg_color="transparent")
        key_row.pack(fill="x", padx=14, pady=4)
        ctk.CTkLabel(key_row, text="数字譜の主音:").pack(side="left")
        ctk.CTkOptionMenu(key_row, variable=self._tonic, width=70,
                          values=["C", "G", "D", "A", "E", "F", "Bb", "Eb"],
                          command=lambda _v: self._regen()).pack(side="left", padx=6)
        ctk.CTkCheckBox(key_row, text="休符・拍を含める（キー譜の再現用）",
                        variable=self._keys_rhythm, onvalue=True, offvalue=False,
                        command=self._regen).pack(side="left", padx=12)

        self._text = ctk.CTkTextbox(self, wrap="word", font=(theme.FONT_MONO, 13))
        self._text.pack(fill="both", expand=True, padx=14, pady=6)

        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkButton(buttons, text="コピー", width=80, command=self._copy).pack(side="left")
        ctk.CTkButton(buttons, text="保存...", width=80,
                      command=self._save).pack(side="left", padx=6)
        self._reflect_btn = ctk.CTkButton(buttons, text="この形式で楽譜欄に反映", width=170,
                                          command=self._reflect, **theme.BTN_ACCENT)
        self._reflect_btn.pack(side="left", padx=6)
        ctk.CTkButton(buttons, text="閉じる", width=80,
                      command=self.destroy).pack(side="right")

        self.transient(parent)
        self._regen()

    def _on_format_select(self, label: str) -> None:
        self._format.set(_LABEL_EXPORTS.get(label, "text"))
        self._regen()

    def _current_text(self) -> str:
        fmt = self._format.get()
        if fmt == "number":
            return score_to_numbers(self._score, tonic=self._tonic.get())
        if fmt == "keys":
            return score_to_keys(self._score, self._mapping, include_rhythm=self._keys_rhythm.get())
        return score_to_text(self._score)

    def _regen(self) -> None:
        content = self._current_text()
        self._text.delete("1.0", "end")
        self._text.insert("1.0", content)
        # キー文字譜は本アプリの入力形式ではないので反映不可
        self._reflect_btn.configure(state=("disabled" if self._format.get() == "keys" else "normal"))

    def _copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._text.get("1.0", "end").rstrip("\n"))

    def _save(self) -> None:
        path = filedialog.asksaveasfilename(
            title="保存", defaultextension=".txt", filetypes=[("テキスト", "*.txt"), ("すべて", "*.*")]
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._text.get("1.0", "end"))
        except Exception as exc:
            messagebox.showerror("保存エラー", str(exc), parent=self)
            return
        messagebox.showinfo("保存", f"保存しました: {os.path.basename(path)}", parent=self)

    def _reflect(self) -> None:
        fmt = self._format.get()
        if fmt == "keys":
            return
        self._on_reflect(self._text.get("1.0", "end"), "number" if fmt == "number" else "text")
        self.destroy()


class WelcomeDialog(ctk.CTkToplevel):
    """初回起動時のみ表示するクイックスタート案内。"""

    _STEPS = (
        ("1", "楽譜を用意する",
         "テキスト/数字譜を入力するか、MIDI・MusicXML・楽譜画像（OCR/OMR）を"
         "読み込みます。まずは読み込み済みのサンプル曲のままでOK。"),
        ("2", "キー割り当てを合わせる",
         "『⚙ 設定』タブで、演奏先アプリのキー配置に合ったプリセットを選びます。"),
        ("3", "演奏する",
         "演奏先アプリを前面にして F9（またはこの画面の『▶ 演奏開始』）。"
         "音は鳴らさず、キー入力だけを送出します。"),
    )

    def __init__(self, parent: tk.Misc) -> None:
        super().__init__(parent)
        self.title("ようこそ")
        self.geometry("560x520")
        self.resizable(False, False)
        theme.apply_titlebar(self)

        ctk.CTkLabel(self, text="🎹 AutoPlayNotes へようこそ",
                     font=ctk.CTkFont(size=20, weight="bold")).pack(
            anchor="w", padx=24, pady=(20, 2))
        ctk.CTkLabel(self, text="楽譜どおりにキー入力を自動送出する演奏支援ツールです。3 ステップで始められます。",
                     wraplength=500, justify="left",
                     text_color=theme.pair("subtle")).pack(anchor="w", padx=24)

        for num, title, desc in self._STEPS:
            row = ctk.CTkFrame(self)
            row.pack(fill="x", padx=24, pady=6)
            ctk.CTkLabel(row, text=num, width=36, height=36, corner_radius=18,
                         fg_color=theme.pair("accent"),
                         text_color=theme.pair("accent_fg"),
                         font=ctk.CTkFont(size=16, weight="bold")).pack(
                side="left", padx=(12, 12), pady=12)
            body = ctk.CTkFrame(row, fg_color="transparent")
            body.pack(side="left", fill="x", expand=True, pady=10, padx=(0, 12))
            ctk.CTkLabel(body, text=title, anchor="w",
                         font=ctk.CTkFont(size=14, weight="bold")).pack(fill="x")
            ctk.CTkLabel(body, text=desc, wraplength=420, justify="left", anchor="w",
                         text_color=theme.pair("subtle")).pack(fill="x")

        ctk.CTkLabel(self, text="💡『🔊 音で試聴』なら、キー送出せずにスピーカーで曲を確認できます。",
                     wraplength=500, justify="left",
                     text_color=theme.pair("subtle")).pack(anchor="w", padx=24, pady=(6, 0))
        ctk.CTkButton(self, text="はじめる", height=40,
                      font=ctk.CTkFont(size=14, weight="bold"),
                      command=self.destroy, **theme.BTN_ACCENT).pack(
            fill="x", padx=24, pady=(14, 20))

        self.transient(parent)
        self.after(150, self._safe_grab)

    def _safe_grab(self) -> None:
        try:
            self.grab_set()
        except tk.TclError:
            pass


def run() -> None:
    config = AppConfig.load()
    theme.setup(config.dark)
    root = ctk.CTk()
    App(root, config)
    root.mainloop()
