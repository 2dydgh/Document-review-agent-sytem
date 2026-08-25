"""디지털 PDF 로더의 pypdf 경로 + 페이지 앵커 테스트.

본문 추출은 pdfplumber 로 옮겼다 — tests/test_ingestion_pdf_layout.py 가 덮는다.
여기 남은 것은 둘이다:

  · 여전히 pypdf 가 맡는 부분 — 암호 걸린 PDF 판정. 이제 가짜 리더로 본문까지
    흉내낼 수 없으므로(pdfplumber 가 진짜 파일을 연다) 진짜 PDF 를 만들어 두고
    암호 여부만 가짜로 덮는다.
  · RawDoc 에 폼피드를 직접 넣어 normalize 를 검증하는 페이지 추적.
"""
import pytest

from modules.doc_parser import RawDoc
from modules.doc_parser import PAGE_BREAK, PdfDigitalLoader
from modules.doc_parser import normalize
from modules.agent_trace import extract_id_statements


class _FakeReader:
    """암호 판정만 흉내낸다. 본문은 pdfplumber 가 진짜 파일에서 읽는다."""

    def __init__(self, encrypted=False, decrypt_ok=True):
        self.is_encrypted = encrypted
        self.outline = []
        self._decrypt_ok = decrypt_ok

    def decrypt(self, password):
        return 1 if self._decrypt_ok else 0


@pytest.fixture
def real_pdf(tmp_path):
    """글자가 있는 진짜 PDF. pdfplumber 가 열 수 있어야 한다."""
    fpdf = pytest.importorskip("fpdf")
    doc = fpdf.FPDF()
    doc.add_page()
    doc.set_font("helvetica", size=12)
    doc.cell(0, 10, "BODYTEXT")
    path = tmp_path / "d.pdf"
    doc.output(str(path))
    return path


@pytest.fixture
def fake_encryption(monkeypatch):
    def install(**kw):
        monkeypatch.setattr("pypdf.PdfReader", lambda path: _FakeReader(**kw))

    return install


def test_encrypted_pdf_opens_with_empty_password(real_pdf, fake_encryption):
    """인쇄 제한만 걸린 문서는 빈 암호로 열린다 — 흔한 경우다."""
    fake_encryption(encrypted=True, decrypt_ok=True)
    assert "BODYTEXT" in PdfDigitalLoader().load(real_pdf).text


def test_password_protected_pdf_is_a_clear_error(real_pdf, fake_encryption):
    fake_encryption(encrypted=True, decrypt_ok=False)
    with pytest.raises(ValueError, match="암호"):
        PdfDigitalLoader().load(real_pdf)


# ---- 페이지 앵커 (normalize) ----------------------------------------------

def _pdf_raw(*pages):
    return RawDoc(source_path="d.pdf", text=f"\n{PAGE_BREAK}\n".join(pages),
                  meta={"format": "pdf"})


def test_each_page_becomes_a_section_with_its_page_number():
    doc = normalize(_pdf_raw("첫 쪽 문장", "둘째 쪽 문장", "셋째 쪽 문장"))
    got = [(s.title, s.anchor.page) for s in doc.iter_sections()]
    assert got == [("1쪽", 1), ("2쪽", 2), ("3쪽", 3)]


def test_page_break_is_not_left_in_the_text():
    doc = normalize(_pdf_raw("가", "나"))
    assert all(PAGE_BREAK not in s.text for s in doc.iter_sections())


def test_id_on_page_three_anchors_to_page_three():
    doc = normalize(_pdf_raw("머리말", "RQ-001 로그인", "RQ-002 결제"))
    stmts = extract_id_statements(doc, r"RQ-\d{3}")
    assert stmts["RQ-001"].anchor.page == 2
    assert stmts["RQ-002"].anchor.page == 3


def test_blank_pages_do_not_create_sections_but_still_count():
    doc = normalize(_pdf_raw("1쪽 글", "   ", "3쪽 글"))
    got = [(s.title, s.anchor.page) for s in doc.iter_sections()]
    assert got == [("1쪽", 1), ("3쪽", 3)]


def test_headings_in_a_pdf_carry_the_page_number():
    raw = RawDoc(source_path="d.pdf",
                 text=f"# 개요\n앞장\n{PAGE_BREAK}\n# 설계\n뒷장", meta={})
    pages = {s.title: s.anchor.page for s in normalize(raw).iter_sections()}
    assert pages == {"개요": 1, "설계": 2}


def test_markdown_without_page_breaks_keeps_page_none():
    """마크다운/HWPX에는 쪽 개념이 없다. 없는 정보를 지어내면 안 된다."""
    raw = RawDoc(source_path="d.md", text="# 개요\n내용", meta={})
    sections = list(normalize(raw).iter_sections())
    assert all(s.anchor.page is None for s in sections)
