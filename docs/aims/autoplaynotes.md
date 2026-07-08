---
aim: キーボード演奏系アプリのユーザーが、手持ちの楽譜から「自動で弾かせる」と「自分で弾けるようになる」の両方を、1 つの Windows ツールで達成できる
parent:
state: open
---

# IS
楽譜を共通データモデル（`model.py` の `Score` / `NoteEvent`）へ集約し、そこを軸に「最も広い入力 → 変換 → 2 系統の出力」を組む、という読み。独自性は「最高の変換器」ではなく「どんな素材でも playable にする入口の広さ」に置く。

- 入力（本体・依存軽）: 数字譜（`number_parser`）／ テキスト CDE（`text_parser`）／ MIDI（`midi_parser`, 任意依存 mido）／ MusicXML・MXL（`musicxml_parser`）／ 数字譜スクショ OCR（`ocr`, Windows 内蔵 OCR・依存ゼロ）／ PDF 各ページ画像化（`pdf`, 任意依存 pypdfium2）／ 楽譜画像を下敷きになぞるトレース入力（`trace`, 2 点キャリブ）。
- 入力（採譜アドオン・重依存を隣接 dir へ分離）: 綺麗な五線譜画像 OMR（`omr` ＋ oemer アドオン）／ 音源のみの「弾いてみた」→ MIDI（`pitch` ＋ basic-pitch アドオン, Phase 3a）。いずれも「アドオンが MIDI を吐き本体が取り込む」契約で本体から分離し、`tools/build_*_addon.py`・`bundle_transcribe_addon.py` で同梱ビルド。
- 変換 / 共有: `convert.py` で数字譜・キー文字譜・テキストへ相互変換（休符・拍・タイ保持・往復無損失）。`score_export.py` で MIDI / MusicXML 書き出し。
- 出力① 自動演奏: `keymap` の音階→キー割当を通し、`win_input`（スキャンコード SendInput）＋ `player`（別スレッド・停止可・ヒューマナイズ）でフォーカス窓へキー送出。
- 出力② 練習: `practice.py` の音ゲー型（判定・スコア）／ ステップ型（運指）・A-B ループ・メトロノーム（`audio`）・練習メモ（`practice_notes`）で、ゲームに触れず自己完結トレーニング。
- 周辺 / 配布: `staff`（五線譜プレビュー / 簡易エディタ）・`playlist`（連続再生 / ミニプレイヤー）・`theme`/`config`（ライト・ダーク / 設定保存）・`gui`（customtkinter タブ UI）。`build.py`（PyInstaller で単一 exe、mido 同梱）。v0.1.0 リリース済み。

# PROCESS
- [done] 共通データモデル（Score / NoteEvent）
- [done] 本体の入力網（数字譜 / テキスト CDE / MIDI / MusicXML / 数字譜 OCR / PDF / 画像トレース）
- [done] フォーマット変換・共有エクスポート（テキスト⇄数字譜・キー文字譜の往復無損失 / MIDI・MusicXML 書き出し）
- [done] 自動演奏エンジン（SendInput・停止可・和音・ヒューマナイズ）
- [done] 練習モード（リズム / ステップ・シーク・参照五線譜・A-B ループ・メトロノーム・練習メモ）
- [done] 採譜機能のドロップイン型アドオン化（隣接 dir 契約・同梱ビルドハーネス）
- [done] 五線譜画像 OMR アドオン（oemer・実ビルド E2E）
- [done] 音源→MIDI 自動採譜アドオン（Phase 3a・basic-pitch・実アドオン E2E）
- [done] 五線譜プレビュー / 簡易エディタ・音声プレビュー・プレイリスト・テーマ・設定保存
- [done] UI を customtkinter へ刷新・単一 exe 配布・v0.1.0 リリース
- [done] 自動テスト基盤の第一層（parser / convert / export / OCR / MusicXML / 採譜 / 練習メモ の unittest 71 件・緑）
- [todo] Phase 3b: 落ちノーツ映像 → 譜面（semi-auto・トレースの動画版）— 設計済み・実クリップ 1 本が着手条件
- [todo] Phase 3a precision 検証（実「弾いてみた」音源での実測）
- [todo] 回帰網の残余カバレッジ（GUI / `player` / `win_input` など未カバー層）
