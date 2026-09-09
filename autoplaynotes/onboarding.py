"""自動演奏から練習への導線（→ `docs/aims/practice-onboarding.md`）。

自動演奏で来る人は練習したい人と別のセグメントではなく、あきらめた同一人物である。
∴ 足りないのは機能の肩代わりではなく**導線**であり、この module はその導線のうち
判断の部分だけ ——「最初に何を見せるか」と「いつ声を掛けるか」—— を純関数で持つ。

GUI から切り離してあるのは、この 2 つが最も静かに壊れる層だからである（画面には
出ているので壊れても動いて見え、誰も気づかない）。
"""

from __future__ import annotations

TAB_PRACTICE = "🎮 練習"
TAB_PLAY = "🎹 演奏"
TAB_PLAYLIST = "🎵 プレイリスト"
TAB_SETTINGS = "⚙ 設定"
TAB_LOG = "📄 ログ"

# 練習を先頭に置く。ただし自動演奏はその隣に在り、消しも隠しもしない
# （妥協を否定せず、隣に道が続いていることを見せるだけ）。
TAB_ORDER: tuple[str, ...] = (TAB_PRACTICE, TAB_PLAY, TAB_PLAYLIST, TAB_SETTINGS, TAB_LOG)


def startup_tab(last_tab: str) -> str:
    """起動時に開くタブを返す。前回のタブを尊重し、無ければ練習から始める。

    毎回 練習 へ引き戻すのは説教であって導線ではない。∴ 自分でタブを選んだ人には
    その選択のほうが優先される。未知の名前（旧版の設定・改名後）は既定へ落とす。
    """
    return last_tab if last_tab in TAB_ORDER else TAB_PRACTICE


def should_invite(
    *,
    stopped: bool,
    playlist_active: bool,
    assist: bool,
    enabled: bool,
    note_count: int,
    already_invited: bool,
) -> bool:
    """自動演奏の直後に「この曲、弾いてみますか？」を出すか。

    誘ってよいのは**曲が最後まで鳴りきった 1 回だけ**である。以下はいずれも
    「声を掛けると邪魔になる」形なので出さない:

    - `stopped`: 途中で止めた人は、その曲を聴き終えていない。
    - `playlist_active`: 次の曲が始まる直前であり、割り込むと再生が途切れる。
    - `assist`: 補助演奏 ＝ その人はもう自分で弾いている。誘う相手ではない。
    - `already_invited`: 同じ曲で二度目は、勧誘であって導線ではない。
    """
    if not enabled or stopped or playlist_active or assist or already_invited:
        return False
    return note_count > 0


def playable_note_count(score, mapping) -> int:
    """その割り当てで実際にキーへ解決できる音の数。

    ⚠️ 楽譜に音が在っても、鍵盤の外・スケール外の音しか無ければ 1 音も鳴らない
    （プレイヤーは「演奏できる音がありません」で終わる）。その直後に「弾いてみますか？」
    を出すと、鳴っていない曲を弾けと言うことになる ∴ 誘いの数え方は楽譜の音数ではなく
    こちらである。
    """
    return sum(
        1
        for event in score.events
        for note in event.midi_notes
        if mapping.resolve(note) is not None
    )


INVITE_TITLE = "この曲、弾いてみますか？"

# 誘いの本文。⚠️ 説教しないこと —— 自動演奏を選んだことは失敗ではない。
INVITE_LEAD = "『{title}』を最後まで鳴らしました。"
INVITE_BODY = (
    "次は、この {count} 音のうち一部だけをあなたが弾く、という始め方ができます。"
    "「🎹 演奏範囲」で自分の担当を決めれば、残りはアプリが受け持ちます。"
)
INVITE_FOOTER = "気が向かなければ、このまま自動演奏で構いません。"


def invite_lead(title: str) -> str:
    """誘いの 1 行目。曲名が無い楽譜でも文が壊れないようにする。"""
    return INVITE_LEAD.format(title=title.strip() or "この曲")


def invite_body(title: str, count: int) -> str:
    return INVITE_BODY.format(title=title.strip() or "この曲", count=count)
