"""数字譜スクリーンショットの OCR 取り込み。

Windows 10/11 に内蔵の OCR エンジン (Windows.Media.Ocr) を
Windows PowerShell 経由で呼び出すため、追加の pip 依存なしで動く。
SNS 等で共有される「数字を並べただけの簡略数字譜」画像を対象とし、
認識結果は数字譜として妥当なトークンだけに整形して返す
（正式な简谱のオクターブ点・音長線など空間配置の解釈は対象外）。
"""

from __future__ import annotations

import base64
import re
import shutil
import subprocess
import sys

_POWERSHELL = "powershell.exe"  # Windows PowerShell 5.x（WinRT 呼び出しに必要）
_CREATE_NO_WINDOW = 0x08000000

# 数字譜1行の中で意味を持つトークン。
#   音:   [#b]?[1-7] にオクターブ記号 '/, が続き、+ で和音、:拍 で音長
#   休符: 0[:拍]   伸ばし: -[:拍]   小節線: |
_TOKEN = re.compile(
    r"[#b]?[1-7][',]*(?:\+[#b]?[1-7][',]*)*(?::\d+(?:\.\d+)?)?"
    r"|0(?::\d+(?:\.\d+)?)?"
    r"|-(?::\d+(?:\.\d+)?)?"
    r"|\|"
)

# OCR が返しがちな全角・類似記号を数字譜の文字へ寄せる。
_NORMALIZE = str.maketrans(
    {
        "０": "0", "１": "1", "２": "2", "３": "3", "４": "4",
        "５": "5", "６": "6", "７": "7", "８": "8", "９": "9",
        "＃": "#", "♯": "#", "♭": "b", "ｂ": "b",
        # 「，」「、」は列挙の区切りに使われるためオクターブ記号 "," へは寄せない
        "＋": "+", "｜": "|", "：": ":", "．": ".",
        "’": "'", "‘": "'", "`": "'", "´": "'", "′": "'",
        "ー": "-", "―": "-", "—": "-", "–": "-", "−": "-", "‐": "-",
        "〇": "0", "○": "0", "◯": "0",
        "l": "1", "I": "1", "O": "0", "o": "0",
    }
)


# OCR（特に日本語エンジン）は記号を独立した単語に分割しがちなので、
# トークン化の前に音へ再結合する。カンマは「列挙の区切り」の可能性が
# あるため再結合しない（オクターブ下げと区別できない）。
_REJOIN_ACCIDENTAL = re.compile(r"([#b])\s+(?=[0-7])")   # "# 1"  -> "#1"
_REJOIN_CHORD = re.compile(r"\s*\+\s*")                   # "1 + 3" -> "1+3"
_REJOIN_DURATION = re.compile(r"\s*:\s*")                 # "1 : 2" -> "1:2"
_REJOIN_OCTAVE_UP = re.compile(r"([0-7'])\s+(?=')")       # "5 '"  -> "5'"


class OcrError(RuntimeError):
    """OCR の実行に失敗したときの例外。"""


def is_available() -> bool:
    """この環境で Windows OCR を呼び出せるか。"""
    return sys.platform == "win32" and shutil.which(_POWERSHELL) is not None


# --- 整形（純ロジック・OS 非依存） -----------------------------------------

def clean_number_text(raw: str) -> str:
    """OCR の生テキストから数字譜トークンだけを取り出して整形する。

    "1234" のような数字の連続は 1 音ずつに分割される（この記譜に
    複数桁の音は存在しないため）。数字譜として解釈できない文字は捨てる。
    行の区切り（フレーズ構造）は保つ。
    """
    lines: list[str] = []
    for line in raw.splitlines():
        line = line.translate(_NORMALIZE)
        line = _REJOIN_ACCIDENTAL.sub(r"\1", line)
        line = _REJOIN_CHORD.sub("+", line)
        line = _REJOIN_DURATION.sub(":", line)
        line = _REJOIN_OCTAVE_UP.sub(r"\1", line)
        tokens = _TOKEN.findall(line)
        if tokens:
            lines.append(" ".join(tokens))
    return "\n".join(lines)


def _rows_to_text(entries: list[tuple[int, int, int, str]]) -> str:
    """(y, x, 高さ, テキスト) の OCR 行を視覚的な行にまとめ直す。

    OCR は同じ段でも離れた語句を別の行として返すことがあるため、
    y が近い（行の高さの半分以内の）ものを同じ段として x 順に並べる。
    """
    rows: list[tuple[int, int, list[tuple[int, str]]]] = []  # (基準y, 高さ, [(x, text)])
    for y, x, height, text in sorted(entries):
        height = max(height, 1)
        if rows and abs(y - rows[-1][0]) <= max(rows[-1][1], height) // 2:
            rows[-1][2].append((x, text))
        else:
            rows.append((y, height, [(x, text)]))
    return "\n".join(
        " ".join(text for _x, text in sorted(cells)) for _y, _h, cells in rows
    )


# --- PowerShell 呼び出し ----------------------------------------------------

