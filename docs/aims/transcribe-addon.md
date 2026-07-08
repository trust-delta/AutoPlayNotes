---
aim: ユーザーが、譜面が無い素材（綺麗な五線譜画像・音源のみの「弾いてみた」・落ちノーツ映像）からでも、重い変換依存を本体に持ち込まずに「弾ける・練習できる」譜面データを得られる
parent: autoplaynotes
state: open
---

# IS
重い機械学習依存（oemer / basic-pitch / 将来 opencv）を本体に同梱せず、隣接 dir の自己完結アドオンへ隔離する、という読み。契約は一貫して「アドオンが MIDI を吐き、本体が既存の `_load_score_file(midi)` で取り込む」＝本体側の配線を再利用し、エンジンを差し替え可能にする。同梱ビルドは `tools/build_*_addon.py`／`bundle_transcribe_addon.py` で 1 つの採譜アドオンへ束ねる（容量はローカル AI＝オフライン・無制限の付加価値として reframe）。

- OMR（`omr` ＋ oemer アドオン）: 綺麗な五線譜画像 → 譜面。実ビルド・E2E 済み。
- Phase 3a 音源→MIDI（`pitch` ＋ basic-pitch アドオン）: 音源のみの「弾いてみた」→ MIDI。下書き品質→本体エディタ/トレースで編集する前提。実アドオン E2E 済み（合成音源は Score へ完全一致）。
- Phase 3b 映像→譜面（設計のみ）: Synthesia 系の落ちノーツ映像を semi-auto（本体トレースの 2 点キャリブ UX を流用）で譜面化。動画デコード（opencv）はアドオン側、キャリブは本体側という 2 フェーズ契約で、上記と同じ「アドオンが MIDI を吐く」形に帰着させる。

# PROCESS
- [done] ドロップイン型アドオンの契約・同梱ビルドハーネス（隣接 dir・埋め込み Python・`--no-deps` lock 導入）
- [done] OMR アドオン（oemer・実ビルド E2E）
- [done] Phase 3a 音源→MIDI アドオン（basic-pitch・本体 `pitch.py` ＋実アドオン E2E）
- [done] 採譜アドオンの統合束ね（OMR＋音源を 1 zip・`bundle_transcribe_addon.py`）
- [todo] Phase 3a precision 検証（実「弾いてみた」ソロピアノ音源での実測・下書き品質確認）
- [todo] Phase 3b 映像→譜面（v1: ヒット線スキャン CV）— 設計済み・実クリップ 1 本が着手条件
