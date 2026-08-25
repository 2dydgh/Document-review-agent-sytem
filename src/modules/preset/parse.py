"""체크리스트 파일 → 항목 목록.

열 구성이 파일마다 다르고 한 파일 안에서도 바뀐다(실측: IS16 은 1쪽과 2쪽의
헤더가 다르다). 그래서 헤더 낱말로 추측하되, **못 맞히면 지어내지 않는다** —
틀린 추측을 조용히 등록하면 엉뚱한 항목으로 검토하게 된다.
"""
from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from .models import Criterion

# 헤더에 이 낱말이 있으면 그 역할로 본다. 왼쪽 열이 이긴다 —
# IS22 는 'Evaluation Item'(3)과 '평가 항목'(4)이 둘 다 걸리는데 앞의 것이 본문이다.
_ROLE_WORDS = {
    "text": ("항목", "내용", "item", "description"),
    "no": ("no", "id", "번호"),
    "group": ("종류", "위치", "구분", "characteristic"),
}

_MAX_HEADER_SCAN = 10  # 표 맨 위 제목 행을 건너뛰기 위한 탐색 범위


def _cell(row: list[str], i: int | None) -> str:
    if i is None or i < 0 or i >= len(row):
        return ""
    return str(row[i] or "").strip()


def guess_columns(header: list[str]) -> dict[str, int | None]:
    """헤더 → {역할: 열 인덱스}. 못 맞힌 역할은 None.

    한 열이 두 역할을 겸하지 않는다. note 는 낱말로 찾지 않고 **마지막 미배정
    열**을 준다 — IS16 은 '적용 문서', IS22 는 '평가 관점'이 거기 온다.
    """
    lowered = [str(h or "").strip().lower() for h in header]
    out: dict[str, int | None] = {"no": None, "text": None,
                                  "group": None, "note": None}
    taken: set[int] = set()
    for role in ("text", "no", "group"):
        for i, h in enumerate(lowered):
            if i in taken or not h:
                continue
            if any(w in h for w in _ROLE_WORDS[role]):
                out[role] = i
                taken.add(i)
                break
    leftover = [i for i in range(len(header)) if i not in taken]
    out["note"] = leftover[-1] if leftover else None
    return out


def find_header(rows: list[list[str]]) -> int | None:
    """역할 낱말이 가장 많이 맞는 행. 동점이면 앞선 행. 하나도 없으면 None.

    표 맨 위에 제목 행이 붙어 있는 일이 흔하다(실측: IS16 1쪽의 'PDF 검토').
    """
    best, best_score = None, 0
    for i, row in enumerate(rows[:_MAX_HEADER_SCAN]):
        cols = guess_columns(list(row))
        score = sum(1 for r in ("text", "no", "group") if cols[r] is not None)
        if score > best_score:
            best, best_score = i, score
    return best


def _has_own_header(rows: list[list[str]]) -> bool:
    """이 표가 자기 헤더를 갖고 있나 = 어느 행에서 '항목 내용' 열을 찾을 수 있나.

    항목 열(항목/내용/item/description)을 못 찾으면 자기를 설명하는 헤더가
    없는 것이다. no/group 만으로는 안 본다 — 'PNS No.' 의 'No' 처럼 우연한
    매칭이 있어서(실측: IS16 3쪽) 그것까지 헤더로 치면 이어지는 표가 독립
    표로 오인된다. 항목 열은 그렇게 우연히 걸리지 않는다.
    """
    return any(guess_columns(list(row))["text"] is not None
               for row in rows[:_MAX_HEADER_SCAN])


def _width(rows: list[list[str]]) -> int:
    return max((len(r) for r in rows), default=0)


