# aim — producer guide（作成と保守）

このプロジェクトは **aim で開発を進める**。`docs/aims/<slug>.md` = purpose=means 木。各 node = 1 つの目的（aim）とその手段、親 = 目的の分解。あなた（producer）がこの木を author・保守する。新規 node を書く前に親と関連 node を読み、木に整合させる。

## 手段 ＝ IS（means＝IS。PROCESS の todo ではない）

最重要 frame。**「手段」を PROCESS の `[todo]` と取り違えるな**。目的（`aim:`）が pin され、その達成のための**手段 ＝ あなたの IS**（aim をどう読んだか ＝ 選んだアプローチ）。1 つの aim に live な IS は実質 **1 つ**（逐次に数撃つ）。IS がミスアプローチと分かれば **旧 IS を理由つきで HISTORY へ送り、新しい IS を立てる**（＝手段を棄却して次を撃つ）。PROCESS の `[done]`/`[todo]` は **その IS を実現する進捗の可視化**であって、並行する複数の手段ではない。

言語化できた制約は **小目的 ＝ 子 aim** として木に結実する（aim 内でなく **tree** で構造化）。ただし **aim を立てる（PIN）のは operator の act** — 会話から導出されても **Producer は勝手に立てず、提案して escalate**（`aim:`/`parent:` は人間・確定は人間。**目的の手綱＝責任の所在は常に人間**）。∴ **木そのものが method**：**人間が**目的を pin → **あなたが** IS（手段）を立て実装 → 不満なら**人間が**子 aim を pin（あなたは提案）／あなたが IS を HISTORY へ送り新 IS を立てる。制約は検証から **後ろ向きに accrete** する（先に仕様がありそれが駆動するのではない＝仕様駆動の逆）。**木の成長が学習エンジン**。

## frontmatter は人間 / body はあなた

- `aim:`（目的 1 文）= 人間の bearing。**絶対に書き換えない**。目的が動くべきなら候補を提案し **escalate**（確定は人間）。
- `parent:`（木の位置）も人間。再 parent も escalate。
- `state:`（open/done/dead）も人間（解決の act）。あなたは判定しない。
- body（下記 5 section）= あなたのもの。起草・保守する。

## slug はあなたのもの

ファイル名 = slug = node の安定 identity。lowercase kebab-case・`--` と先頭末尾 `-` なし・日付形でない。誕生時の placeholder は早めに clean な slug へ rename（参照ゼロなら安全。参照があれば子の `parent:` と body 内 `[[link]]` を追従更新し dangling を残さない）。

## body の 5 section

- `# IS` — あなたが aim を **どう読んだか ＝ 選んだ手段（アプローチ）**（目的 1 文では決まらない現実的解釈）。人間が解釈＝手段の妥当性を確認する surface。最上部・常に。
- `# ESCALATION` — **「Go だけでは進めない＝人間の判断が要る」点のみ**。残留リスク → IS へ。やる作業 → PROCESS の `[todo]`。既決 → IS に事実として。無ければ省略。
- `# PROCESS` — **現 IS（手段）を実現する進捗**を phase / 条件で分け、各行 `[done]` / `[todo]`（進捗はこの mark が担う。並行する手段ではない）。**`[done]` = その手段が実装され存在する事実**（「実装されたか」だけを見る ＝ あなたの call で flip してよく operator 確認は要らない）。**効果・満足の評価は別レイヤで、それは `state:done` ＝ operator の解決 act が担う**（[[aim-resolution-outcome]]：解決時に done=満足 / todo=諦め と仕分ける）。
- `# HISTORY` — **棄却した手段 ＝ 旧 IS** の append-only 台帳（理由つき・同じ轍を踏まない）。
- `# DAG` — 木で辿れない依存を `[[slug]]` で（慣例ラベル `依存:` / `関連:` / `検証:`）。**親は書かない**。

作成は安くてよい: anchor + parent だけの誕生（body 後積み）も正規。

## drift（不整合）の検出と保守

aim は生きて変わるため、ある変更が関連 aim との不整合（drift）を生みうる。**engine 稼働時は engine が drift を検出・提示する。offline（engine 無し）では検出もあなたの仕事**:

- **検出**: 変更 / 作成した node の **隣接（親・子・`[[link]]` 先・自身）** を点検。安い目安 = **一緒に commit されていない隣接は、その変更を反映していない可能性**（anchor だけでなく body も主張を載せるので **whole-file** で見る）。変更を辿って外へ広げ、直す必要が無くなった枝で止める。**断定でなく可能性** — 確かめてから動く。
- **保守（あなたが解決）**: body が **自 anchor と食い違う**（anchor は固定の目的、そこへ body を寄せる）／ **他 aim の body=手段と食い違う**（両 body はあなたのもの）。自分の artifact を整えるのは当然の役目。
- **escalate するのは解決が (a) anchor=目的の変更、または (b) どちらの目的が正か等の判断 を要する時のみ。迷えば escalate**（維持はするが判断は奪わない）。
- 複数 node を整合させたら **一緒に commit**（一緒に直した記録。1 つだけ commit すると隣接が候補のまま残る）。

## 骨格

```
---
aim: <人間が書く目的 1 文。producer は触らない>
parent: <親 slug。root なら省略>
state: open
---

# IS
<aim をどう読んだか>

# PROCESS
- [todo] <手段。完了で [done]>
```

ESCALATION / HISTORY / DAG は必要な時だけ足す（純 ought の誕生は IS / PROCESS だけでよい）。
