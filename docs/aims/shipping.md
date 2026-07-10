---
aim: ソースは公開されたままであり自分でビルドできる人には無償提供され、バイナリの配布は有償にてユーザは完成した実行ファイルと採譜アドオンを入手して使える
parent: autoplaynotes
state: open
---

# IS
ソースは MIT で公開したまま、**バイナリの公式配布だけを有償にする**（Aseprite 方式）、という読み。自分でビルドできる人は無償で使え、ビルド環境を持たない人は完成品を買う。**DRM はかけない** — 上位の競合ですら割られており、割に合わない。

- **本体**: `build.py`（PyInstaller `--onefile --windowed`・アイコンとアセット同梱・customtkinter と pypdfium2 のネイティブ依存を収集）。
- **採譜アドオン**: 本体は凍結 exe なので pip も site-packages も無く、買った人が `pip install` はできない。したがってアドオンは**自前ランタイムごと持ち込む別プロセス**にするしかない。採る形は**隣接 dir ドロップイン** — exe と同じ場所のフォルダに解凍するだけで動き、本体は `manifest.json` の `command` 契約越しに subprocess 起動する。中身（凍結 exe / 埋め込み Python / 別エンジン）を差し替えても本体は不変。埋め込み CPython には python-build-standalone を使う（venv は絶対パスを埋め込むので再配置できない）。
- `bundle_transcribe_addon.py` が OMR と音源採譜を 1 つの zip に束ねる。将来の映像エンジンも同じ zip に足すだけ。
- **容量は弱点ではなく付加価値**として提示する。DL 468MB / 展開 1.26GB は「深層学習モデルを丸ごとローカルに同梱している」ということ、すなわち**クラウド送信なし・サブスクなし・オフライン動作・曲数無制限**である。
- ライセンス表示は `tools/gen_third_party_notices.py` が `THIRD-PARTY-NOTICES.md` と `licenses/` を生成し、配布 zip にも同梱する（oemer は MIT、basic-pitch は Apache-2.0）。

**価格・販売チャネル・競合の分析は非公開ドキュメントの管轄であり、ここには書かない。**

# PROCESS
- [done] 単一 exe のビルド（`build.py`）
- [done] v0.1.0 リリース
- [done] アドオンのドロップイン契約と同梱ビルドのハーネス（埋め込み Python・`--no-deps` lock）
- [done] 採譜アドオンの実成果物ビルドと統合 zip（OMR ＋ 音源採譜・E2E 検証済み）
- [done] `THIRD-PARTY-NOTICES.md` と `licenses/` の生成
- [todo] 名前の決定
- [todo] バイナリの実配布

# ESCALATION
- **名前の決定は operator の act。** 改名するならサムネ・GitHub・exe の全てに波及するので、**配布を始める前が最も安い**。
- **実配布はアカウント操作を伴う**ため operator の act。