def _merge_continuations(tables: list["Table"]) -> list["Table"]:
    """쪽을 넘으며 쪼개진 표를 다시 잇는다.

    PDF 는 표가 쪽 경계를 넘으면 쪽마다 따로 뽑는다. 이어지는 쪽은 헤더가
    다시 안 찍혀서(실측: IS16 3쪽) 항목 열을 못 맞히고 항목이 통째로 날아간다.
    자기 헤더가 없고 열 수가 앞 표와 같으면 앞 표의 이어짐으로 보고 행을 붙인다.

    헤더가 있는 표는 새 체크리스트다 — IS16 1쪽(PDF검토)과 2쪽(내부검토)은
    각자 헤더가 있어 따로 남고, 3쪽만 2쪽에 붙는다. 열 수가 다르면 붙이지
    않는다: 엉뚱한 표에 이으면 열이 어긋나 데이터가 뒤섞인다.
    """
    out: list[Table] = []
    for t in tables:
        if out and not _has_own_header(t.rows) and _width(t.rows) == _width(out[-1].rows):
            out[-1].rows.extend(t.rows)
        else:
            out.append(t)
    return out


def build_items(rows: list[list[str]], header_row: int,
                columns: dict[str, int | None]) -> list[Criterion]:
    """헤더 **아래** 행들을 항목으로. 내용이 빈 행은 버린다.

    헤더 위의 행(제목·머리말)은 항목이 아니므로 통째로 건너뛴다.
    """
    items: list[Criterion] = []
    for row in rows[header_row + 1:]:
        row = list(row)
        text = _cell(row, columns.get("text"))
        if not text:
            continue  # 빈 행·구분선. 내용 없이는 체크할 것이 없다.
        items.append(Criterion(
            no=_cell(row, columns.get("no")),
            text=text,
            group=_cell(row, columns.get("group")),
            note=_cell(row, columns.get("note")),
            raw=[str(c or "") for c in row],
        ))
    return items


def read_csv(data: bytes) -> list[list[str]]:
    """CSV → 행 목록. 엑셀이 붙이는 BOM 을 걷어낸다."""
    text = data.decode("utf-8-sig", errors="replace")
    return [list(r) for r in csv.reader(io.StringIO(text))]


class UnsupportedChecklistFormat(Exception):
    """체크리스트로 읽을 수 없는 형식."""


@dataclass
class Table:
    """파일에서 뽑은 표 하나. label 은 검토자가 고를 때 보는 이름이다."""
    label: str
    rows: list[list[str]] = field(default_factory=list)


_XL = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_XL_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_R = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _xlsx_strings(archive: zipfile.ZipFile) -> list[str]:
    """공유 문자열 표. 없는 파일도 있다(전부 inlineStr 인 경우)."""
    try:
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    except (KeyError, ET.ParseError):
        return []
    return ["".join(t.text or "" for t in si.iter(f"{_XL}t"))
            for si in root.iter(f"{_XL}si")]


def _col_index(ref: str | None) -> int | None:
    """셀 참조(예: "C2")의 열 알파벳 부분 → 0-based 인덱스. 못 읽으면 None.

    "AA"처럼 두 글자 이상인 열도 26진법으로 계산한다(A=1 ... Z=26, AA=27).
    """
    if not ref:
        return None
    letters = "".join(ch for ch in ref if ch.isalpha())
    if not letters:
        return None
    idx = 0
    for ch in letters.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _cell_value(c: ET.Element, strings: list[str]) -> str:
    """<c> 하나의 값. inlineStr·공유문자열·직접값을 구분한다."""
    if c.get("t") == "inlineStr":
        node = c.find(f"{_XL}is")
        return ("".join(t.text or "" for t in node.iter(f"{_XL}t"))
                if node is not None else "")
    v = c.find(f"{_XL}v")
    if v is None:
        return ""
    if c.get("t") == "s":
        try:
            return strings[int(v.text)]
        except (ValueError, IndexError):
            return ""
    return v.text or ""


