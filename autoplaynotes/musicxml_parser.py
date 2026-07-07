"""MusicXML ファイルの読み込み（.musicxml / .xml / .mxl）。標準ライブラリのみで動く。

MusicXML は楽譜デジタル化の事実上の共通形式で、OMR ソフト（oemer, Audiveris,
PlayScore 等）や楽譜エディタ（MuseScore 等）の出力を取り込む入口になる。
midi_parser と同じ「inspect でパート一覧 → build_score で選択パートを統合」
の流れに合わせ、GUI からは同じトラック選択ダイアログで扱えるようにする。

対応: score-partwise / 圧縮 .mxl / 和音(chord) / タイ(tie) / 複声部(backup・forward)
非対応: 装飾音(grace)は無視、unpitched（打楽器）は音にしない
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass

from .keymap import note_name
from .model import NoteEvent, Score

EXTENSIONS = (".musicxml", ".xml", ".mxl")

# 和音とみなす同時刻の許容誤差（拍）
_MERGE_WINDOW_BEATS = 0.02

_STEP_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def is_musicxml_path(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in EXTENSIONS


@dataclass
class XmlPart:
    """MusicXML 内の 1 パート。MidiTrackDialog と互換のインターフェースを持つ。"""

    key: tuple[int, int]  # (パート番号, 0) 選択のキー
    part_id: str
    name: str
    note_count: int
    low: int
    high: int
    unpitched: bool  # 打楽器（音高なし）パート

    @property
    def is_drum(self) -> bool:
        return self.unpitched

    def label(self) -> str:
        parts = [f"Part{self.key[0] + 1}"]
        if self.name:
            parts.append(f'"{self.name}"')
        if self.is_drum:
            parts.append("[打楽器]")
        rng = f"{note_name(self.low)}–{note_name(self.high)}" if self.note_count else "-"
        return f"{' '.join(parts)}   音数 {self.note_count} / 音域 {rng}"


@dataclass
class XmlInfo:
    """MidiInfo と互換のインターフェース（parts / tempo_bpm / title）。"""

    parts: list[XmlPart]
    tempo_bpm: float
    title: str


# --- 音符 1 個の中間表現 ------------------------------------------------------
@dataclass
class _RawNote:
    start: float          # 絶対位置（拍）
    duration: float       # 長さ（拍）
    midi: int
    tie_start: bool
    tie_stop: bool


# --- XML 読み込み -------------------------------------------------------------
def _load_root(path: str) -> ET.Element:
    if path.lower().endswith(".mxl"):
        data = _read_mxl(path)
        root = ET.fromstring(data)
    else:
        root = ET.parse(path).getroot()
    _strip_namespaces(root)
    if root.tag == "score-timewise":
        raise ValueError(
            "score-timewise 形式の MusicXML は未対応です。"
            "MuseScore 等で score-partwise 形式に保存し直してください。"
        )
    if root.tag != "score-partwise":
        raise ValueError(f"MusicXML として解釈できません（ルート要素: {root.tag}）")
    return root


def _read_mxl(path: str) -> bytes:
    """圧縮 MusicXML (.mxl) から本体の XML を取り出す。"""
    with zipfile.ZipFile(path) as zf:
        try:
            container = ET.fromstring(zf.read("META-INF/container.xml"))
            _strip_namespaces(container)
            rootfile = container.find(".//rootfile")
            if rootfile is not None:
                full_path = rootfile.get("full-path")
                if full_path:
                    return zf.read(full_path)
        except (KeyError, ET.ParseError):
            pass
        for name in zf.namelist():  # フォールバック: 最初の XML 実体
            if name.startswith("META-INF/"):
                continue
            if name.lower().endswith((".xml", ".musicxml")):
                return zf.read(name)
    raise ValueError("mxl ファイル内に楽譜データが見つかりません。")


def _strip_namespaces(root: ET.Element) -> None:
    for el in root.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


# --- パート解析（純ロジック） -------------------------------------------------
def _pitch_to_midi(pitch: ET.Element) -> int:
    step = (pitch.findtext("step") or "C").strip().upper()
    octave = int(float(pitch.findtext("octave") or "4"))
    alter_text = pitch.findtext("alter")
    alter = int(round(float(alter_text))) if alter_text else 0
    midi = (octave + 1) * 12 + _STEP_PC.get(step, 0) + alter
    return max(0, min(127, midi))


def _extract_part(part_el: ET.Element) -> tuple[list[_RawNote], bool]:
    """1 パートの音符列（絶対拍）を取り出す。戻り値: (音符列, 打楽器パートか)。"""
    divisions = 1.0
    base = 0.0  # 現在の小節の開始位置（拍）
    notes: list[_RawNote] = []
    has_pitched = False
    has_unpitched = False

    for measure in part_el.findall("measure"):
        pos = 0.0       # 小節内の現在位置（拍）
        max_pos = 0.0   # この小節で到達した最大位置＝小節の長さ
        last_onset = 0.0

        for el in measure:
            tag = el.tag
            if tag == "attributes":
                d = el.findtext("divisions")
                if d:
                    divisions = float(d) or 1.0
            elif tag in ("backup", "forward"):
                d = el.findtext("duration")
                beats = float(d) / divisions if d else 0.0
                pos = max(0.0, pos - beats if tag == "backup" else pos + beats)
                max_pos = max(max_pos, pos)
            elif tag == "note":
                if el.find("grace") is not None:
                    continue  # 装飾音は長さを持たないため無視
                d = el.findtext("duration")
                beats = float(d) / divisions if d else 0.0
                is_chord = el.find("chord") is not None
                onset = last_onset if is_chord else pos

                pitch = el.find("pitch")
                if pitch is not None:
                    has_pitched = True
                    ties = {t.get("type") for t in el.findall("tie")}
                    notes.append(
                        _RawNote(
                            start=base + onset,
                            duration=beats,
                            midi=_pitch_to_midi(pitch),
                            tie_start="start" in ties,
                            tie_stop="stop" in ties,
                        )
                    )
                elif el.find("unpitched") is not None:
                    has_unpitched = True

                if not is_chord:
                    last_onset = pos
                    pos += beats
                    max_pos = max(max_pos, pos)

        base += max_pos

    return notes, (has_unpitched and not has_pitched)


def _merge_ties(notes: list[_RawNote]) -> list[_RawNote]:
    """タイで結ばれた同音を 1 つの長い音へ統合する。"""
    result: list[_RawNote] = []
    open_notes: dict[int, _RawNote] = {}  # midi -> 伸長中の音（result 内を参照）
    for note in sorted(notes, key=lambda n: n.start):
        opened = open_notes.get(note.midi)
        if (
            note.tie_stop
            and opened is not None
            and abs(opened.start + opened.duration - note.start) < _MERGE_WINDOW_BEATS
        ):
            opened.duration += note.duration
            if not note.tie_start:
                del open_notes[note.midi]
            continue
        merged = _RawNote(note.start, note.duration, note.midi, note.tie_start, note.tie_stop)
        result.append(merged)
        if note.tie_start:
            open_notes[note.midi] = merged
    return result


def _first_tempo(root: ET.Element) -> float:
    for sound in root.iter("sound"):
        tempo = sound.get("tempo")
        if tempo:
            try:
                value = float(tempo)
            except ValueError:
                continue
            if value > 0:
                return value
    for per_minute in root.iter("per-minute"):
        if per_minute.text:
            try:
                value = float(per_minute.text)
            except ValueError:
                continue
            if value > 0:
                return value
    return 120.0


def _title(root: ET.Element, path: str) -> str:
    for xpath in ("work/work-title", "movement-title"):
        text = root.findtext(xpath)
        if text and text.strip():
            return text.strip()
    return os.path.basename(path)


def _all_parts(root: ET.Element) -> list[tuple[str, ET.Element]]:
    return [(part.get("id") or f"P{i + 1}", part) for i, part in enumerate(root.findall("part"))]


def _part_names(root: ET.Element) -> dict[str, str]:
    names: dict[str, str] = {}
    for score_part in root.iter("score-part"):
        part_id = score_part.get("id")
        if part_id:
            names[part_id] = (score_part.findtext("part-name") or "").strip()
    return names


# --- 公開 API -----------------------------------------------------------------
def inspect_musicxml(path: str) -> XmlInfo:
    """MusicXML の中身を解析し、パート一覧を返す。"""
    root = _load_root(path)
    names = _part_names(root)
    parts: list[XmlPart] = []
    for index, (part_id, part_el) in enumerate(_all_parts(root)):
        notes, unpitched = _extract_part(part_el)
        notes = _merge_ties(notes)
        pitches = [n.midi for n in notes]
        parts.append(
            XmlPart(
                key=(index, 0),
                part_id=part_id,
                name=names.get(part_id, ""),
                note_count=len(pitches),
                low=min(pitches) if pitches else 0,
                high=max(pitches) if pitches else 0,
                unpitched=unpitched,
            )
        )
    return XmlInfo(parts=parts, tempo_bpm=_first_tempo(root), title=_title(root, path))


def build_score(
    path: str,
    selected_keys: set[tuple[int, int]] | None = None,
    monophonic: bool = False,
    octave_shift: int = 0,
    include_drums: bool = False,
) -> Score:
    """選択したパートを 1 本の時間軸へ統合して Score を作る（midi_parser と同じ流儀）。"""
    root = _load_root(path)
    collected: list[_RawNote] = []
    for index, (_part_id, part_el) in enumerate(_all_parts(root)):
        notes, unpitched = _extract_part(part_el)
        if selected_keys is not None:
            if (index, 0) not in selected_keys:
                continue
        elif unpitched and not include_drums:
            continue
        collected.extend(_merge_ties(notes))

    tempo = _first_tempo(root)
    title = _title(root, path)
    if not collected:
        return Score(tempo_bpm=tempo, events=[], title=title)

    if octave_shift:
        for note in collected:
            note.midi = max(0, min(127, note.midi + 12 * octave_shift))

    # 同時刻（許容誤差内）の音を 1 つの NoteEvent（和音）へ
    collected.sort(key=lambda n: n.start)
    groups: list[list[_RawNote]] = []
    for note in collected:
        if groups and note.start - groups[-1][0].start <= _MERGE_WINDOW_BEATS:
            groups[-1].append(note)
        else:
            groups.append([note])

    origin = groups[0][0].start  # 先頭の無音をつめる
    events: list[NoteEvent] = []
    for group in groups:
        if monophonic:
            top = max(group, key=lambda n: n.midi)
            midis: tuple[int, ...] = (top.midi,)
            duration = top.duration
        else:
            midis = tuple(sorted({n.midi for n in group}))
            duration = max(n.duration for n in group)
        events.append(
            NoteEvent(
                start_beat=group[0].start - origin,
                duration_beat=max(duration, 0.05),
                midi_notes=midis,
            )
        )
    return Score(tempo_bpm=tempo, events=events, title=title)
