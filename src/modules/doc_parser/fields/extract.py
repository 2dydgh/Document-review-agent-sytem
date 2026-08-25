"""라벨 기반 필드 추출. 표에서 "이 라벨의 값"을 꺼낸다.

시험 산출물은 거의 전부 표다(실측: 검토기록서 11줄 중 10줄, 제출물확인증 30줄 중
29줄, 갑지 25줄 중 19줄). 그래서 "어느 칸이 라벨이고 값이 어디 있나"만 알면 된다.

표는 두 모양으로 온다:

    갑지 (세로)                        을지 머리표 (가로)
    | 기관명 | 한국소프트웨어시험연구소 |    | 의뢰번호 | 성적서번호 |
             ↑ at: right               | SST-26-999 | SST-26-999-C01 |
                                                    ↑ at: below

로더가 표를 `| 셀 | 셀 |` 한 줄로 내므로(docx.py·hwpx.py 규약) 그 줄만 읽으면 된다.
서식 레이어(머릿말·꼬리말·글꼴)는 아직 없다 — source 가 header·footer 인 필드는
찾지 못한 것으로 돌려준다. 파서가 못 주는 정보를 있는 척하지 않는다.

**추출과 검증은 다른 일이다.** 여기서는 값을 꺼내기만 한다. `pattern`·`required`·
`format` 은 FieldSpec 에 실려 오지만 판정은 검사기 몫이다 — 추출기가 판정까지 하면
"못 찾음"과 "형식이 틀림"이 한 자리에서 뭉개진다.
"""
from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from modules.shared import Anchor, Document

# 체크 기호는 문서마다 다르다 — md 가 "기호 종류는 무관"이라고 못박았다.
_UNCHECKED = "□☐○◯▢"
_CHECKED = "■☑▣●◉✔✓☒⊠"


@dataclass(frozen=True)
class FieldSpec:
    """필드 하나를 어디서 꺼내는지.

    labels 는 **후보 목록**이다. 같은 필드의 라벨이 문서마다 다르다(실측):
    `의뢰번호 :`(의뢰서·동의서) vs `의뢰 번호:`(제출물 확인증).
    """
    name: str
    # table | table_rows | table_cell | checkbox_group | header | footer
    source: str = "table"
    labels: tuple[str, ...] = ()
    at: str = "right"               # table: right | below
    options: tuple[str, ...] = ()   # checkbox_group: 선택지
    select: str = ""                # checkbox_group: "one"
    # table_rows: 머리행에서 찾을 열 이름들. **조합으로 표를 특정한다** —
    # "담당자" 하나로는 어느 표인지 모른다. key 는 그 행이 실재하는지 가르는
    # 열이고(비면 빈 양식 행), 안 주면 첫 열이다.
    columns: tuple[str, ...] = ()
    key: str = ""
    # table_cell 전용. columns 로 머리행을 찾고, 바로 아래 값 행에서 이 열의
    # 칸 하나를 낸다. key 가 어느 열인지 가리킨다(안 주면 첫 열).
    #
    # 라벨이 아예 없는 칸을 위한 어휘다. 실측(시험 계획서·설계서 결재란):
    #     | 의뢰번호   | 시험 실무자      | 기술 책임자      |
    #     | SST-26-999 |  | 2026. 01. 02. |  | 2026. 01. 02. |
    # 머리행 3칸 · 값 행 5칸이라 칸 번호로는 못 맞춘다. **빈 칸을 걷어내면
    # 1:1 로 맞는다** — 실측에서 나온 규칙이지 어림짐작이 아니다.
    # 검사기가 읽는다. 이 열이 빈 행은 지적감이다.
    required_columns: tuple[str, ...] = ()
    # table 전용. 라벨의 오른쪽/아래 칸 전체가 아니라 그 칸 안의 일부만
    # 필드 값일 때 쓴다. named group `value`, 첫 캡처 그룹, 전체 매치 순으로
    # 값을 고른다. 예: `시험 환경` 한 칸 안의 온도·습도를 각각 꺼낸다.
    capture: str = ""
    # 아래는 검사기가 읽는다. 추출에는 쓰지 않는다.
    pattern: str = ""
    format: str = ""
    equals: str = ""
    required: bool = False


@dataclass(frozen=True)
class TableRow:
    """표의 데이터 행 하나. cells 는 {열 이름: 값}."""
    cells: dict[str, str]
    anchor: Anchor