def _row_cells(row: ET.Element, strings: list[str]) -> list[str]:
    """<row> 하나 → 셀 값 목록. r 속성으로 실제 열 위치를 복원한다.

    엑셀은 빈 셀을 XML 에 아예 쓰지 않는다(B2 가 비면 <c r="B2">가 통째로
    없다). 등장 순서대로만 채우면 그 뒤 값들이 전부 왼쪽으로 밀려 엉뚱한
    열(항목/구분/비고)에 들어간다 — 그래서 r 속성의 열 문자를 인덱스로 써서
    제자리에 놓는다. r 속성이 없는 비정상 파일은 이전 위치 다음 칸으로
    넘어가는 것으로 대체한다.
    """
    cells: list[str] = []
    next_idx = 0
    for c in row.iter(f"{_XL}c"):
        idx = _col_index(c.get("r"))
        if idx is None:
            idx = next_idx
        while len(cells) < idx:
            cells.append("")
        value = _cell_value(c, strings)
        if idx < len(cells):
            cells[idx] = value
        else:
            cells.append(value)
        next_idx = idx + 1
    return cells


def _xlsx_tables(data: bytes) -> list[Table]:
    """시트 하나를 표 하나로. 라벨은 시트 이름이다.

    openpyxl 을 쓰지 않는다(미설치). docx.py·hwpx.py 와 같이 zipfile+XML 로 읽는다.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise UnsupportedChecklistFormat(
            "엑셀 파일이 아닌 것 같습니다 (ZIP이 아님)") from exc

    with archive:
        try:
            rels = {r.get("Id"): r.get("Target") for r in
                    ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
                    .iter(f"{_PKG_R}Relationship")}
            strings = _xlsx_strings(archive)
            book = ET.fromstring(archive.read("xl/workbook.xml"))
        except (KeyError, ET.ParseError) as exc:
            raise UnsupportedChecklistFormat(
                "엑셀 파일 구조를 읽을 수 없습니다 (workbook.xml 없음/손상)"
            ) from exc

        tables: list[Table] = []
        for sheet in book.iter(f"{_XL}sheet"):
            target = rels.get(sheet.get(f"{_XL_R}id"), "")
            name = "xl/" + target.lstrip("/").removeprefix("xl/")
            try:
                grid = ET.fromstring(archive.read(name))
            except (KeyError, ET.ParseError):
                continue
            rows: list[list[str]] = []
            for row in grid.iter(f"{_XL}row"):
                cells = _row_cells(row, strings)
                if any(x.strip() for x in cells):
                    rows.append(cells)
            if rows:
                tables.append(Table(label=sheet.get("name") or "", rows=rows))
        return tables


def _pdf_tables(data: bytes) -> list[Table]:
    import pdfplumber  # noqa: PLC0415 — 임포트 비용이 커서 여기서 연다

    tables: list[Table] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for pno, page in enumerate(pdf.pages, 1):
            for n, grid in enumerate(page.extract_tables(), 1):
                rows = [[(c or "").strip() for c in row] for row in grid]
                rows = [r for r in rows if any(r)]
                if not rows:
                    continue
                # 쪽마다 헤더가 다를 수 있어(실측: IS16) 첫 행을 라벨에 넣는다.
                head = " | ".join(x for x in rows[0] if x)[:40]
                suffix = f"-{n}" if n > 1 else ""
                tables.append(Table(label=f"{pno}쪽{suffix} · {head}", rows=rows))
    # 쪽을 넘으며 쪼개진 표를 다시 잇는다(IS16 3쪽 → 2쪽). xlsx 는 시트가 논리적
    # 단위라 여기 해당 없다 — PDF 쪽 경계에서만 생기는 문제다.
    return _merge_continuations(tables)


def extract_tables(filename: str, data: bytes) -> list[Table]:
    """업로드 파일 → 표 목록. 지원하지 않는 확장자는 거절한다."""
    ext = Path(filename or "").suffix.lower()
    if ext == ".csv":
        rows = [r for r in read_csv(data) if any(str(c).strip() for c in r)]
        return [Table(label="csv", rows=rows)] if rows else []
    if ext == ".xlsx":
        return _xlsx_tables(data)
    if ext == ".pdf":
        return _pdf_tables(data)
    raise UnsupportedChecklistFormat(
        f"체크리스트로 읽을 수 없는 형식입니다: {ext or '(확장자 없음)'} "
        "— .pdf, .xlsx, .csv 만 됩니다.")
