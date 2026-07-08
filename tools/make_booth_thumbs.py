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
def draw_addon():
    img, d = new_canvas()
    d.text((W / 2, 60), "画像・PDF から、自動で譜面に。", font=F(YUB, 58), fill=WHITE, anchor="ma")
    d.text((W / 2, 138), "五線譜をなぞる手間を、まず自動で“下書き”に。", font=F(YUM, 30),
           fill=MUTED, anchor="ma")

    PY0, PY1 = 300, 720
    LX0, LX1, RX0, RX1 = 70, 468, 612, 1010
    d.text(((LX0 + LX1) / 2, PY0 - 46), "画像・PDF", font=F(YUM, 28), fill=MUTED, anchor="ma")
    d.text(((RX0 + RX1) / 2, PY0 - 46), "譜面データ（編集できる）", font=F(YUM, 28),
           fill=MUTED, anchor="ma")

    shadow(img, [LX0, PY0, LX1, PY1], 26)
    d.rounded_rectangle([LX0, PY0, LX1, PY1], radius=26, fill=PAPER)

    def staff(y0, seed):
        x0, x1 = LX0 + 34, LX1 - 26
        for i in range(5):
            yy = y0 + i * 20
            d.line([(x0, yy), (x1, yy)], fill=(120, 118, 110), width=3)
        random.seed(seed)
        nx = x0 + 22
        for j in range(6):
            step = random.randint(0, 8)
            cy = y0 + 80 - step * 10
            hollow = (j % 5 == 2)
            d.ellipse([nx, cy - 11, nx + 24, cy + 11],
                      fill=None if hollow else INK, outline=INK, width=4 if hollow else 1)
            d.line([(nx + 23, cy), (nx + 23, cy - 55)], fill=INK, width=4)
            nx += 58
    staff(PY0 + 70, 3)
    staff(PY0 + 230, 11)
    d.rounded_rectangle([LX0 + 16, PY0 + 16, LX0 + 132, PY0 + 52], radius=18, fill=(210, 205, 190))
    d.text((LX0 + 74, PY0 + 34), "BEFORE", font=F(YUB, 24), fill=(90, 88, 80), anchor="mm")

    ax = (LX1 + RX0) // 2
    d.polygon([(ax - 46, PY0 + 190), (ax - 46, PY0 + 230), (ax + 20, PY0 + 230),
               (ax + 20, PY0 + 255), (ax + 60, PY0 + 210), (ax + 20, PY0 + 165),
               (ax + 20, PY0 + 190)], fill=ACCENT)
    d.text((ax + 7, PY0 + 284), "自動採譜", font=F(YUB, 26), fill=ACCENT, anchor="ma")

    shadow(img, [RX0, PY0, RX1, PY1], 26)
    d.rounded_rectangle([RX0, PY0, RX1, PY1], radius=26, fill=CARD, outline=ACCENT, width=3)
    kx = RX0 + 18
    for i in range(14):
        yy = PY0 + 30 + i * 26
        d.rectangle([kx, yy, kx + 34, yy + 24], fill=(230, 230, 238), outline=(60, 60, 80))
        if i % 7 in (1, 2, 4, 5, 6):
            d.rectangle([kx, yy, kx + 20, yy + 24], fill=(40, 40, 55))
    random.seed(7)
    bx0 = kx + 46
    for i in range(14):
        yy = PY0 + 30 + i * 26
        if random.random() < 0.62:
            x = bx0 + random.randint(0, 90)
            w = random.randint(60, 210)
            col = ACCENT if (i + random.randint(0, 1)) % 2 == 0 else ACCENT2
            d.rounded_rectangle([x, yy + 3, min(x + w, RX1 - 20), yy + 21], radius=7, fill=col)
    d.rounded_rectangle([RX1 - 132, PY0 + 16, RX1 - 16, PY0 + 52], radius=18, fill=ACCENT)
    d.text((RX1 - 74, PY0 + 34), "AFTER", font=F(YUB, 24), fill=(12, 20, 40), anchor="mm")

    d.rounded_rectangle([300, 812, 780, 820], radius=4, fill=ACCENT)
    d.text((W / 2, 850), "AutoPlayNotes 自動採譜アドオン", font=F(YUB, 46), fill=WHITE, anchor="ma")
    d.text((W / 2, 918), "“探す→手入力”の数十分〜数時間を、まず自動で下書きに。",
           font=F(YUM, 28), fill=MUTED, anchor="ma")
    d.text((W / 2, 968), "omr フォルダを本体と同じ場所に置くだけ／追加インストール不要",
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
