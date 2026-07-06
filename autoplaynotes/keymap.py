"""音階（MIDI ノート番号）とキーボードキーの対応（マッピング）。

- MIDI ノート番号 60 = 中央のド (C4)
- マッピングは「MIDI ノート -> キー文字」の辞書で表現する
- 音域外の音は設定に応じてオクターブ移調 / 最寄り音へ丸め / 無視 する
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

OutOfRange = Literal["transpose", "nearest", "skip"]

# 音名 -> 音高クラス（半音）
PITCH_CLASS: dict[str, int] = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_PC_TO_NAME = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def note_name(midi: int) -> str:
    """MIDI ノート番号を 'C4' 形式の音名へ変換する。"""
    octave = midi // 12 - 1
    return f"{_PC_TO_NAME[midi % 12]}{octave}"


def name_to_midi(name: str, default_octave: int = 4) -> int:
    """'C4' / 'D#5' / 'Eb3' などの音名を MIDI ノート番号へ変換する。"""
    s = name.strip()
    if not s:
        raise ValueError("空の音名です")
    letter = s[0].upper()
    if letter not in PITCH_CLASS:
        raise ValueError(f"音名を認識できません: '{name}'")
    pc = PITCH_CLASS[letter]
    idx = 1
    if idx < len(s) and s[idx] in "#b":
        pc += 1 if s[idx] == "#" else -1
        idx += 1
    octave_part = s[idx:]
    if octave_part:
        try:
            octave = int(octave_part)
        except ValueError as exc:
            raise ValueError(f"音名を認識できません: '{name}'") from exc
    else:
        octave = default_octave
    return (octave + 1) * 12 + pc


@dataclass
class KeyMapping:
    """1 つのマッピング設定。"""

    name: str
    note_to_key: dict[int, str]
    out_of_range: OutOfRange = "transpose"

    def resolve(self, midi: int) -> str | None:
        """MIDI ノートを演奏キーへ解決する。演奏不能なら None。"""
        if midi in self.note_to_key:
            return self.note_to_key[midi]
        if not self.note_to_key:
            return None

        lo = min(self.note_to_key)
        hi = max(self.note_to_key)

        # まずオクターブ移調で音域内へ入れる
        candidate = midi
        while candidate < lo:
            candidate += 12
        while candidate > hi:
            candidate -= 12
        if candidate in self.note_to_key:
            return self.note_to_key[candidate]

        # スケール外（例: C メジャー鍵盤に対する #/b）の扱い
        if self.out_of_range == "nearest":
            nearest = min(self.note_to_key, key=lambda n: abs(n - candidate))
            return self.note_to_key[nearest]
        return None

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "out_of_range": self.out_of_range,
            "note_to_key": {str(k): v for k, v in sorted(self.note_to_key.items())},
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "KeyMapping":
        raw = data.get("note_to_key", {})
        if not isinstance(raw, dict):
            raise ValueError("note_to_key が不正です")
        note_to_key = {int(k): str(v) for k, v in raw.items()}
        out_of_range = str(data.get("out_of_range", "transpose"))
        if out_of_range not in ("transpose", "nearest", "skip"):
            out_of_range = "transpose"
        name = str(data.get("name", "カスタム"))
        return cls(name=name, note_to_key=note_to_key, out_of_range=out_of_range)  # type: ignore[arg-type]

    def as_text(self) -> str:
        """マッピング編集用のテキスト表現（'C4 = z' 形式）を返す。"""
        lines = [f"{note_name(n)} = {k}" for n, k in sorted(self.note_to_key.items())]
        return "\n".join(lines)

    @classmethod
    def from_text(cls, text: str, name: str = "カスタム", out_of_range: OutOfRange = "transpose") -> "KeyMapping":
        """'C4 = z' 形式のテキストからマッピングを構築する。"""
        note_to_key: dict[int, str] = {}
        for lineno, line in enumerate(text.splitlines(), start=1):
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            if "=" not in s:
                raise ValueError(f"{lineno} 行目: '音名 = キー' の形式で書いてください -> {line!r}")
            left, right = s.split("=", 1)
            midi = name_to_midi(left.strip())
            key = right.strip()
            if not key:
                raise ValueError(f"{lineno} 行目: キーが空です")
            note_to_key[midi] = key
        return cls(name=name, note_to_key=note_to_key, out_of_range=out_of_range)


def _build(rows: list[tuple[str, int, list[int]]], name: str, out_of_range: OutOfRange) -> KeyMapping:
    note_to_key: dict[int, str] = {}
    for keys, octave, scale in rows:
        base = (octave + 1) * 12
        for key, semitone in zip(keys, scale):
            note_to_key[base + semitone] = key
    return KeyMapping(name=name, note_to_key=note_to_key, out_of_range=out_of_range)


# --- 同梱プリセット ------------------------------------------------------------
_MAJOR = [0, 2, 4, 5, 7, 9, 11]  # C D E F G A B
_PENTA = [0, 2, 4, 7, 9]  # C D E G A


def diatonic_mapping() -> KeyMapping:
    """全音階（白鍵のみ）3 オクターブ x 7 音 = 21 鍵（C メジャー）。

    低音 ZXCVBNM / 中音 ASDFGHJ / 高音 QWERTYU。黒鍵なしの簡易配列。
    """
    rows = [
        ("ZXCVBNM", 3, _MAJOR),
        ("ASDFGHJ", 4, _MAJOR),
        ("QWERTYU", 5, _MAJOR),
    ]
    return _build(rows, "全音階 (白鍵のみ・21鍵)", "transpose")


def chromatic_mapping() -> KeyMapping:
    """クロマチック（黒鍵あり）フル配列（3 オクターブ・半音対応・36鍵）。

    実ピアノ同様「白鍵の間の上に黒鍵」を置く配置。中音の白鍵が下段 ZXCVBNM、
    その上の SDGHJ が黒鍵。一般的なキーボード・ピアノ配列に準拠。

    記号キー（低音）は配列やロケール（JIS/US）で物理位置が異なる場合があるため、
    対象アプリに合わせて「割り当てを編集...」で調整してください。
    黒鍵が不要なら diatonic プリセット（白鍵のみ）が使えます。
    """
    # {オクターブ: {半音: キー}}  半音 0=C,1=C#,2=D,3=D#,4=E,5=F,6=F#,7=G,8=G#,9=A,10=A#,11=B
    octaves: dict[int, dict[int, str]] = {
        5: {0: "Q", 2: "W", 4: "E", 5: "R", 7: "T", 9: "Y", 11: "U",
            1: "2", 3: "3", 6: "5", 8: "6", 10: "7"},
        4: {0: "Z", 2: "X", 4: "C", 5: "V", 7: "B", 9: "N", 11: "M",
            1: "S", 3: "D", 6: "G", 8: "H", 10: "J"},
        3: {0: ",", 2: ".", 4: "/", 5: "O", 7: "P", 9: "[", 11: "]",
            1: "L", 3: ";", 6: "0", 8: "-", 10: "="},
    }
    note_to_key: dict[int, str] = {}
    for octave, semitones in octaves.items():
        base = (octave + 1) * 12
        for semitone, key in semitones.items():
            note_to_key[base + semitone] = key
    return KeyMapping("クロマチック (黒鍵あり・36鍵)", note_to_key, out_of_range="transpose")


def pentatonic_mapping() -> KeyMapping:
    """ペンタトニック 3 x 5 = 15 鍵。"""
    rows = [
        ("NM,./", 3, _PENTA),
        ("HJKL;", 4, _PENTA),
        ("YUIOP", 5, _PENTA),
    ]
    return _build(rows, "ペンタトニック (15鍵)", "nearest")


def PRESETS() -> dict[str, KeyMapping]:
    """プリセット名 -> マッピング（毎回新しいインスタンスを返す）。"""
    return {
        "chromatic": chromatic_mapping(),
        "diatonic": diatonic_mapping(),
        "pentatonic": pentatonic_mapping(),
    }
