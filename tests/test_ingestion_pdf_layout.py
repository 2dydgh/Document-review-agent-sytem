"""로더가 표와 본문을 밴드로 갈라 조립하는지 지키는 테스트.

실문서(data/)는 gitignore 되어 커밋되지 않으므로 fpdf2 로 합성한다.
합성 표가 실문서와 같은 실패 양상(셀 안 줄바꿈)을 재현하는 것은
tests/test_pdf_tables.py 에서 확인한다.
"""
import pytest

pytest.importorskip("fpdf")
pytest.importorskip("pdfplumber")

from modules.doc_parser import RawDoc  # noqa: E402
from modules.doc_parser import PAGE_BREAK, PdfDigitalLoader  # noqa: E402


def _make_pdf(path, rows, intro="Intro paragraph.", outro="Closing paragraph."):
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
    doc.ln(6)
    doc.cell(0, 8, outro, new_x="LMARGIN", new_y="NEXT")
    doc.output(str(path))
    return path


def test_table_row_survives_as_one_line(tmp_path):
    p = _make_pdf(tmp_path / "t.pdf",
                  [["No", "Signal", "Source"],
                   ["6", "MSIS local manual\nreset status", "GC\nA/B"]])
    raw = PdfDigitalLoader().load(p)
    assert "6 | MSIS local manual reset status | GC A/B" in raw.text


def test_text_around_the_table_is_kept_in_reading_order(tmp_path):
    p = _make_pdf(tmp_path / "t.pdf", [["a", "b"], ["c", "d"]])
    raw = PdfDigitalLoader().load(p)
    body = raw.text
    assert body.index("Intro paragraph.") < body.index("a | b")
    assert body.index("a | b") < body.index("Closing paragraph.")


def test_meta_counts_pages_and_tables(tmp_path):
    p = _make_pdf(tmp_path / "t.pdf", [["a", "b"], ["c", "d"]])
    raw = PdfDigitalLoader().load(p)
    assert isinstance(raw, RawDoc)
    assert raw.meta["format"] == "pdf"
    assert raw.meta["pages"] == 1
    assert len(raw.meta["tables"]) == 1


def test_page_break_still_separates_pages(tmp_path):
    from fpdf import FPDF
    doc = FPDF()
    doc.set_auto_page_break(False)
    for body in ("FIRSTPAGE", "SECONDPAGE"):
        doc.add_page()
        doc.set_font("helvetica", size=12)
        doc.cell(0, 10, body)
    path = tmp_path / "two.pdf"
    doc.output(str(path))
    raw = PdfDigitalLoader().load(path)
    assert PAGE_BREAK in raw.text
    first, second = raw.text.split(PAGE_BREAK)
    assert "FIRSTPAGE" in first and "SECONDPAGE" in second


def test_partially_empty_pdf_is_accepted(tmp_path):
    """표지가 이미지라 1쪽이 비어도, 나머지에 글자가 있으면 읽는다."""
    from fpdf import FPDF
    doc = FPDF()
    doc.set_auto_page_break(False)
    doc.add_page()  # 빈 표지
    doc.add_page()
    doc.set_font("helvetica", size=12)
    doc.cell(0, 10, "REALBODY")
    path = tmp_path / "cover.pdf"
    doc.output(str(path))
    assert "REALBODY" in PdfDigitalLoader().load(path).text


def test_pdf_without_any_text_fails_loudly(tmp_path):
    from fpdf import FPDF
    doc = FPDF()
    doc.add_page()  # 글자 없는 빈 쪽
    path = tmp_path / "blank.pdf"
    doc.output(str(path))
    with pytest.raises(NotImplementedError):
        PdfDigitalLoader().load(path)
