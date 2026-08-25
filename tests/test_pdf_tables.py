"""표를 1논리행 = 1줄로 복원하는지 지키는 테스트.

pypdf 는 셀 안에 줄바꿈이 있는 표에서 한 행을 3~5줄로 파열시킨다(실측:
SHN34 SRS 본문 108쪽). 엔진이 줄 단위로 대조하므로 그 조각들은 노이즈다.

시험용 PDF 는 fpdf2 로 만든다. 실문서(data/)는 gitignore 되어 커밋되지 않기
때문이다. fpdf2 의 doc.table() 이 만든 표를 pdfplumber 가 실문서와 똑같은
모양으로 읽는 것을 확인했다 — 셀 안 줄바꿈이 '\n' 으로 그대로 남는다.
"""
import io

import pytest

pytest.importorskip("fpdf")
pytest.importorskip("pdfplumber")

import pdfplumber  # noqa: E402

from modules.doc_parser.ingestion.pdf_tables import (is_usable, render_rows,  # noqa: E402
                                                     render_table, usable_tables)


def _pdf_with_table(rows, intro="Intro paragraph before the table."):
    from fpdf import FPDF
    doc = FPDF()
    doc.add_page()
    doc.set_font("helvetica", size=10)
    doc.cell(0, 8, intro, new_x="LMARGIN", new_y="NEXT")
    with doc.table() as table:
        for r in rows:
            row = table.row()
            for cell in r:
                row.cell(cell)
    return bytes(doc.output())


class _FakeTable:
    """bbox 와 columns 만 있으면 is_usable 을 시험할 수 있다."""

    def __init__(self, bbox, ncols):
        self.bbox = bbox
        self.columns = [None] * ncols


def test_multiline_cells_collapse_into_one_line():
    """pypdf 가 5줄로 파열시키던 행이 한 줄로 나와야 한다."""
    data = [["No", "Signal", "Source"],
            ["6", "MSIS local manual\nreset status", "GC\nA/B"]]
    pdf = _pdf_with_table(data)
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        table = usable_tables(doc.pages[0])[0]
        lines = render_rows(table.extract())
    assert lines[0] == "No | Signal | Source"
    assert lines[1] == "6 | MSIS local manual reset status | GC A/B"


def test_row_count_matches_logical_rows():
    data = [["a", "b"], ["c\nd", "e"], ["f", "g\nh"]]
    pdf = _pdf_with_table(data)
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        lines = render_rows(usable_tables(doc.pages[0])[0].extract())
    assert len(lines) == 3


def test_single_column_detection_is_rejected():
    """도면 안에서 잡히는 1열 가짜 표(실측: 본문 17쪽 13x64pt)를 걸러낸다."""
    assert not is_usable(_FakeTable((205.0, 459.0, 218.0, 523.0), 1))
    assert is_usable(_FakeTable((128.0, 71.0, 553.0, 758.0), 6))


def test_tiny_detection_is_rejected():
    assert not is_usable(_FakeTable((100.0, 100.0, 120.0, 110.0), 2))


def test_empty_rows_are_skipped():
    assert render_rows([["a", "b"], [None, None], ["", "  "], ["c", "d"]]) == ["a | b", "c | d"]


def test_none_cells_become_empty_strings():
    assert render_rows([["a", None, "c"]]) == ["a |  | c"]


def test_hyphen_line_break_inside_a_cell_is_joined_without_a_space():
    """표 셀은 ID를 하이픈 뒤에서 끊는다 — SHN34 RVVR 에서 358회.

    셀 안 줄바꿈을 그냥 공백으로 접으면 'FR- MTP_02' 가 되고, idref 의 하이픈
    줄바꿈 복구(_WRAP)는 개행만 보므로 걸리지 않는다. 그러면 하위문서에 실재하는
    ID 를 못 찾아 상위 요건이 '누락'으로 보고된다 — 없는 결함을 만들어낸다.
    실제로 이 경로로 추적성 8건이 죽었다.
    """
    assert render_rows([["FR-\nMTP_02", "x"]]) == ["FR-MTP_02 | x"]


def test_ordinary_line_break_inside_a_cell_still_becomes_a_space():
    assert render_rows([["MSIS local manual\nreset status", "x"]]) == [
        "MSIS local manual reset status | x"]


