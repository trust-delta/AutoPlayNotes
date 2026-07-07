---
aim: キーボード演奏系アプリのユーザーが、手持ちの楽譜から「自動で弾かせる」と「自分で弾けるようになる」の両方を、1 つの Windows ツールで達成できる
parent:
state: open
---

# IS
楽譜を共通データモデル（`model.py` の `Score` / `NoteEvent`）へ集約し、そこを軸に「多様な入力 → 変換 → 2 系統の出力」を組む、という読み。

- 入力: 数字譜（`number_parser`）／ 自作テキスト CDE（`text_parser`）／ MIDI（`midi_parser`, 任意依存 mido）に加え、画像 OCR で数字譜化（`ocr`）／ MusicXML・MXL（`musicxml_parser`）／ 五線譜画像 OMR（`omr`, 重い任意依存 oemer）／ PDF を各ページ画像化して取込（`pdf`, 任意依存 pypdfium2）／ 楽譜画像を下敷きになぞるトレース入力（`trace`）を Score へ。
- 変換 / 共有: `convert.py` で数字譜・キー文字譜・テキストへ相互変換（休符・拍・タイを保持し往復無損失）。`score_export.py` で MIDI / MusicXML 書き出し（追加依存なし）。
- 出力① 自動演奏: `keymap` の音階→キー割当を通し、`win_input`（スキャンコード SendInput）＋ `player`（別スレッド・停止可・ヒューマナイズ）でフォーカス窓へキー送出。
- 出力② 練習: `practice.py` の音ゲー型（判定・スコア）／ ステップ型（運指）に A-B ループ・メトロノーム（`audio`）を備え、ゲームに触れず自己完結トレーニング。
- 周辺: `staff`（五線譜プレビュー / 簡易エディタ）、`audio`（winsound サイン波の確認用試聴・メトロノーム）、`playlist`（連続再生 / ミニプレイヤー）、`theme` / `config`（ライト・ダーク / 設定保存）、`gui`（customtkinter タブ UI・アイコン・初回起動体験）。
- 配布: `build.py`（PyInstaller で単一 exe、mido 同梱）。v0.1.0 リリース済み（exe の GitHub 配布は停止し、README はビルド案内へ）。

# PROCESS
- [done] 共通データモデル（Score / NoteEvent）
- [done] 入力 3 系統（数字譜 / テキスト CDE / MIDI トラック選択・単音化・移調）
- [done] 画像・文書からの取り込み（数字譜 OCR / MusicXML・MXL / 五線譜 OMR / PDF / 画像トレース）
- [done] フォーマット変換・共有エクスポート（テキスト ⇄ 数字譜・キー文字譜の往復無損失 / MIDI・MusicXML 書き出し）
- [done] 自動演奏エンジン（SendInput・停止可・和音・ヒューマナイズ）
- [done] 練習モード（リズム / ステップ・シーク・参照五線譜・A-B ループ・メトロノーム）
- [done] 五線譜プレビュー / 簡易エディタ・音声プレビュー
- [done] プレイリスト / ミニプレイヤー・ライト/ダークテーマ・設定保存
- [done] UI を customtkinter へ刷新（アイコン・初回起動体験）
- [done] 単一 exe 配布（PyInstaller）・v0.1.0 リリース
- [done] 自動テスト基盤の第一層（parser / convert / export / OCR / MusicXML の unittest 34 件・緑）
- [todo] 回帰網の残余カバレッジ（GUI / `player` / `win_input` など未カバー層）— 子 aim 化の候補
