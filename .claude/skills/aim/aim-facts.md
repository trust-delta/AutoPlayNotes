# aim-facts — セッション開始時に注入される aim の事実

`aim-facts` は、cwd から解決した unit の各 repo の `docs/aims/` を読み、**frame と機械可読な事実**を stdout に出す。server も port も要らない。エージェントのセッション開始時にこれを流し込むことで、`aim` で駆動する project の状態がそのセッションの context に載る。

この doc は**その出力をどう読み、何を義務づけられるか**の正本である。aim をどう作成・保守するかは [`aim-authoring.md`](aim-authoring.md)、常時効く不変は [`frame.md`](frame.md) が持つ。ここには**それらに無いこと**だけを書く。

⚠ **仕様と許容度を区別して読むこと。** ここに書かれたことのうち、**corpus から測られたもの**（実際の記法を全数で数えた結果など）と、**実装がたまたま許すもの**は別である。後者を契約と受け取ると、実装の癖が正本に化ける。切り分けの済んだ箇所には**測定値を併記**してある。

---

## 事実は fence で読む —— prose を scrape しない

出力には人が読む prose と、機械が読む fenced block の両方が載る。**必ず fence を parse すること。** prose の言い回しは変わりうるが、fence の schema は tag の `v1` が保証する。

fence は **records が空でも必ず出る**。空の block は「**該当なし**」であって「**計算されなかった**」ではない。この 2 つを取り違えると、観測できなかったことを「問題なし」と報告することになる。空のときは `# none — …` の 1 行が入る。

各 block の 1 行目は `# fields: …` のヘッダで、以降が 1 行 1 record（` | ` 区切り）。

### 6 枚の fence

| fence tag | fields | 何の事実か |
| :-- | :-- | :-- |
| `bearing-drift-intra v1` | `slug \| anchor_commit \| body_moved` | 自 node の `aim:` が**改訂**され、以後 body がそれに寄せられたかどうか |
| `bearing-drift-inter v1` | `slug \| anchor_commit \| unreconciled_neighbours` | 隣接 node（親・子・`[[link]]` 先）のうち、その変更と一緒に commit されておらず、かつ `照合:` 記録でも片付いていないもの |
| `bearing-working-delta v1` | `slug \| uncommitted \| uncommitted_anchor_change \| untracked` | working tree にある未 commit / 未 track の node。presence のみで順序を含まない |
| `bearing-unpushed v1` | `slug \| ahead_commits \| latest_sha \| latest_date` | commit 済だが remote に届いていない aim commit |
| `bearing-checkpoint-stale v1` | `slug \| checkpoint_sha \| commits_since` | `last-verified` を持つ node の checkpoint から repo がどれだけ動いたか |
| `bearing-awaiting-observation v1` | `slug \| done_marks \| state` | エージェントが尽くし（mark が在り、その全てが `[done]`）、人間がまだ `state: done` を宣言していない node |

⚠ **前の 5 枚は git の事実だが、6 枚目だけは corpus の事実である。** git が読めなくても出る。

**drift が 2 枚に割れるのは、2 種の drift が trigger を共有しないため**である。「同一 aim 内」は anchor の*改訂*のみが隙間を開ける（誕生時、body は anchor と共に書かれる）が、「aim 同士」は*作成*も trigger になる（親を動かさずに子を足す形）。∴ 1 枚に畳むと、どちらかの trigger が黙って落ちる。

⚠ **checkpoint-stale に閾は無い。** 「N commit 未満は候補から落とす」という数を名指す `aim:` 文が存在しない ∴ 導出を持たない filter は検査面を運任せで削ることになる。少なく出したいなら、まず閾を目的として書くこと。

⚠ **履歴の浅い corpus では、履歴を読む 3 枚が構造的に沈黙する。** `drift-intra` は anchor の*変更* commit を、`drift-inter` は「一緒に commit されていない隣接」を、`checkpoint-stale` は `last-verified` からの経過を見る ∴ 誕生 commit しか無い間、3 枚とも空になる。**空を「該当なし」と読む前に、噛むものが在るかを確かめること** —— これは working / broken のどちらでもない第 3 の状態である。

### 各 fence が課すもの

**drift は可能性であって断定ではない。** 挙がった node が親の `aim:` の bearing になお仕えているかを再確認する。**body 内に閉じた改訂で再整合できるなら、それはあなたの担当** —— node を編集すれば flag は self-clear する。**親の bearing 自体が問われているときにのみ人間へ escalate する。**