@dataclass(frozen=True)
class FieldValue:
    """꺼낸 값 하나.

    value=None, found=False 를 빈 문자열로 뭉개지 않는다. "필드가 비었다"와
    "필드를 못 찾았다"는 다른 지적이고, 후자는 라벨맵이 실제 문서와 어긋났을
    가능성이라 사람이 봐야 한다.
    """
    name: str
    value: str | None
    anchor: Anchor
    found: bool
    matched_label: str = ""
    # 이 값을 읽은 **원문 그대로의 연속 구간**. 짧은 값만 근거로 넘기면 PDF에서
    # 날짜 속 `1.0` 같은 엉뚱한 출현을 짚을 수 있다. 라벨과 값을 임의로 이어
    # 붙이지 않고 실제 표 행을 보존해야 capture/below 구조도 위치를 찾는다.
    source_quote: str = ""
    selected: tuple[str, ...] = ()
    # table_rows 전용. found=True 인데 rows 가 비면 "표는 있는데 값이 한 줄도
    # 없다" 는 뜻이다 — 표를 못 찾은 것(found=False)과 구분한다.
    rows: tuple[TableRow, ...] = ()


@dataclass
class _Table:
    """표 하나. 문서 안에서 몇 번째인지가 지적 위치가 된다."""
    no: int
    rows: list[list[str]] = field(default_factory=list)
    page: int | None = None
    section: str = ""


def _squash(text: str) -> str:
    """공백을 지운다. 라벨 표기가 문서마다 흔들려도 맞추기 위함이다."""
    return "".join(str(text or "").split())


def _cells(line: str) -> list[str] | None:
    """`| a | b |` → ['a', 'b']. 표 줄이 아니면 None."""
    s = line.strip()
    if len(s) < 2 or not (s.startswith("|") and s.endswith("|")):
        return None
    return [c.strip() for c in s[1:-1].split("|")]


def _tables(doc: Document) -> list[_Table]:
    """문서의 표들. 이어진 표 줄을 하나로 묶고 문서 순서대로 번호를 매긴다."""
    out: list[_Table] = []
    current: _Table | None = None
    for section in doc.iter_sections():
        for line in section.text.split("\n"):
            row = _cells(line)
            if row is None:
                current = None      # 표가 끊겼다
                continue
            if current is None:
                current = _Table(no=len(out) + 1, page=section.anchor.page,
                                 section=section.id)
                out.append(current)
            current.rows.append(row)
    return out


def _anchor(table: _Table, row_no: int) -> Anchor:
    """지적 위치. 이 문서들은 제목이 0개라 섹션 번호만으로는 "0"뿐이다."""
    return Anchor(page=table.page, section=f"표{table.no} {row_no}행")


def _row_quote(row: Sequence[str]) -> str:
    """표 행을 Document 직렬화와 같은 순서의 연속 원문으로 보존한다."""
    return " | ".join(row)


def _find_label(tables: Sequence[_Table], labels: Sequence[str]
                ) -> Iterator[tuple[_Table, int, int, str]]:
    """라벨이 있는 자리를 (표, 행, 열, 맞은 라벨) 로 내놓는다.

    **셀 전체가 같아야 한다.** 부분일치는 위험하다 — 갑지에는 `주소 :`(슈어소프트테크
    주소)와 `주소`(의뢰기관 주소)가 둘 다 있어서, 부분일치면 회사 주소를 의뢰기관
    주소로 읽고 그 값이 문서 간 대조에 들어가 거짓 불일치를 만든다.
    """
    wanted = {_squash(label): label for label in labels}
    for table in tables:
        for r, row in enumerate(table.rows):
            for c, cell in enumerate(row):
                hit = wanted.get(_squash(cell))
                if hit is not None:
                    yield table, r, c, hit