_OCR_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[void][Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics,ContentType=WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapTransform,Windows.Graphics,ContentType=WindowsRuntime]
[void][Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]
function Await($op, $resultType) {
    $task = $asTask.MakeGenericMethod($resultType).Invoke($null, @($op))
    $task.Wait(-1) | Out-Null
    $task.Result
}
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
    foreach ($lang in [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages) {
        $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
        if ($null -ne $engine) { break }
    }
}
if ($null -eq $engine) { exit 2 }
$file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync('__IMAGE_PATH__')) ([Windows.Storage.StorageFile])
$stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$maxDim = [double][Windows.Media.Ocr.OcrEngine]::MaxImageDimension
$w = [double]$decoder.PixelWidth
$h = [double]$decoder.PixelHeight
$scale = 1.0
if (($w -gt $maxDim) -or ($h -gt $maxDim)) { $scale = [Math]::Min($maxDim / $w, $maxDim / $h) }
$tf = [Windows.Graphics.Imaging.BitmapTransform]::new()
$tf.ScaledWidth = [uint32][Math]::Max(1, [Math]::Floor($w * $scale))
$tf.ScaledHeight = [uint32][Math]::Max(1, [Math]::Floor($h * $scale))
$bitmap = Await ($decoder.GetSoftwareBitmapAsync(
    [Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,
    [Windows.Graphics.Imaging.BitmapAlphaMode]::Premultiplied,
    $tf,
    [Windows.Graphics.Imaging.ExifOrientationMode]::RespectExifOrientation,
    [Windows.Graphics.Imaging.ColorManagementMode]::DoNotColorManage
)) ([Windows.Graphics.Imaging.SoftwareBitmap])
$result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$sb = [System.Text.StringBuilder]::new()
foreach ($line in $result.Lines) {
    $x = [double]::MaxValue
    $y = [double]::MaxValue
    $bottom = 0.0
    $words = @()
    foreach ($word in $line.Words) {
        $r = $word.BoundingRect
        if ($r.X -lt $x) { $x = $r.X }
        if ($r.Y -lt $y) { $y = $r.Y }
        if (($r.Y + $r.Height) -gt $bottom) { $bottom = $r.Y + $r.Height }
        $words += $word.Text
    }
    if ($words.Count -eq 0) { continue }
    $text = $words -join ' '
    [void]$sb.AppendLine(("{0}`t{1}`t{2}`t{3}" -f
        [int][Math]::Round($y), [int][Math]::Round($x),
        [int][Math]::Round($bottom - $y), $text))
}
Write-Output ([Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($sb.ToString())))
"""

_CLIPBOARD_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$img = [System.Windows.Forms.Clipboard]::GetImage()
if ($null -eq $img) { exit 3 }
$img.Save('__DEST_PATH__', [System.Drawing.Imaging.ImageFormat]::Png)
"""


def _quote_ps(path: str) -> str:
    """PowerShell の単一引用符文字列に埋め込めるようエスケープする。"""
    return path.replace("'", "''")


def _run_ps(script: str, timeout: float) -> subprocess.CompletedProcess:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    try:
        return subprocess.run(
            [_POWERSHELL, "-NoProfile", "-NonInteractive", "-Sta",
             "-ExecutionPolicy", "Bypass", "-EncodedCommand", encoded],
            capture_output=True,
            timeout=timeout,
            creationflags=_CREATE_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise OcrError("PowerShell が見つかりません。") from exc
    except subprocess.TimeoutExpired as exc:
        raise OcrError("OCR がタイムアウトしました。") from exc


def ocr_image(path: str, timeout: float = 60.0) -> str:
    """画像ファイルを Windows OCR にかけ、生テキストを返す（上の行から順）。

    整形前のテキストを返すので、数字譜化には clean_number_text() を通す。
    """
    if not is_available():
        raise OcrError("この機能は Windows でのみ利用できます。")
    script = _OCR_SCRIPT.replace("__IMAGE_PATH__", _quote_ps(path))
    proc = _run_ps(script, timeout)
    if proc.returncode == 2:
        raise OcrError(
            "OCR 言語パックが見つかりません。Windows の設定 → 時刻と言語 → "
            "言語と地域 から言語機能（OCR）を追加してください。"
        )
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise OcrError(f"画像の認識に失敗しました。{detail[:200]}")

    payload = proc.stdout.decode("ascii", errors="ignore").strip()
    if not payload:
        return ""
    try:
        decoded = base64.b64decode(payload).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise OcrError("OCR 結果の読み取りに失敗しました。") from exc

    entries: list[tuple[int, int, int, str]] = []
    for line in decoded.splitlines():
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        try:
            entries.append((int(parts[0]), int(parts[1]), int(parts[2]), parts[3]))
        except ValueError:
            continue
    return _rows_to_text(entries)


def grab_clipboard_image(dest_path: str, timeout: float = 30.0) -> bool:
    """クリップボードの画像を PNG として保存する。画像が無ければ False。"""
    if not is_available():
        raise OcrError("この機能は Windows でのみ利用できます。")
    script = _CLIPBOARD_SCRIPT.replace("__DEST_PATH__", _quote_ps(dest_path))
    proc = _run_ps(script, timeout)
    if proc.returncode == 3:
        return False
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()
        raise OcrError(f"クリップボード画像の取得に失敗しました。{detail[:200]}")
    return True
