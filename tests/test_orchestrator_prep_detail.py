"""진행 화면 '문서 준비' 줄에 무엇을 띄우는지 지키는 테스트.

이 문자열은 orchestrator 가 emit 하고 api.js 가 r.prep 에 담아 views.js 가
그대로 그린다. 프론트엔드에 로직이 없으므로 여기가 유일한 계약 지점이다.

세는 척하지 않는다 — meta 에 없는 값은 띄우지 않는다.
"""
from modules.doc_parser import RawDoc
from app.orchestrator import _ingestion_detail


def test_pdf_shows_pages_and_tables():
    raw = RawDoc(source_path="a.pdf", text="x" * 12000,
                 meta={"format": "pdf", "pages": 236, "tables": [{"columns": [], "fontSizes": {}}] * 194})
    detail = _ingestion_detail(raw)
    assert "236쪽" in detail
    assert "표 194" in detail


def test_pdf_without_tables_omits_the_table_part():
    raw = RawDoc(source_path="a.pdf", text="x" * 100,
                 meta={"format": "pdf", "pages": 3, "tables": []})
    detail = _ingestion_detail(raw)
    assert "3쪽" in detail
    assert "표" not in detail


def test_non_pdf_input_keeps_the_old_string():
    """docx·hwpx 는 meta 에 쪽·표가 없다. 지어내지 않는다."""
    raw = RawDoc(source_path="a.docx", text="x" * 100, meta={"format": "docx"})
    detail = _ingestion_detail(raw)
    assert "쪽" not in detail
    assert "표" not in detail


def test_word_문서는_표_목록이_아니라_개수를_띄운다():
    """파서마다 meta 에 남기는 모양이 다르다 — PDF 는 개수, Word·HWP 는 표 목록.

    목록을 그대로 이어붙여 진행 화면에 이렇게 찍혔다:
        문서 준비 · 798 chars · 표 [{'columns': ['일자', ...], 'fontSizes': {8.0: 160}}]
    표 목록은 표 글꼴 검사가 읽는 데이터지 사람이 읽을 글이 아니다.
    """
    raw = RawDoc(source_path="a.docx", text="x" * 798, meta={
        "format": "docx",
        "tables": [{"columns": ["일자", "시험 업무"], "fontSizes": {8.0: 160}},
                   {"columns": ["항목"], "fontSizes": {}}]})
    detail = _ingestion_detail(raw)
    assert "표 2" in detail
    assert "columns" not in detail and "{" not in detail