def _table_value(tables: Sequence[_Table], spec: FieldSpec) -> FieldValue:
    """라벨이 나온 자리들 중 **값이 있는 자리**를 고른다.

    예전에는 첫 자리에서 그냥 끝냈다. 같은 라벨이 두 번 나오고 첫 자리가 비어
    있으면(쪽 넘김에 되풀이되는 머리행 · 위에 놓인 빈 서식 행 · 안내용 행)
    아래에 있는 진짜 값을 영영 안 보고 "비어 있습니다" 를 major 로 냈다.
    문서는 멀쩡한데 도구가 엉뚱한 칸을 본 것이라, 검토자가 고칠 것이 없는
    지적이 나갔다. 인용 대조도 이걸 못 잡는다 — 근거로 다는 것이 값이 아니라
    라벨이라(agent_format/fields.py) 문서에 실재하기 때문이다.

    전부 비어 있으면 첫 자리로 "비어 있다" 를 낸다 — 그때는 진짜로 안 채운
    칸이고, required 검사가 잡아야 하는 것이 그것이다.

    **바로 옆 칸만 본다. 빈 칸을 건너뛰지 않는다.** 라벨과 값 사이에 여백 칸이
    끼는 양식이 있어 한 칸까지 건너뛰어 봤는데, 실문서(SKN56_CDMS_RVVR_Rev08
    표지 결재란 `| 작성자 : |  | Date : |`)에서 빈 칸을 넘어 옆 라벨인
    `Date :` 를 작성자 값으로 집었다 — 안 채운 칸을 지적해야 하는 자리가
    조용히 통과했다. 문서에 어떤 말이 라벨인지 우리는 모르므로(기준에 적힌
    라벨만 안다) 건너뛰기는 안전하게 만들 수 없다. 여백 칸이 끼는 양식은
    기준의 labels·at 으로 다룬다.
    """
    empty: FieldValue | None = None
    unmatched: FieldValue | None = None
    for table, r, c, label in _find_label(tables, spec.labels):
        if spec.at == "below":
            if r + 1 >= len(table.rows) or c >= len(table.rows[r + 1]):
                continue
            value = table.rows[r + 1][c]
            anchor = _anchor(table, r + 2)
        else:
            if c + 1 >= len(table.rows[r]):
                continue
            value = table.rows[r][c + 1]
            anchor = _anchor(table, r + 1)
        if spec.capture:
            match = re.search(spec.capture, value)
            if match is None:
                if unmatched is None:
                    unmatched = FieldValue(name=spec.name, value=None,
                                           anchor=anchor, found=False,
                                           matched_label=label)
                continue
            value = (match.groupdict().get("value")
                     or (match.group(1) if match.groups() else match.group(0)))

        got = FieldValue(
            name=spec.name, value=value, anchor=anchor, found=True,
            matched_label=label,
            source_quote=_row_quote(table.rows[
                r + 1 if spec.at == "below" else r]))
        if _squash(value):
            return got
        if empty is None:
            empty = got
    return empty or unmatched or FieldValue(name=spec.name, value=None,
                                            anchor=Anchor(None, None), found=False)


def _checkbox_value(tables: Sequence[_Table], spec: FieldSpec) -> FieldValue:
    """선택된 것들을 돌려준다.

    0개면 미선택, 2개 이상이면 중복 선택이다 — "항목당 하나만" 을 판정하려면 개수를
    알아야 하므로 튜플로 낸다. 판정 자체는 검사기 몫이다.
    """
    wanted = {_squash(o): o for o in spec.options}
    selected: list[str] = []
    anchor = Anchor(None, None)
    found = False
    for table in tables:
        for r, row in enumerate(table.rows):
            for cell in row:
                stripped = cell.lstrip(_UNCHECKED + _CHECKED + " \t")
                option = wanted.get(_squash(stripped))
                if option is None:
                    continue
                found = True
                if not anchor.section:
                    anchor = _anchor(table, r + 1)
                mark = cell.strip()[:1]
                if mark and mark in _CHECKED:
                    selected.append(option)
    return FieldValue(name=spec.name, value=None, anchor=anchor, found=found,
                      selected=tuple(selected))


def _column_index(row: Sequence[str], columns: Sequence[str]
                  ) -> dict[str, int] | None:
    """이 줄이 머리행인가. 맞으면 {열 이름: 칸 번호}, 아니면 None.

    **열이 하나라도 없으면 아니다.** 일부만 맞으면 다른 표일 수 있고, 엉뚱한 표를
    검사하면 거짓 지적이 난다. 실측(EV2 개정기록)은 열 사이에 빈 칸이 하나씩 끼어
    있어서 칸 번호가 0·2·4… 로 벌어진다 — 이름으로 찾으므로 상관없다.
    """
    want = {_squash(c): c for c in columns}
    found: dict[str, int] = {}
    for i, cell in enumerate(row):
        name = want.get(_squash(cell))
        if name is not None and name not in found:
            found[name] = i
    return found if len(found) == len(want) else None


