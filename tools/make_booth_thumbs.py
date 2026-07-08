"""BOOTH 出品用サムネイル生成（本体 / 支援版 / 自動採譜アドオン）。

  python tools/make_booth_thumbs.py [出力先ディレクトリ=docs]

アプリのブランド（ダーク背景・青 #4a9eff・橙 #ff9d54＝発音中の色）で統一。
Windows の Yu Gothic を使用。再レンダー可能なので価格/文言変更に追従できる。
"""
import os
import sys
import random
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W = H = 1080
BG_TOP = (18, 18, 27)
BG_BOT = (32, 32, 46)
ACCENT = (74, 158, 255)
ACCENT2 = (255, 157, 84)
WHITE = (245, 245, 250)
MUTED = (150, 152, 175)
FAINT = (110, 112, 135)
PAPER = (242, 239, 230)
INK = (34, 34, 40)
CARD = (36, 36, 54)

YUB = "C:/Windows/Fonts/YuGothB.ttc"
YUM = "C:/Windows/Fonts/YuGothM.ttc"
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
ICON = os.path.join(_REPO, "assets", "icon.png")


def F(path, sz):
    return ImageFont.truetype(path, sz)


def new_canvas():
    img = Image.new("RGB", (W, H), BG_TOP)
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        d.line([(0, y), (W, y)],
               fill=tuple(int(BG_TOP[i] + (BG_BOT[i] - BG_TOP[i]) * t) for i in range(3)))
    return img, d


def shadow(img, box, radius, blur=18, alpha=120, dxy=(0, 10)):
    lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(lay)
    b = [box[0] + dxy[0], box[1] + dxy[1], box[2] + dxy[0], box[3] + dxy[1]]
    ld.rounded_rectangle(b, radius=radius, fill=(0, 0, 0, alpha))
    img.paste(lay.filter(ImageFilter.GaussianBlur(blur)), (0, 0),
              lay.filter(ImageFilter.GaussianBlur(blur)))


def chip_row(d, cy, items, font, gap=16):
    widths = [d.textlength(t, font=font) + 40 for t in items]
    total = sum(widths) + gap * (len(items) - 1)
    x = (W - total) / 2
    for t, w in zip(items, widths):
        d.rounded_rectangle([x, cy, x + w, cy + 48], radius=24, fill=CARD,
                            outline=(70, 80, 110), width=2)
        d.text((x + w / 2, cy + 24), t, font=font, fill=WHITE, anchor="mm")
        x += w + gap


def chevron_down(d, cx, cy, col=ACCENT, s=22):
    d.line([(cx - s, cy), (cx, cy + s)], fill=col, width=7)
    d.line([(cx + s, cy), (cx, cy + s)], fill=col, width=7)


def mini_keyboard(d, box):
    x0, y0, x1, y1 = box
    n = 8
    kw = (x1 - x0) / n
    for i in range(n):
        x = x0 + i * kw
        pressed = i in (2, 5)
        d.rectangle([x + 1, y0, x + kw - 1, y1],
                    fill=ACCENT if pressed else (232, 232, 240), outline=(60, 60, 80))
        if i % 7 in (0, 1, 3, 4, 5):
            d.rectangle([x + kw * 0.62, y0, x + kw * 1.02, y0 + (y1 - y0) * 0.6],
                        fill=(40, 40, 55))


def mini_falling(d, box):
    x0, y0, x1, y1 = box
    lanes = 4
    lw = (x1 - x0) / lanes
    line_y = y1 - 14
    d.line([(x0, line_y), (x1, line_y)], fill=ACCENT2, width=4)
    random.seed(5)
    for i in range(lanes):
        cx = x0 + i * lw + lw / 2
        for _ in range(random.randint(1, 2)):
            by = random.randint(int(y0), int(line_y - 40))
            col = ACCENT if i % 2 == 0 else ACCENT2
            d.rounded_rectangle([cx - lw * 0.3, by, cx + lw * 0.3, by + 26], radius=6, fill=col)


def paste_icon(img, cx, cy, size):
    try:
        ic = Image.open(ICON).convert("RGBA").resize((size, size), Image.LANCZOS)
        img.paste(ic, (int(cx - size / 2), int(cy - size / 2)), ic)
        return True
    except OSError:
        return False


def heart(d, cx, cy, s, col):
    r = s / 2
    d.ellipse([cx - r, cy - r / 2, cx, cy + r / 2], fill=col)
    d.ellipse([cx, cy - r / 2, cx + r, cy + r / 2], fill=col)
    d.polygon([(cx - r + 2, cy + r / 6), (cx + r - 2, cy + r / 6), (cx, cy + r * 1.2)], fill=col)


