---
aim: 弾きたい曲の素材を問わず（テキスト・数字譜・MIDI・MusicXML・スクショ・PDF・楽譜画像・音源・映像など）、練習できる譜面データに変換できる
parent: autoplaynotes
state: open
---

# IS
入口をすべて共通データモデル（`model.py` の `Score` / `NoteEvent`）へ集約する、という読み。独自性は「最高の変換器」を作ることではなく、**入口の広さ**そのものに置く。依存の軽い手動系は本体に同梱し、数百 MB のモデルを要する自動系は子 aim `transcribe-addon` へ隔離する。

- **本体（依存が軽い）**: 数字譜（`number_parser`）／ テキスト CDE（`text_parser`）／ MIDI（`midi_parser`, 任意依存 mido）／ MusicXML・MXL（`musicxml_parser`, 依存ゼロ）／ 数字譜スクショ OCR（`ocr`, Windows 内蔵 OCR を PowerShell 経由で呼ぶので pip 依存ゼロ）／ PDF 各ページ画像化（`pdf`, 任意依存 pypdfium2）／ 楽譜画像を下敷きになぞるトレース入力（`trace`, 2 点キャリブ）。
- **アドオン（依存が重い）**: 五線譜画像 OMR ／ 音源→MIDI ／ 映像→譜面 → 子 aim `transcribe-addon`。
- **変換 / 共有**: `convert.py` が数字譜・キー文字譜・テキストへ相互変換（休符・拍・タイを保持し往復無損失）。`score_export.py` が MIDI / MusicXML を書き出す。

**トレースがテールの主戦力**。ロングテールの素材は汚い（配信のスクショ・手書き・低画質）ため、OMR は綺麗な画像の時短にすぎない。楽譜を読めなくても、画像を下敷きに音符の位置をクリックすれば譜面になる。

**相互運用が堀**。専業の楽譜スキャナー（PlayScore / ScanScore / MuseScore など）は「人が読む・印刷する楽譜」が出口で、こちらと重なるのは入口だけ。だから OMR の精度は追わず、**彼らの MusicXML / MIDI を取り込む側**に回る。

# PROCESS
- [done] 共通データモデル（`Score` / `NoteEvent`・音ごとの音長）
- [done] 本体の入口網（数字譜 / テキスト CDE / MIDI / MusicXML / 数字譜 OCR / PDF / 画像トレース）
- [done] フォーマット変換・共有エクスポート（往復無損失 / MIDI・MusicXML 書き出し）
- [done] 複声部由来の重なる譜面で変換がずれる欠陥の修正（`model.sequential_durations()`）
- [子] 譜面が無い素材（画像 / 音源 / 映像）からの採譜 → [[transcribe-addon]]

# DAG
関連: [[ear-verification]] — 入口を広げるほど、採譜の誤りを検証できないユーザーが増える