def _table_cell(tables: Sequence[_Table], spec: FieldSpec) -> FieldValue:
    """머리행을 찾고 **바로 아래 값 행**에서 그 열의 칸 하나를 낸다.

    `_table_rows` 와 달리 칸 번호로 맞추지 않는다. 값 행에 빈 칸이 끼어 머리행보다
    길어지는 표가 있어서다(결재란). 빈 칸을 걷어내고 머리행에서의 **순번**으로
    맞춘다 — 걷어낸 뒤 길이가 다르면 대응을 확신할 수 없으므로 못 찾은 것으로 둔다.
    조용히 아무 칸이나 집으면 엉뚱한 값을 그 필드의 값이라고 우기게 된다.
    """
    want = spec.key or (spec.columns[0] if spec.columns else "")
    for table in tables:
        for r, row in enumerate(table.rows):
            index = _column_index(row, spec.columns)
            if index is None or want not in index:
                continue
            head = [c for c in row if _squash(c)]
            order = next((i for i, c in enumerate(head)
                          if _squash(c) == _squash(want)), None)
            if order is None:
                continue
            for j in range(r + 1, len(table.rows)):
                cells = [c for c in table.rows[j] if _squash(c)]
                if not cells:
                    continue        # 표 안의 빈 줄. 값 행은 아직 아래에 있다.
                if len(cells) != len(head):
                    # 계약대로 여기서 포기한다. 예전에는 계속 훑어 내려가서, 머리행
                    # 열이 하나 더 있는 결재란에서 한참 아래 비고·서명 행의 칸을
                    # 작성일자라고 우겼다 — 그 틀린 날짜가 선후 검사까지 오염시켰다.
                    break
                return FieldValue(name=spec.name, value=cells[order].strip(),
                                  found=True, anchor=_anchor(table, j + 1),
                                  source_quote=_row_quote(table.rows[j]))
    return FieldValue(name=spec.name, value=None, anchor=Anchor(None, None),
                      found=False)


def _table_rows(tables: Sequence[_Table], spec: FieldSpec) -> FieldValue:
    """머리행을 찾고 그 아래 데이터 행들을 낸다."""
    key = spec.key or (spec.columns[0] if spec.columns else "")
    for table in tables:
        for r, row in enumerate(table.rows):
            index = _column_index(row, spec.columns)
            if index is None:
                continue
            width = max(index.values()) + 1
            out: list[TableRow] = []
            for j in range(r + 1, len(table.rows)):
                data = table.rows[j]
                # 열 수가 모자란 줄은 이 표의 데이터가 아니다. 실측(제출물
                # 확인증)에서 표 끝에 `| 비고 |  |` 가 붙는데, 그냥 두면
                # "비고" 가 제출물명이 된다.
                if len(data) < width:
                    continue
                # 쪽을 넘기면 머리행이 되풀이된다. 그대로 두면 열 이름이 값이 된다.
                if _column_index(data, spec.columns) is not None:
                    continue
                cells = {name: data[i].strip() for name, i in index.items()}
                # key 열이 비면 빈 양식 행이다. 실측(제출물 확인증)은 실제
                # 제출물 1건에 빈 행이 20줄 더 있다.
                if not _squash(cells.get(key, "")):
                    continue
                out.append(TableRow(cells=cells, anchor=_anchor(table, j + 1)))
            return FieldValue(name=spec.name, value=None, found=True,
                              anchor=_anchor(table, r + 1), rows=tuple(out))
    return FieldValue(name=spec.name, value=None, anchor=Anchor(None, None),
                      found=False)


def extract_fields(doc: Document, specs: Sequence[FieldSpec]
                   ) -> dict[str, FieldValue]:
    """명세대로 값을 꺼낸다. {필드 이름: FieldValue}.

    못 찾은 필드도 `found=False` 로 자리를 남긴다 — 빠뜨리면 "그 필드는 검사 안 함"과
    "그 필드를 못 찾음"이 구분되지 않는다.
    """
    tables = _tables(doc)
    out: dict[str, FieldValue] = {}
    for spec in specs:
        if spec.source == "table_rows":
            out[spec.name] = _table_rows(tables, spec)
        elif spec.source == "table_cell":
            out[spec.name] = _table_cell(tables, spec)
        elif spec.source == "checkbox_group":
            out[spec.name] = _checkbox_value(tables, spec)
        elif spec.source == "table":
            out[spec.name] = _table_value(tables, spec)
        else:
            # header·footer 는 서식 레이어가 있어야 읽는다. 아직 없다.
            out[spec.name] = FieldValue(name=spec.name, value=None,
                                        anchor=Anchor(None, None), found=False)
    return out
