---
name: aim
description: aim corpus（既定 docs/aims/）—— この project を駆動する purpose＝means の木 —— を読み・書き・保守する方法。aim node を読む／作る／編集する前、boot 時の drift / unpushed / checkpoint-stale の record が slug を名指したとき、open todo やこの project が何のためかを問われたときに使う。
---

# aim

corpus の各ファイル `<slug>.md`（在り処は既定 `docs/aims/`。`CLAUDE.md` の法の block の `dir=` が宣言する）が 1 つの **aim**（目的とその手段）であり、親子で目的を分解した木を成す。

**aim の作成と保守の正本は傍らの [`aim-authoring.md`](aim-authoring.md)。aim に触れる前に読むこと。** slug の付け方・body の section・木の保守・drift の検出と修復は、そこが唯一の source である。

**セッション開始時に注入される事実の読み方の正本は [`aim-facts.md`](aim-facts.md)。** fence の schema、各 fence が課すもの、open-todo 数の扱い、`# PROCESS` の機械 parse 形、CLI —— これらを知る必要が出たらそこを読む。⚠ **fence を parse せよ。prose を scrape するな。**

常時効く不変（frontmatter は人間のもの・body はあなたのもの 等）は `CLAUDE.md` の法の block と SessionStart hook が運び、通常はセッション開始時に既に context に在る。**ここには複製しない** —— 同じ規則が context に二度入ることになり、しかも複製した側が先に古くなる。

⚠ **この skill は `/bearing:setup-aim` がこの repo の `.claude/skills/aim/` へ置いたものであり、置かれた瞬間からこの repo のものである。** plugin は追随させない —— 直すのも、古いままにするのも、この repo が決める。
