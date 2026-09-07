# AutoPlayNotes — この repo での作法

## aim（purpose=means 木）で進める

`docs/aims/<slug>.md` が目的と手段の木。**規律の正本は `.claude/skills/aim/`**（`/bearing:setup-aim` が置く 3 枚）で、
`SKILL.md`（入口）・`aim-authoring.md`（slug・section・木の保守・drift）・`aim-facts.md`（注入される事実の読み方）に分かれる。
役割分担（`aim:` / `parent:` / `state:` は operator、body は producer）は、この file の下部に在る `bearing:aim` の block が述べる。

⚠ **2026-09-05、正本を `docs/aims/_guide/` から bearing の機構へ移した**（operator の決定）。旧い形は
`frame.md` と `producer-guide.md` の 2 枚を `@import` で読ませていたが、⚠ **あの 2 枚は正本ではなく
tmai-core からの手コピーで、同期を検出する機構は無かった** —— 実際 `producer-guide.md` は 2026-07-10 の
配布（`6145ca6`）から 08-04 まで古い版のまま止まっていた。∴ **追随しない複製を 1 つ減らした。**

⚠ **旧い形が残した教訓は 2 つとも生きている**（2026-08-04 に踏んだ）: ⑴ **`@path` の import が解決できなくても
Claude Code は何も言わない** ∴ 配線を local に置くと静かに割れる。⑵ **複数のマシン・複数の担い手で真である
ものを `*.local.md` に置かない** —— git に載らないものは、欠けていても repo 側からは見えない。

<!-- bearing:aim v0.26.0 dir=docs/aims sha=6d8693bb3c91e20f -->
## aim frame

⚠ **この repo が aim corpus を持つなら、開発はそれによって駆動される。** `docs/aims/<slug>.md` の各ファイルが 1 つの aim（目的とその手段）であり、親子で目的を分解した木を成す。


- **aim に触れる前に `aim` skill を読むこと。** slug の付け方、body の section、木の保守、drift の検出と修復は、そこが唯一の正本である。
- **frontmatter は人間のもの、body はあなたのもの。** `aim:`（目的 1 文）・`parent:`（木の位置）・`state:`（open / done / dead）を書き換えてはならない。目的が動くべきだと考えたなら、候補を提案して人間に escalate する。確定は人間の act である。
- **目的を単独で決めない。** 手段は提案し、実装してよい。だが「何のためか」と「それが達成されたか」の宣言は人間が担う。あなたが body に記すマークは*実装された事実*であって、*目的が満たされたこと*ではない。
- **`[todo]` は、あなたが自力で完了を確認できることだけを書く。** 人間の観測・判断を完了条件に持つものを書いてはならない —— あなたに完結できないうえ、`open-todo`（＝ エージェントの残務）に人間待ちが混ざって数が嘘になる。人間の観測が要ると分かったら、todo を「**観測できるようにする**」へ書き換える。判断そのものが要るなら escalate する。
- **迷ったら escalate する。** 維持はあなたの仕事だが、判断を人間から奪わない。
<!-- /bearing:aim -->