⚠ **`drift-inter` を「見たが変更不要だった」で終えてはならない。** その結論は何も動かさない ∴ file の移動しか見ない絞り込みでは永久に落ちず、**既に見た者へ「見よ」と言い続ける** —— 可視化ではなく注意予算への課税である。`# DAG` に `照合:` の 1 行を残すこと（形と規律は `aim-authoring.md` の「drift の検出と保守」）。⚠ **flag が無関係な編集で消えるのを待つのは、判断を捨てることである** —— この fence は整合したかを見ておらず、隣接が動けば理由を問わず落ちるので、**書かなかった判断はどこにも残らないまま flag だけが消える。**

**working-delta は presence のみを述べ、順序を一切含意しない。** working tree の中に順序の事実は無いので、この層は比較を行わない。commit された瞬間にこの node の working fact は消え、drift 側の本物の順序判定が引き継ぐ。∴ **ここに時系列を読み込むな。**

**unpushed は「既に済んだ作業」の frontier。** baton は forward に選択されるため、道中どう aim を触ったかを構造的に過少報告する。ここに挙がった slug は **re-read すること** —— aim を読み直して得られるのは*到達状態*であって*変化*ではないが、この差分だけが変化を運ぶ。

**awaiting-observation は「終わった aim」の一覧ではない。** ここに挙がるのは *エージェントの側が*尽きた node であり、⚠ **満足したかどうかを述べられるのは人間だけである** —— この fence はそれを一切先取りしない。∴ **surface はせよ。だが「これは done にしてよい」と提案するな。** 逆に、⚠ **ここが空であることは「番が渡っていない」を意味するのであって、「やることが無い」ではない。** ⚠ **`open-todo` と `escalation` の両方と併せて読むこと: 3 つとも 0 で初めて、エージェントにも人間にも渡っていない ＝ node が純 IS のままか、すべて解決済みである。** ⚠ **2 つだけで読んではならない** —— `# ESCALATION` を持つ node は、`open-todo` も awaiting も 0 のまま**人間で止まっている**。

**checkpoint-stale は verdict ではない。** footprint はまだ node 自身の code へ絞られておらず、repo 全体が動いただけかもしれない。挙がった slug は「**再検証する価値がありうる候補**」として扱う。判断不要な絞り込みは fan-out してよいが、**aim が code から剥離したという宣言は人間の act** である（`state: done` と同じ層）。

---

## open-todo 数

出力は `open-todo: N` を含む。N ＝ **`[todo]` mark を 1 つ以上持つ aim node の数**。

- **node 単位で 1 回**数える（1 つの node が todo を何個並べても 1）。
- **`state: dead` の node は除く。**
- unit の**全 repo を横断**して合算する。

これは **fact であり、fact でしかない。surface せよ。triage も ranking も、どれをやるべきかの提案もするな** —— 拾うものを選ぶのは人間の act である。

⚠ **この数はエージェントの残務であって、人間待ちを含まない。** `[todo]` はエージェントが自力で完了を確認できる形でのみ書かれる（[`aim-authoring.md`](aim-authoring.md) 「todo の完了条件」）∴ **人間の観測を待っているものがここに数えられていたら、それは記法の誤りであって backlog ではない。** 見つけたら、todo を「観測できるようにする」へ書き換えるか `# ESCALATION` へ出す。

⚠ **空の baton は空の project ではない。** ∴ **この数を述べずに「拾うものが無い」と報告してはならない。** これは記憶されたタイミングではなく*主張*を縛る: boot 時にも、何かを終えた後にも等しく効く。

---

## escalation 数

出力は `escalation: N` を含む。N ＝ **`# ESCALATION` に中身を持つ aim node の数**。

- **node 単位で 1 回**数える（1 つの node が判断待ちを何個並べても 1）。
- **`state: dead` の node は除く。** ⚠ 除外はこれ 1 つだけであり、`open-todo` と同じ規則である —— **`state: done` の node に残った escalation は、述べるべき食い違いであって、数える層が畳んでよいものではない。**
- unit の**全 repo を横断**して合算する。
- ⚠ **見出しだけ在って中身が無い節は、この数に入らない。** 読みに行っても何も書かれていないものを「人間待ち」として数えれば、数は権威のまま別のものを数える。⚠ **かといって黙って落としもしない** —— 別の行で名指される（`# PROCESS` の `unknown` と同じ法である）。

⚠ **これは `open-todo` の反対側である。** [`aim-authoring.md`](aim-authoring.md) の「todo の完了条件」は、**エージェントが自力で閉じられないと分かったものを `# ESCALATION` へ出せ**と定めている ∴ **2 つは同じ 1 つの分割の両側**であって、別々の関心ではない。⚠ **片側だけを surface する報告は、閉じられない側だけを黙って落とす。**

これも **fact であり、fact でしかない。surface せよ。triage も ranking も、どれから片付けるべきかの提案もするな。** ⚠ **どの数がより重いかを述べることは、注意予算の割り当てであって観測ではない** —— それは人間の act である。

---

## PROCESS の機械 parse 形

