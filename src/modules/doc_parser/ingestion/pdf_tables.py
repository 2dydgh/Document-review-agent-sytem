"""표를 찾아 1논리행 = 1줄로 렌더한다.

pypdf 는 셀 안에 줄바꿈이 있는 표에서 한 행을 3~5줄로 파열시킨다.
실측(SHN34 SRS 본문 108쪽) — 논리적 한 행:

    6 | MSIS local manual reset status | GC A/B | MTP A/B | Bool | Not Reset/Reset

pypdf 출력:

    6 MSIS local manual reset status GC
    A/B
    MTP
    A/B Bool Not Reset/
    Reset

GC 와 MTP 가 각자 줄이 되고 A/B 가 어느 열 것인지 사라진다. 엔진은 줄 단위로
대조하므로 이 5줄은 노이즈다. 이 문서들의 표 안 글자는 54~88% 를 차지한다
(SHN34 SRS 71.5%, RVVR 88.4%).
"""
from __future__ import annotations

import re

# 표 셀은 ID를 하이픈 뒤에서 끊는다 — "FR-\nMTP_02"(SHN34 RVVR 358회).
# 셀 안 줄바꿈을 전부 공백으로 접으면 "FR- MTP_02" 가 되고, idref 의 하이픈
# 줄바꿈 복구(_WRAP)는 개행만 보므로 걸리지 않는다. 그러면 하위문서에 실재하는
# ID를 못 찾아 상위 요건이 '누락'으로 보고된다 — 없는 결함을 만들어내는 것이다.
# 실제로 이 경로로 추적성 8건이 죽었다(2026-07-28 실측).
#
# 복구는 여기서 한다. idref 쪽 _WRAP 을 "하이픈+공백"까지 넓히면 문서 전체에서
# "A - B" 가 "A -B" 로 붙어 서술이 망가진다. 셀 안 줄바꿈이라는 것을 아는 건
# 여기뿐이다.
_HYPHEN_WRAP = re.compile(r"-[ \t]*\n[ \t]*")

# 1열짜리는 표가 아니다. 도면 안에서 이런 오검출이 나온다(본문 17쪽 13x64pt).
MIN_COLUMNS = 2
# 이보다 작으면 표로 치지 않는다.
MIN_WIDTH = 40.0
MIN_HEIGHT = 20.0

CELL_SEP = " | "


def is_usable(table, *, min_columns: int = MIN_COLUMNS,
              min_width: float = MIN_WIDTH, min_height: float = MIN_HEIGHT) -> bool:
    """진짜 표인가. bbox 와 columns 를 가진 것이면 무엇이든 받는다."""
    x0, top, x1, bottom = table.bbox
    if len(table.columns) < min_columns:
        return False
    return (x1 - x0) >= min_width and (bottom - top) >= min_height


def usable_tables(page) -> list:
    """오검출을 뺀 표 목록을 top 오름차순으로 준다."""
    found = [t for t in page.find_tables() if is_usable(t)]
    return sorted(found, key=lambda t: t.bbox[1])