# ---------------------------------------------------------------- 本体 / 支援版
def draw_base(support=False):
    img, d = new_canvas()
    d.text((W / 2, 54), "楽譜を、自動で弾かせる。", font=F(YUB, 56), fill=WHITE, anchor="ma")
    d.text((W / 2, 126), "自分で弾けるように、もなる。", font=F(YUB, 56), fill=ACCENT, anchor="ma")

    d.text((W / 2, 224), "① いろんな楽譜を取り込む", font=F(YUM, 27), fill=MUTED, anchor="ma")
    chip_row(d, 268, ["テキスト", "数字譜", "MIDI", "MusicXML"], F(YUM, 26))
    chip_row(d, 326, ["画像", "PDF", "なぞり入力"], F(YUM, 26))

    chevron_down(d, W / 2, 392)
    paste_icon(img, W / 2, 470, 96)
    d.text((W / 2, 524), "AutoPlayNotes", font=F(YUB, 40), fill=WHITE, anchor="ma")
    chevron_down(d, W / 2, 590)

    # 出口2枚
    cy0, cy1 = 628, 812
    lb = [92, cy0, 520, cy1]
    rb = [560, cy0, 988, cy1]
    for b in (lb, rb):
        shadow(img, b, 22)
        d.rounded_rectangle(b, radius=22, fill=CARD, outline=(70, 80, 110), width=2)
    d.text((306, cy0 + 26), "自動演奏", font=F(YUB, 34), fill=ACCENT, anchor="ma")
    mini_keyboard(d, [140, cy0 + 92, 472, cy0 + 132])
    d.text((306, cy1 - 46), "ゲームへ自動でキー入力", font=F(YUM, 23), fill=MUTED, anchor="ma")
    d.text((774, cy0 + 26), "練習モード", font=F(YUB, 34), fill=ACCENT2, anchor="ma")
    mini_falling(d, [600, cy0 + 78, 948, cy0 + 150])
    d.text((774, cy1 - 46), "自分で弾く練習・ゲームに触れない", font=F(YUM, 22), fill=MUTED, anchor="ma")

    if support:
        d.rounded_rectangle([W / 2 - 250, 862, W / 2 + 250, 906], radius=22, fill=ACCENT2)
        d.text((W / 2, 884), "支援版 ― 中身は通常版（¥200）と同じ", font=F(YUB, 26),
               fill=(35, 22, 10), anchor="mm")
        d.text((W / 2, 928), "「気に入ったから応援したい」方向けの価格です。ありがとうございます。",
               font=F(YUM, 24), fill=MUTED, anchor="ma")
    else:
        d.text((W / 2, 866), "特定のゲーム“専用”じゃない。色々なゲームで、これ1つ。",
               font=F(YUB, 30), fill=WHITE, anchor="ma")
        d.text((W / 2, 922), "ソースは無料公開（MIT）／すぐ使えるビルド済み exe",
               font=F(YUM, 24), fill=FAINT, anchor="ma")
    return img


# ---------------------------------------------------------------- アドオン
def mini_waveform(d, box, seed=9):
    x0, y0, x1, y1 = box
    mid = (y0 + y1) / 2
    random.seed(seed)
    n = 40
    bw = (x1 - x0) / n
    for i in range(n):
        x = x0 + i * bw + bw / 2
        env = max(0.15, 1 - abs(i / n - 0.4) * 1.3)
        amp = max(3, (y1 - y0) * 0.4 * (0.35 + random.random()) * env)
        col = ACCENT if i % 4 else ACCENT2
        d.line([(x, mid - amp), (x, mid + amp)], fill=col, width=max(2, int(bw * 0.55)))


