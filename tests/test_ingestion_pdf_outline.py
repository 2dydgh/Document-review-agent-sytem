"""PDF 책갈피(outline)로 섹션 트리를 복원하는지 지키는 테스트.

PDF에는 마크다운 heading이 없어서, 예전에는 쪽마다 섹션을 하나씩 만들었다.
제목이 '1쪽', '2쪽'이 되므로 다음이 전부 반쪽이 된다:

  · CompletenessChecker 가 required_sections 를 '1쪽','2쪽'과 대조하게 되어
    **무엇을 넣든 매칭되지 않는다** — 채우면 100% 오탐이다. 데모 체크리스트가
    실문서에서 가짜 '누락' 3건을 낸 것이 정확히 이 경로였다.
  · 지적 위치가 "3쪽"까지만 나온다. "1.3.2 Acronyms"라고 말할 수 없다.
  · 청킹이 쪽 단위가 된다. 절이 쪽을 넘어가면 문맥이 끊긴다.

그런데 실제 문서에는 책갈피가 있다(실측: SHN34 SRS 380개, CDMS RVVR 67개).
그걸 읽어 heading 으로 심으면 normalize() 가 진짜 트리를 만든다.

책갈피가 없는 PDF(실측: SKN56 CPS SRS 0개)는 예전처럼 쪽 단위로 떨어진다 —
없는 구조를 지어내지 않는다.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

pytest.importorskip("fpdf")

from pypdf import PdfReader, PdfWriter  # noqa: E402

from modules.doc_parser import load_document  # noqa: E402
from modules.doc_parser import normalize  # noqa: E402


def _pdf(pages: list[tuple[str, str]]) -> bytes:
    """(제목줄, 본문줄) 목록으로 페이지를 만든다. 제목은 본문에 실제로 찍힌다."""
    from fpdf import FPDF
    doc = FPDF()
    doc.set_auto_page_break(False)
    for title, body in pages:
        doc.add_page()
        doc.set_font("helvetica", size=14)
        doc.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
        doc.set_font("helvetica", size=11)
        doc.cell(0, 10, body)
    return bytes(doc.output())


def _with_outline(data: bytes, marks) -> bytes:
    """marks: [(title, page, parent_index_or_None)] 순서대로 책갈피를 단다."""
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    made = []
    for title, page, parent in marks:
        made.append(writer.add_outline_item(
            title, page, parent=None if parent is None else made[parent]))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.fixture
def outlined(tmp_path: Path) -> Path:
    data = _pdf([("1.0 Introduction", "Purpose text here"),
                 ("2.0 Scope", "Scope body line")])
    p = tmp_path / "outlined.pdf"
    p.write_bytes(_with_outline(data, [("1.0 Introduction", 0, None),
                                       ("1.1 Purpose", 0, 0),
                                       ("2.0 Scope", 1, None)]))
    return p


@pytest.fixture
def plain(tmp_path: Path) -> Path:
    p = tmp_path / "plain.pdf"
    p.write_bytes(_pdf([("Alpha heading", "alpha body"), ("Beta heading", "beta body")]))
    return p


def test_bookmarked_pdf_gets_real_section_titles(outlined):
    doc = normalize(load_document(outlined))
    titles = [s.title for s in doc.iter_sections()]
    assert "1.0 Introduction" in titles
    assert "2.0 Scope" in titles
    assert not any(t.endswith("쪽") for t in titles), f"쪽 제목이 남았다: {titles}"


def test_bookmark_hierarchy_becomes_a_tree(outlined):
    doc = normalize(load_document(outlined))
    root = next(s for s in doc.sections if s.title == "1.0 Introduction")
    assert [c.title for c in root.children] == ["1.1 Purpose"]


def test_sections_keep_their_page_number(outlined):
    """절 제목을 얻었다고 쪽을 잃으면 안 된다 — PDF 하이라이트가 쪽으로 점프한다."""
    doc = normalize(load_document(outlined))
    by = {s.title: s.anchor.page for s in doc.iter_sections()}
    assert by["1.0 Introduction"] == 1
    assert by["2.0 Scope"] == 2


def test_body_text_lands_under_its_section(outlined):
    doc = normalize(load_document(outlined))
    scope = next(s for s in doc.iter_sections() if s.title == "2.0 Scope")
    assert "Scope body line" in scope.text


def test_title_line_is_not_duplicated_in_the_body(outlined):
    """제목은 heading 이 된다. 본문에도 그대로 남으면 같은 줄이 두 번 세어진다."""
    doc = normalize(load_document(outlined))
    intro = next(s for s in doc.iter_sections() if s.title == "1.0 Introduction")
    assert "1.0 Introduction" not in intro.text


def test_pdf_without_bookmarks_keeps_page_sections(plain):
    """없는 구조를 지어내지 않는다. 책갈피가 0개인 실문서가 실제로 있다."""
    doc = normalize(load_document(plain))
    titles = [s.title for s in doc.iter_sections()]
    assert titles == ["1쪽", "2쪽"], titles
