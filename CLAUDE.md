# AutoPlayNotes — この repo での作法

## aim（purpose=means 木）で進める

`docs/aims/<slug>.md` が目的と手段の木。**規律の正本は `docs/aims/_guide/` の 2 枚**で、
`frame.md`（役割分担と escalation の規律）と `producer-guide.md`（slug・section・木の保守・drift）に分かれる。
役割分担（`aim:` / `parent:` / `state:` は operator、body は producer）はそちらに従う。

@docs/aims/_guide/frame.md
@docs/aims/_guide/producer-guide.md

⚠ **この import は 2026-08-04 に `CLAUDE.local.md` から repo 側へ移した**（同時に `.gitignore` から
`CLAUDE.md` を外した）。それまで配線は untracked の 1 行ファイルにしか無く、**git に載らないので、
欠けていても repo 側からは見えない**状態だった。⚠ **`@path` の import が解決できなくても
Claude Code は何も言わない**ので、配線を local に置くと静かに割れる。
**複数のマシン・複数の担い手で真であるものを `*.local.md` に置かない。**

⚠ **この 2 枚は正本ではなく手コピー**（正本は tmai-core の `docs/aims/_guide/`）。**同期を検出する機構は無い**
—— 実際 `producer-guide.md` は 2026-07-10 の配布（`6145ca6`）から 08-04 まで古い版のまま止まっていた。