def cell_lines(page, bbox) -> list[str]:
    """셀 하나의 글자를 좌표에서 줄 단위로 읽는다. 공백을 지우지 않는다.

    `extract()` 를 안 쓰는 이유 — 그쪽은 셀 안 줄 끝의 **공백을 지운다.** 그러면
    줄바꿈이 단어 사이였는지 단어 중간이었는지 알 수 없고, 접을 때 넣은 공백이
    멀쩡한 단어를 가른다. 실측(SKN56 CDMS RVVR): `Communication` → `Communicati on`,
    `Backup` → `Ba ckup`, `구현하여` → `구 현하여`. 검토자에게는 문서 오탈자로
    보이지만 문서는 멀쩡하고 우리가 깨뜨린 것이다.

    글자 좌표에는 그 공백이 남아 있다. 그래서 **줄을 그냥 이어 붙이면** 공백이
    저절로 맞는다:

        'Shared ' + 'Memory '  →  'Shared Memory '   (공백이 이미 있다)
        'ommunicati' + 'on '   →  'ommunication '    (없으니 붙는다)

    하이픈 뒤 줄바꿈(`FR-` + `MTP_02`)도 같은 규칙으로 붙는다.

    실측(SHN34 ESF-CCS SRS 60쪽): 줄바꿈 1259건 중 1247건이 공백으로 이어지고
    12건만 붙는다. 붙는 쪽은 전부 진짜 갈라진 토큰이었다(`ITP,MTP,O`+`M`).
    """
    x0, top, x1, bottom = bbox
    chars = [c for c in page.chars
             if x0 - 1 <= c["x0"] and c["x1"] <= x1 + 1
             and top - 1 <= c["top"] and c["bottom"] <= bottom + 1]
    if not chars:
        return []

    # 줄 묶기에 **허용 오차**가 필요하다. `round(top)` 으로 묶으면 한글과 영문의
    # 기준선 차이(0.2pt)만으로 한 줄이 둘로 갈린다. 실측(SKN56 CDMS RVVR p38):
    #
    #     top=279.4  x=285~321  '에서통신'      → round 279
    #     top=279.6  x=260~323  'CDMS  '       → round 280
    #
    # 갈리면 위에서 아래 순으로 이어 붙어 `에서통신CDMS` 가 된다. 원문은
    # "CDMS에서 통신" 이다 — 순서가 뒤집히고 공백도 사라진다. 글자 순서가
    # 뒤섞인다고 본 것이 전부 이 한 줄 때문이었다.
    #
    # 오차는 글자 높이에 비례시킨다. 고정값을 쓰면 큰 글꼴의 다른 줄까지 묶인다.
    heights = sorted(c["bottom"] - c["top"] for c in chars)
    tol = heights[len(heights) // 2] * 0.5
    chars = sorted(chars, key=lambda c: (c["top"], c["x0"]))
    rows: list[list] = [[chars[0]]]
    for c in chars[1:]:
        if c["top"] - rows[-1][0]["top"] <= tol:
            rows[-1].append(c)
        else:
            rows.append([c])
    return ["".join(c["text"] for c in sorted(r, key=lambda c: c["x0"])) for r in rows]


def _has_wrap_space(cells: list[list[list[str]]]) -> bool:
    """이 표가 줄 끝 공백을 실어 나르는가.

    **모든 PDF 가 그러지는 않는다.** Word 가 낸 실문서는 남기지만, 글자를 직접
    찍어 만든 PDF 는 안 남긴다(이 저장소의 합성 시험 PDF 가 그렇다). 신호가 없는데
    좌표만 믿고 이어 붙이면 `manual`+`reset` 이 `manualreset` 이 된다 — 고치려던
    것과 정반대의 결함이다.

    그래서 표마다 먼저 세어 본다. 하나도 없으면 신호가 없는 PDF 로 보고 예전처럼
    공백으로 접는다.
    """
    return any(ln.endswith(" ") or nxt.startswith(" ")
               for row in cells for lines in row
               for ln, nxt in zip(lines, lines[1:]))


def render_table(page, table, *, sep: str = CELL_SEP) -> list[str]:
    """표 하나 → 1논리행 = 1줄. 셀 글자는 좌표에서 읽는다(cell_lines).

    구조(몇 행 몇 열인가)는 `table.rows` 가 준 것을 그대로 쓰고, 칸 안의 글자만
    다시 읽는다.
    """
    grid = [[cell_lines(page, b) if b else [] for b in row.cells] for row in table.rows]
    glue = "" if _has_wrap_space(grid) else " "
    lines: list[str] = []
    for row in grid:
        cells = [" ".join(_HYPHEN_WRAP.sub("-", glue.join(c)).split()) for c in row]
        if not any(cells):
            continue
        lines.append(sep.join(cells))
    return lines


def table_meta(page, table) -> dict:
    """표 하나의 요약 — 머리행과 글꼴 크기별 글자 수.

    **docx 로더가 남기는 모양과 같다**(`{"columns", "fontSizes"}`). 형식마다 다른
    모양을 남기면 그걸 읽는 검사기가 형식을 알아야 한다. 실제로 그랬다 — PDF 는
    표 개수(정수)를, Word 는 표 목록을 같은 열쇠에 넣어서, 표 글꼴 검사가 PDF 를
    만나면 `'int' object is not iterable` 로 죽었다.

    PDF 쪽이 오히려 정확하다. Word 는 대부분의 글자가 크기를 안 갖고 스타일에서
    물려받아 **직접 박은 크기만** 보이지만, PDF 는 종이에 찍힌 실제 크기가 글자마다
    있다. 팀 기준이 말하는 "테스트케이스 글꼴 8pt 또는 9pt" 는 이쪽이다.
    """
    x0, top, x1, bottom = table.bbox
    sizes: dict[float, int] = {}
    for c in page.chars:
        if (x0 - 1 <= c["x0"] and c["x1"] <= x1 + 1
                and top - 1 <= c["top"] and c["bottom"] <= bottom + 1):
            key = round(float(c["size"]), 1)
            sizes[key] = sizes.get(key, 0) + 1
    columns: list[str] = []
    for row in table.rows:
        cells = [" ".join(" ".join(cell_lines(page, b)).split()) if b else ""
                 for b in row.cells]
        if any(cells):
            columns = cells      # 글자가 있는 첫 행이 머리행이다
            break
    return {"columns": columns, "fontSizes": sizes}


def render_rows(data: list[list[str | None]], *, sep: str = CELL_SEP) -> list[str]:
    """extract() 결과 → 1논리행 = 1줄.

    셀 안의 줄바꿈은 공백으로 접되, **하이픈 뒤 줄바꿈은 붙인다**(끊긴 ID다).
    마크다운 표로 만들지 않는 이유는 정렬행(---)이 끼어들어 줄 수가 늘고 줄 단위
    대조가 어긋나기 때문이다.
    """
    lines: list[str] = []
    for row in data:
        cells = [" ".join(_HYPHEN_WRAP.sub("-", str(c or "")).split()) for c in row]
        if not any(cells):
            continue
        lines.append(sep.join(cells))
    return lines