def draw_addon():
    img, d = new_canvas()
    d.text((W / 2, 50), "画像も、音源も。", font=F(YUB, 58), fill=WHITE, anchor="ma")
    d.text((W / 2, 124), "ローカル AI で、譜面に。", font=F(YUB, 58), fill=ACCENT, anchor="ma")
    d.text((W / 2, 214), "五線譜の画像・PDF ／ 音源（音声ファイル）から、自動で“下書き”譜面に。",
           font=F(YUM, 28), fill=MUTED, anchor="ma")

    # 左：2つの入口（画像/PDF・音源）
    AX0, AX1 = 70, 430
    ay0, ay1 = 300, 452     # 画像カード
    by0, by1 = 476, 628     # 音源カード
    # 画像/PDF カード（紙・五線譜）
    shadow(img, [AX0, ay0, AX1, ay1], 22)
    d.rounded_rectangle([AX0, ay0, AX1, ay1], radius=22, fill=PAPER)
    sx0, sx1 = AX0 + 30, AX1 - 24
    for i in range(5):
        yy = ay0 + 62 + i * 16
        d.line([(sx0, yy), (sx1, yy)], fill=(120, 118, 110), width=3)
    random.seed(3)
    nx = sx0 + 22
    for _ in range(5):
        cy = ay0 + 94 - random.randint(0, 6) * 8
        d.ellipse([nx, cy - 9, nx + 20, cy + 9], fill=INK)
        d.line([(nx + 19, cy), (nx + 19, cy - 42)], fill=INK, width=4)
        nx += 60
    d.rounded_rectangle([AX0 + 14, ay0 + 14, AX0 + 128, ay0 + 46], radius=16, fill=(210, 205, 190))
    d.text((AX0 + 71, ay0 + 30), "画像・PDF", font=F(YUB, 20), fill=(90, 88, 80), anchor="mm")
    # 音源カード（ダーク・波形）
    shadow(img, [AX0, by0, AX1, by1], 22)
    d.rounded_rectangle([AX0, by0, AX1, by1], radius=22, fill=CARD, outline=(70, 80, 110), width=2)
    mini_waveform(d, [AX0 + 26, by0 + 50, AX1 - 26, by1 - 24])
    d.rounded_rectangle([AX0 + 14, by0 + 14, AX0 + 104, by0 + 46], radius=16, fill=(50, 52, 72))
    d.text((AX0 + 59, by0 + 30), "音源", font=F(YUB, 20), fill=WHITE, anchor="mm")

    # 中央：2入力の合流 → 自動採譜（ローカルAI）
    ax, ay = 512, 464
    d.line([(AX1, (ay0 + ay1) / 2), (ax - 38, ay)], fill=(90, 100, 130), width=4)
    d.line([(AX1, (by0 + by1) / 2), (ax - 38, ay)], fill=(90, 100, 130), width=4)
    d.polygon([(ax - 38, ay - 26), (ax - 38, ay + 26), (ax + 32, ay)], fill=ACCENT)
    d.text((ax - 3, ay + 40), "自動採譜", font=F(YUB, 24), fill=ACCENT, anchor="ma")
    d.rounded_rectangle([ax - 88, ay - 98, ax + 82, ay - 54], radius=22, fill=(28, 30, 46),
                        outline=ACCENT2, width=2)
    d.text((ax - 3, ay - 76), "ローカル AI", font=F(YUB, 22), fill=ACCENT2, anchor="mm")

    # 右：譜面データ（ピアノロール）
    RX0, RX1 = 600, 1010
    ry0, ry1 = 340, 620
    shadow(img, [RX0, ry0, RX1, ry1], 26)
    d.rounded_rectangle([RX0, ry0, RX1, ry1], radius=26, fill=CARD, outline=ACCENT, width=3)
    kx = RX0 + 18
    for i in range(9):
        yy = ry0 + 34 + i * 26
        d.rectangle([kx, yy, kx + 30, yy + 24], fill=(230, 230, 238), outline=(60, 60, 80))
        if i % 7 in (1, 2, 4, 5, 6):
            d.rectangle([kx, yy, kx + 18, yy + 24], fill=(40, 40, 55))
    random.seed(7)
    bx0 = kx + 42
    for i in range(9):
        yy = ry0 + 34 + i * 26
        if random.random() < 0.7:
            x = bx0 + random.randint(0, 90)
            w = random.randint(70, 230)
            col = ACCENT if (i + random.randint(0, 1)) % 2 == 0 else ACCENT2
            d.rounded_rectangle([x, yy + 3, min(x + w, RX1 - 20), yy + 21], radius=7, fill=col)
    d.rounded_rectangle([RX1 - 154, ry0 + 14, RX1 - 16, ry0 + 46], radius=16, fill=ACCENT)
    d.text((RX1 - 85, ry0 + 30), "譜面データ", font=F(YUB, 20), fill=(12, 20, 40), anchor="mm")

    # ローカルAI 訴求チップ
    chip_row(d, 672, ["クラウド送信なし", "サブスクなし", "オフラインOK", "曲数無制限"], F(YUM, 25))

    # 下部
    d.rounded_rectangle([300, 762, 780, 770], radius=4, fill=ACCENT)
    d.text((W / 2, 792), "AutoPlayNotes 採譜アドオン", font=F(YUB, 46), fill=WHITE, anchor="ma")
    d.text((W / 2, 860), "画像も音源も、ぜんぶあなたの PC の中で解析。", font=F(YUM, 28),
           fill=MUTED, anchor="ma")
    d.text((W / 2, 910), "omr と pitch の2フォルダを本体と同じ場所に置くだけ／追加インストール不要",
           font=F(YUM, 24), fill=FAINT, anchor="ma")
    return img


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_REPO, "docs")
    os.makedirs(out, exist_ok=True)
    jobs = {
        "booth-base-thumb.png": lambda: draw_base(support=False),
        "booth-support-thumb.png": lambda: draw_base(support=True),
        "booth-omr-thumb.png": draw_addon,
    }
    for name, fn in jobs.items():
        p = os.path.join(out, name)
        fn().save(p)
        print("saved", p)


if __name__ == "__main__":
    main()
