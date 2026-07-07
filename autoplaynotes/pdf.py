"""PDF を画像化する（PDF ページ → PIL 画像 / 一時 PNG）。

楽譜の多くは PDF で配布されるため、トレース・OCR・OMR の入口として
PDF の各ページをラスタライズして渡せるようにする。pypdfium2（Apache/BSD・
外部バイナリ不要）を使い、未導入なら is_available() が False を返す。
"""

from __future__ import annotations

import os
import tempfile

try:
    import pypdfium2 as _pdfium

    _OK = True
except ImportError:  # pragma: no cover - pypdfium2 未導入環境
    _OK = False


def is_available() -> bool:
    return _OK


def is_pdf(path: str) -> bool:
    return os.path.splitext(path)[1].lower() == ".pdf"


def page_count(path: str) -> int:
    doc = _pdfium.PdfDocument(path)
    try:
        return len(doc)
    finally:
        doc.close()


def render_page(path: str, index: int = 0, scale: float = 2.0):
    """PDF の 1 ページを PIL.Image(RGB) にする。scale=2.0 で約 144dpi。"""
    doc = _pdfium.PdfDocument(path)
    try:
        index = max(0, min(index, len(doc) - 1))
        page = doc[index]
        pil = page.render(scale=scale).to_pil()
        return pil.convert("RGB")
    finally:
        doc.close()


def render_page_to_png(
    path: str, index: int = 0, scale: float = 2.78, dest: str | None = None
) -> str:
    """PDF の 1 ページを一時 PNG に書き出してパスを返す（OCR/OMR 用・約 200dpi）。"""
    img = render_page(path, index, scale)
    if dest is None:
        fd, dest = tempfile.mkstemp(suffix=".png", prefix="autoplaynotes_pdf_")
        os.close(fd)
    img.save(dest)
    return dest