`# PROCESS` は body で**唯一機械に読まれる** section であり、読まれる形は厳密に決まっている。数えられたいなら、この形で書くこと。

⚠ **以下は 2026-08-31 に corpus 全数（77 node / 296 mark）で実測した。** 測定値と、実装が持つが**一度も行使されていない**許容度を分けて書く。

**見出しの特定** —— ATX 見出し（`#` の連続の直後に空白）のうち、`#` を剥いで trim した text が**ちょうど `PROCESS`** である**最初のもの**。⚠ **実測: 296 mark の全てが level 1 の `# PROCESS` の下にあり、`## PROCESS` は 0 件。** 実装は level を問わないが、その許容度は行使されていない。

**scope の終端** —— その見出しの次行から、**同じか浅い level の見出し**まで。実装は PROCESS 内の**深い**見出しを scope に留める。⚠ **実測: PROCESS 内の deeper 見出しは 0 件。** この規則は一度も発火していない。

**mark の形** —— bullet list item であって、その content が `[done]` / `[todo]` で**始まる**もの。⚠ **実測: bullet は `-` のみ 296/296、mark は小文字 `done` / `todo` のみ、字下げは 0 のみ、296 件全てが `# PROCESS` 直下。** 実装は `*` bullet と大小無視も受けるが、corpus はどちらも使っていない。

⚠ **∴ 上記 3 つの許容度（見出し level 不問・deeper 見出しの scope・`*` bullet と大小無視）は仕様ではなく実装の latitude である。** 正本で両者を混ぜてはならない —— 契約と読めば書き手は「`*` でもよい」と信じ、実装が変わった日に**黙って数え落とされる**。

⚠ **逸脱は、黙って吸収してもならないし、黙って無視してもならない。** 厳格な parser は `* [todo]` を静かに数え落とし、寛容な parser は corpus が自らの慣例から離れた事実を静かに埋める。**どちらの沈黙も嘘をつく。** ∴ 観測された形（`- [done]` / `- [todo]`・`# PROCESS` 直下・字下げ 0）を正とし、そこから外れた mark は**数えた上で anomaly として表面化する**。

⚠ **inline の prose 内の `[done]` / `[todo]` は数えない。** `# IS` や `# HISTORY` の散文に現れるこれらのトークン（「かつて `[todo]` だった」等）を数えないための形であり、**PROCESS 内の散文中に書いたものも同様に数えられない**。進捗として数えられたいなら list item にすること。⚠ **この法は corpus 側からも支持される** —— 同じ法（**引用は主張ではない**）が cross-ref にも現れ、素の正規表現が未解決と報告する 24 件は全て code span 内の記法引用で、code span を除くと 0 になる。

**結果は 4 値**:

| 値 | 意味 |
| :-- | :-- |
| `some-todo` | `[todo]` が 1 つ以上ある ＝ **エージェントに**未実装の手段が残っている |
| `all-done` | mark があり、その全てが `[done]` ＝ **エージェントが尽くした ∴ 人間の観測待ち** |
| `no-process` | `# PROCESS` 見出しが無い（純 IS の node。正常な状態） |
| `unknown` | 見出しはあるが、parse できる mark が 1 つも無い |

⚠ **`all-done` と `no-process` を「todo が 0 件」として同じに読んではならない。** 前者は **エージェントの側が終わっており、残っているのは人間の観測と `state:` の宣言だけ**という状態である。後者はまだ何も約束していない。⚠ **`all-done` かつ `state: open` の node は、この体制において「人間の番」を意味する** —— 数が 0 だからといって、その aim が閉じたわけではない。

⚠ **`unknown` を `all-done` に倒してはならない。** これは soft な散文 parse であって、drift のような hard な git 計算ではない。∴ 読めなかったときは**読めなかったと述べる** —— 捏造した `done` より正直な `unknown` が正しい。この非対称が、この層に与えられている権限の全てである。

---

## 呼び出し

composer は hook から**引数無しで**呼ばれる。⚠ **下の行は形の説明であって、写して打てる 1 行ではない** —— この canon は plugin にも workspace にも同じ text で運ばれる ∴ どちらの置き場も名指せない。frame は常に出し、unit は cwd から解決し、fence は必ず 5 枚出す。**flag は持たない。**

```
node <plugin root>/bin/aim-facts.mjs
```

⚠ **unit は cwd から解決される。** 呼ぶ側が `cd` してはならない。セッションの cwd こそが unit を定義しており、それを動かすと別の unit の事実を注入することになる。

⚠ **観測できなかった事実は「無い」であって「問題なし」ではない。** git が失敗した、corpus が読めない —— どの場合も出力は事実の**不在**である。fence が観測できなかったときは `# unavailable` とその旨を述べ、`# none`（該当なし）とは別の文言を出す。**この 2 つを取り違えてはならない。**