# ── 셀 안 줄바꿈: 공백을 넣을지 붙일지 ──────────────────────────────────────
# 예전에는 무조건 공백으로 접었다. 그래서 셀 폭에 걸려 잘린 단어가 갈라졌다 —
# 실측(SKN56 CDMS RVVR): `Communication`→`Communicati on`, `Backup`→`Ba ckup`,
# `구현하여`→`구 현하여`. 검토자에게는 문서 오탈자로 보이는데 문서는 멀쩡했다.
#
# 실문서는 줄 끝 공백을 글자로 실어 나른다(extract() 가 지울 뿐이다). 그래서
# 좌표에서 읽어 그냥 이어 붙이면 공백이 저절로 맞는다. 다만 **모든 PDF 가 그러지는
# 않아서**, 신호가 없으면 예전처럼 접어야 한다 — 안 그러면 `manual`+`reset` 이
# `manualreset` 이 된다.


def test_줄_끝_공백이_있으면_그것이_신호다():
    from modules.doc_parser.ingestion.pdf_tables import _has_wrap_space
    assert _has_wrap_space([[["Shared ", "Memory"]]])
    assert _has_wrap_space([[["IPS", " Communication"]]])


def test_줄_끝_공백이_없으면_신호가_없다():
    from modules.doc_parser.ingestion.pdf_tables import _has_wrap_space
    assert not _has_wrap_space([[["manual", "reset"]]])
    assert not _has_wrap_space([[["한 줄뿐"]]])       # 이을 자리가 없다
    assert not _has_wrap_space([])


def test_신호가_없는_pdf_는_예전처럼_공백으로_접는다():
    """이 저장소의 합성 PDF 가 그렇다. 붙이면 단어가 뭉개진다."""
    raw = _pdf_with_table([["No", "Signal", "Source"],
                           ["6", "MSIS local manual\nreset status", "GC\nA/B"]])
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        page = pdf.pages[0]
        lines = render_table(page, usable_tables(page)[0])
    assert any("manual reset status" in ln for ln in lines), lines
    assert not any("manualreset" in ln for ln in lines), lines


def test_tables_come_back_in_top_order():
    from fpdf import FPDF
    doc = FPDF()
    doc.add_page()
    doc.set_font("helvetica", size=10)
    for tag in ("FIRST", "SECOND"):
        with doc.table() as table:
            row = table.row()
            row.cell(tag)
            row.cell("x")
        doc.ln(10)
    with pdfplumber.open(io.BytesIO(bytes(doc.output()))) as pdf:
        tables = usable_tables(pdf.pages[0])
        tops = [t.bbox[1] for t in tables]
    assert tops == sorted(tops)


def test_기준선이_어긋난_한_줄을_둘로_가르지_않는다():
    """한글과 영문이 섞인 줄은 글꼴이 달라 top 이 미세하게 어긋난다.

    실측(SKN56 CDMS RVVR p38) — 같은 줄인데 0.2pt 차이다:

        top=279.4  x=285~321  '에서통신'
        top=279.6  x=260~323  'CDMS  '

    `round(top)` 으로 묶으면 279 와 280 으로 갈리고, 갈린 둘을 위에서 아래 순으로
    이어 붙이면 `에서통신CDMS` 가 된다. 원문은 "CDMS에서 통신" 이다 — 순서가
    뒤집히고 공백까지 사라진다. 글자가 뒤섞인다고 본 증상이 전부 이것이었다.
    """
    class _Page:
        chars = [
            # 같은 줄. 한글이 0.2pt 위에 있고 x 는 뒤다.
            {"text": "C", "x0": 10, "x1": 16, "top": 100.6, "bottom": 110.6},
            {"text": "D", "x0": 16, "x1": 22, "top": 100.6, "bottom": 110.6},
            {"text": "에", "x0": 24, "x1": 34, "top": 100.4, "bottom": 110.4},
            {"text": "서", "x0": 34, "x1": 44, "top": 100.4, "bottom": 110.4},
            # 다음 줄
            {"text": "X", "x0": 10, "x1": 16, "top": 120.0, "bottom": 130.0},
        ]

    from modules.doc_parser.ingestion.pdf_tables import cell_lines
    lines = cell_lines(_Page(), (0, 90, 60, 140))
    assert lines == ["CD에서", "X"], lines
