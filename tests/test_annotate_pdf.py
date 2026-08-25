"""원본 PDF 형광펜 표시.

시험용 PDF는 헤드리스 크롬으로 만든 것을 쓴다(tests/data/probe.pdf). 한글이
들어간 진짜 디지털 PDF여야 자간 문제(‘3 초’)까지 재현된다 — 그게 이 모듈이
공백을 통째로 지우고 대조하는 이유다.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader

from modules.report import annotate

pytest.importorskip("pdfplumber", reason="web extra에만 있다")

PDF = Path(__file__).parent / "data" / "probe.pdf"
pytestmark = pytest.mark.skipif(not PDF.exists(), reason="시험용 PDF 없음")

# 추출 텍스트 그대로. pypdf가 자간을 공백으로 낸다 — 인용도 그 모양으로 온다.
QUOTE_3 = "RQ-SFR-PR-01-001 예측  응답시간은  3 초  이내여야  한다 ."
QUOTE_5 = "RQ-SFR-PR-01-001 예측  응답시간은  5 초  이내로  한다 ."


def _finding(fid, quote, sev="minor", page=1):
    return {"id": fid, "sev": sev, "checker": "consistency",
            "message": "응답시간이 3초와 5초로 상충된다",
            "section": "0", "page": page,
            "evidence": [{"quote": quote, "section": "0", "page": page}]}


def _annots(pdf_bytes, page=-1):
    """주석은 본문 페이지에 붙는다.

    요약 페이지가 맨 앞에 끼어들므로 pages[0]은 더 이상 원본 1쪽이 아니다.
    기본값 -1 = 마지막 페이지(시험 PDF는 본문이 한 장이다).
    """
    pg = PdfReader(__import__("io").BytesIO(pdf_bytes)).pages[page]
    return [a.get_object() for a in (pg.get("/Annots") or [])]


def test_quote_becomes_a_highlight_on_the_original_pdf():
    out = annotate(PDF.read_bytes(), [_finding("f1", QUOTE_3)])
    assert out.marked == 1 and out.unmarked == []
    kinds = [a.get("/Subtype") for a in _annots(out.pdf)]
    assert "/Highlight" in kinds


def test_highlight_carries_the_finding_message_as_popup():
    # 뷰어에서 형광펜을 누르면 지적이 뜬다. 본문에 글자를 그리지 않으므로
    # 한글 폰트를 PDF에 심을 필요가 없다.
    out = annotate(PDF.read_bytes(), [_finding("f1", QUOTE_3)])
    hl = [a for a in _annots(out.pdf) if a.get("/Subtype") == "/Highlight"][0]
    assert "3초와 5초" in str(hl.get("/Contents"))


def test_whitespace_differences_do_not_break_the_match():
    # 한글 PDF는 자간 때문에 낱말이 쪼개진다. 공백을 지우고 맞추므로 인용의
    # 공백이 어떻게 오든 찾아야 한다.
    squashed = QUOTE_3.replace(" ", "")
    out = annotate(PDF.read_bytes(), [_finding("f1", squashed)])
    assert out.marked == 1 and out.unmarked == []


def test_same_quote_is_painted_once_even_if_two_checkers_report_it():
    # 표현 점검과 일관성 agent가 같은 불일치를 각각 찾는 일이 흔하다.
    two = [_finding("f1", QUOTE_3), _finding("f2", QUOTE_3)]
    out = annotate(PDF.read_bytes(), two)
    assert out.marked == 1
    assert len([a for a in _annots(out.pdf) if a.get("/Subtype") == "/Highlight"]) == 1


def test_missing_quote_is_reported_not_swallowed():
    # 조용히 넘기면 "형광펜이 없다 = 지적이 없다"로 읽힌다.
    out = annotate(PDF.read_bytes(), [_finding("f1", "이 문장은 원문에 없다")])
    assert out.marked == 0
    assert len(out.unmarked) == 1 and out.unmarked[0]["id"] == "f1"


def test_summary_page_is_prepended():
    # 크롬 기본 뷰어는 주석 팝업의 한글을 못 찍고, 인쇄하면 팝업은 사라진다.
    # 지적 내용을 지면에 직접 그린 페이지가 앞에 붙어야 한다.
    before = len(PdfReader(str(PDF)).pages)
    out = annotate(PDF.read_bytes(), [_finding("f1", QUOTE_3)], doc_name="시험.pdf")
    after = len(PdfReader(__import__("io").BytesIO(out.pdf)).pages)
    assert out.summary is True
    assert after > before, "요약 페이지가 앞에 붙어야 한다"


def test_unmarked_is_still_reported_when_a_summary_exists():
    # 요약이 있으면 옛 방식(1쪽 스티커 메모)은 안 붙인다. 대신 요약 페이지가
    # 말한다. 어느 쪽이든 "표시가 없다 = 이상 없다"로 읽히면 안 된다.
    out = annotate(PDF.read_bytes(), [_finding("f1", "이 문장은 원문에 없다")])
    assert out.marked == 0
    assert len(out.unmarked) == 1
    assert out.summary is True


def test_rule_findings_without_evidence_are_not_counted_as_failures():
    # TBD 지적은 근거를 안 단다. 칠할 자리가 없는 것이지 실패가 아니다.
    tbd = {"id": "f9", "sev": "major", "checker": "completeness",
           "message": "미완성 표시가 남아 있습니다: TBD",
           "section": "0", "page": 1, "evidence": []}
    out = annotate(PDF.read_bytes(), [tbd])
    assert out.marked == 0 and out.unmarked == []


def test_two_quotes_on_the_same_page_both_get_marked():
    out = annotate(PDF.read_bytes(),
                   [_finding("f1", QUOTE_3), _finding("f2", QUOTE_5)])
    assert out.marked == 2 and out.unmarked == []


def test_summary_pages_counts_inserted_pages():
    # 표시본은 앞에 요약 페이지가 끼어든다. 화면이 지적의 page로 점프하려면
    # 몇 장이 밀렸는지 알아야 한다 — 그 수를 Marked가 실어야 한다.
    before = len(PdfReader(str(PDF)).pages)
    out = annotate(PDF.read_bytes(), [_finding("f1", QUOTE_3)], doc_name="시험.pdf")
    after = len(PdfReader(__import__("io").BytesIO(out.pdf)).pages)
    assert out.summary is True
    assert out.summary_pages == after - before
    assert out.summary_pages >= 1


def test_summary_pages_is_zero_without_a_summary(monkeypatch):
    # 한글 폰트가 없어 요약을 못 넣으면 삽입이 0장이다.
    import modules.report.annotate_pdf as ap
    monkeypatch.setattr(ap, "find_font", lambda: (_ for _ in ()).throw(ap.FontMissing("no font")))
    out = annotate(PDF.read_bytes(), [_finding("f1", QUOTE_3)], doc_name="시험.pdf")
    assert out.summary is False
    assert out.summary_pages == 0


def test_numbers_map_findings_to_the_marks_drawn_on_the_page():
    """화면 카드가 표시본과 같은 번호를 달 수 있어야 한다.

    지면의 번호표는 형광펜에 매달린다. 그 번호를 지적 id로 되짚을 수 없으면
    화면은 자기 나름의 번호를 새로 매길 수밖에 없고, 그러면 "3번 지적"이
    표시본과 화면에서 서로 다른 것을 가리킨다.
    """
    out = annotate(PDF.read_bytes(),
                   [_finding("f1", QUOTE_3), _finding("f2", QUOTE_5)])
    assert out.numbers == {"f1": "1", "f2": "2"}


def test_findings_without_a_mark_get_no_number():
    """칠하지 못한 지적에 번호를 지어내면 지면에 없는 번호를 가리키게 된다."""
    tbd = {"id": "f9", "sev": "major", "checker": "completeness",
           "message": "미완성 표시가 남아 있습니다: TBD",
           "section": "0", "page": 1, "evidence": []}
    out = annotate(PDF.read_bytes(), [_finding("f1", QUOTE_3), tbd])
    assert out.numbers == {"f1": "1"}
    assert "f9" not in out.numbers


def test_findings_sharing_a_quote_share_its_number():
    """같은 인용은 한 번만 칠하고 번호도 하나다 — 둘 다 그 번호를 가리켜야 한다."""
    out = annotate(PDF.read_bytes(),
                   [_finding("f1", QUOTE_3), _finding("f2", QUOTE_3)])
    assert out.numbers == {"f1": "1", "f2": "1"}


def test_number_labels_stay_in_the_margin_not_on_the_text():
    """번호표는 왼쪽 여백에 세운다.

    예전에는 형광펜 시작점의 16pt 왼쪽에 놓았다. 줄 맨 앞을 칠할 때는 맞지만
    줄 중간을 칠하면("제정일자: 2025.00.00." 에서 날짜만) 그 자리가 바로 앞
    글자 위였고, 번호표가 본문을 덮어 글자가 깨져 보였다.
    """
    import io as _io

    import pdfplumber

    from modules.report.pdf_summary import number_overlay

    # 줄 한참 오른쪽(x=400)에서 시작하는 형광펜.
    data = number_overlay((595.0, 842.0), [(7, 400.0, 100.0, "minor")])
    with pdfplumber.open(_io.BytesIO(data)) as pdf:
        words = pdf.pages[0].extract_words()
    assert words, "번호가 그려지지 않았다"
    x0 = min(w["x0"] for w in words)
    assert x0 < 40, (
        f"번호표가 여백이 아니라 본문 자리(x={x0:.0f})에 찍혔다 — 글자를 덮는다"
    )


def test_two_marks_on_one_line_do_not_stack_on_each_other():
    """같은 줄에 형광펜이 둘이면 번호표도 둘이다. 겹치면 하나만 읽힌다."""
    import io as _io

    import pdfplumber

    from modules.report.pdf_summary import number_overlay

    data = number_overlay((595.0, 842.0),
                          [(1, 100.0, 200.0, "minor"), (2, 300.0, 200.0, "minor")])
    with pdfplumber.open(_io.BytesIO(data)) as pdf:
        words = pdf.pages[0].extract_words()
    xs = sorted(w["x0"] for w in words)
    assert len(xs) == 2, f"번호 두 개가 안 보인다: {words}"
    assert xs[1] - xs[0] > 8, "같은 자리에 겹쳐 찍혔다"
