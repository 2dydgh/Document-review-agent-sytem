"""업로드 파일에서 표를 뽑는다.

한 파일에 표가 여럿이다 — IS16 은 쪽마다, IS22 는 시트가 30여 개다. 그래서
목록으로 보여주고 고르게 해야 하고, 각 표에 사람이 알아볼 라벨이 필요하다.
"""
import io
import zipfile

import pytest

from modules.preset.parse import (UnsupportedChecklistFormat,
                                       extract_tables)


def _xlsx(sheets: dict[str, list[list[str]]]) -> bytes:
    """시트 이름 → 행 목록으로 최소 xlsx 를 만든다(inlineStr 사용)."""
    NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    R = ('xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
         '2006/relationships"')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        wb = [f"<workbook {NS} {R}><sheets>"]
        rels = ['<Relationships xmlns="http://schemas.openxmlformats.org/'
                'package/2006/relationships">']
        for n, (name, rows) in enumerate(sheets.items(), 1):
            wb.append(f'<sheet name="{name}" sheetId="{n}" r:id="rId{n}"/>')
            rels.append(f'<Relationship Id="rId{n}" Target="worksheets/'
                        f'sheet{n}.xml" Type="x"/>')
            body = []
            for row in rows:
                cells = "".join(
                    f'<c t="inlineStr"><is><t>{c}</t></is></c>' for c in row)
                body.append(f"<row>{cells}</row>")
            z.writestr(f"xl/worksheets/sheet{n}.xml",
                       f'<worksheet {NS}><sheetData>{"".join(body)}'
                       "</sheetData></worksheet>")
        wb.append("</sheets></workbook>")
        rels.append("</Relationships>")
        z.writestr("xl/workbook.xml", "".join(wb))
        z.writestr("xl/_rels/workbook.xml.rels", "".join(rels))
    return buf.getvalue()


def test_csv_yields_one_table():
    tables = extract_tables("a.csv", b"No,\xed\x95\xad\xeb\xaa\xa9\n1,\xea\xb0\x80\n")
    assert len(tables) == 1
    assert tables[0].rows[0] == ["No", "항목"]


def test_xlsx_yields_one_table_per_sheet_labelled_by_name():
    """IS22 는 시트가 30여 개다. 이름이 없으면 검토자가 고를 수 없다."""
    data = _xlsx({"B-1 (요건BTP)": [["No", "항목"], ["1", "가"]],
                  "B-2 (요건1012)": [["ID", "Evaluation Item"], ["VR15-01", "나"]]})
    tables = extract_tables("c.xlsx", data)
    assert [t.label for t in tables] == ["B-1 (요건BTP)", "B-2 (요건1012)"]
    assert tables[1].rows[1] == ["VR15-01", "나"]


def test_empty_sheets_are_dropped():
    data = _xlsx({"빈시트": [], "본문": [["No", "항목"], ["1", "가"]]})
    assert [t.label for t in extract_tables("c.xlsx", data)] == ["본문"]


def test_unsupported_extension_is_rejected():
    with pytest.raises(UnsupportedChecklistFormat):
        extract_tables("a.hwp", b"x")


def _xlsx_with_sparse_row() -> bytes:
    """B2 를 XML 에서 아예 빼서(엑셀이 빈 셀을 생략하는 실제 동작) 만든 xlsx.

    _xlsx() 헬퍼는 항상 모든 셀을 쓰기 때문에 이 경우를 재현하지 못한다.
    r 속성(A1, C2 등)만으로 실제 열 위치를 알 수 있어야 한다.
    """
    NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    R = ('xmlns:r="http://schemas.openxmlformats.org/officeDocument/'
         '2006/relationships"')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        wb = (f'<workbook {NS} {R}><sheets>'
              '<sheet name="s" sheetId="1" r:id="rId1"/>'
              '</sheets></workbook>')
        rels = ('<Relationships xmlns="http://schemas.openxmlformats.org/'
                'package/2006/relationships">'
                '<Relationship Id="rId1" Target="worksheets/sheet1.xml" '
                'Type="x"/></Relationships>')
        header_row = (
            '<row r="1">'
            '<c r="A1" t="inlineStr"><is><t>No</t></is></c>'
            '<c r="B1" t="inlineStr"><is><t>항목</t></is></c>'
            '<c r="C1" t="inlineStr"><is><t>비고</t></is></c>'
            '</row>')
        # B2 가 비어서 <c r="B2">가 통째로 없다 — 실제 엑셀 산출물의 동작.
        data_row = (
            '<row r="2">'
            '<c r="A2" t="inlineStr"><is><t>1</t></is></c>'
            '<c r="C2" t="inlineStr"><is><t>주의</t></is></c>'
            '</row>')
        sheet = (f'<worksheet {NS}><sheetData>{header_row}{data_row}'
                 '</sheetData></worksheet>')
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


def test_sparse_row_keeps_later_columns_aligned():
    """B2 가 생략돼도 C2 값("주의")은 열 인덱스 2 에 남아야 한다.

    r 속성을 무시하면 "주의"가 인덱스 1(B 열, 항목)로 밀려 들어간다.
    """
    tables = extract_tables("c.xlsx", _xlsx_with_sparse_row())
    assert tables[0].rows[1] == ["1", "", "주의"]


def test_non_zip_xlsx_raises_domain_exception():
    """zip 이 아닌 바이트를 .xlsx 로 주면 zipfile.BadZipFile 이 아니라
    도메인 예외(UnsupportedChecklistFormat)로 감싸져야 한다."""
    with pytest.raises(UnsupportedChecklistFormat):
        extract_tables("broken.xlsx", b"this is not a zip file at all")


def test_pdf_tables_are_labelled_with_the_page(tmp_path):
    """실측: IS16 은 쪽마다 표가 있고 쪽마다 헤더가 다르다."""
    pytest.importorskip("fpdf")
    pytest.importorskip("pdfplumber")
    from fpdf import FPDF
    doc = FPDF()
    doc.add_page()
    doc.set_font("helvetica", size=11)
    with doc.table() as table:
        for r in (("No", "Item"), ("1", "check bookmarks")):
            row = table.row()
            for c in r:
                row.cell(c)
    tables = extract_tables("a.pdf", bytes(doc.output()))
    assert tables and tables[0].label.startswith("1쪽")
    assert tables[0].rows[0] == ["No", "Item"]


# --- 이어지는 표 병합 -------------------------------------------------------
# PDF 는 표가 쪽을 넘으면 쪽마다 따로 뽑힌다. 이어지는 쪽은 헤더가 없어서
# (실측: IS16 3쪽) 항목 열을 못 맞히고 항목이 통째로 날아간다. 자기 헤더가
# 없고 열 수가 같으면 앞 표에 붙인다.
from modules.preset.parse import (Table, _has_own_header,
                                       _merge_continuations)

_HDR = ["No", "위치", "체크리스트 항목", "비고"]


def test_a_row_with_an_item_text_keyword_is_an_own_header():
    assert _has_own_header([_HDR, ["1", "전체", "책갈피 확인", ""]]) is True


def test_a_table_of_pure_data_has_no_own_header():
    """실측: IS16 3쪽. 'PNS No.' 의 'No' 가 우연히 걸려도 항목 열은 못 찾는다."""
    rows = [["53", "전체", "단어·약어 통일", ""],
            ["54", "전체", "머리글 11 pt(부록명·PNS No.)", ""]]
    assert _has_own_header(rows) is False


def test_headerless_table_merges_into_the_previous_one():
    prev = Table(label="2쪽", rows=[_HDR, ["1", "전체", "책갈피", ""]])
    cont = Table(label="3쪽", rows=[["53", "전체", "단어 통일", ""],
                                    ["54", "전체", "표 정렬", ""]])
    merged = _merge_continuations([prev, cont])
    assert len(merged) == 1
    assert [r[0] for r in merged[0].rows] == ["No", "1", "53", "54"]


def test_a_table_with_its_own_header_stays_separate():
    """1쪽(PDF검토)과 2쪽(내부검토)은 각자 헤더가 있어 다른 체크리스트다."""
    a = Table(label="1쪽", rows=[["No", "종류", "체크리스트 항목", "적용"],
                                 ["1", "스캔", "서명 스캔", "전체"]])
    b = Table(label="2쪽", rows=[_HDR, ["1", "전체", "책갈피", ""]])
    assert len(_merge_continuations([a, b])) == 2


def test_a_headerless_table_of_different_width_does_not_merge():
    """열 수가 다르면 이어지는 표가 아니다 — 엉뚱한 데 붙이면 열이 어긋난다."""
    prev = Table(label="p", rows=[_HDR, ["1", "전체", "책갈피", ""]])
    cont = Table(label="q", rows=[["a", "b"], ["c", "d"]])
    assert len(_merge_continuations([prev, cont])) == 2


def test_real_is16_merges_page3_into_the_internal_review_checklist():
    pytest.importorskip("pdfplumber")
    from conftest import sample
    p = sample("IS16-CHK-0000(내부검토_체크리스트).pdf")
    if p is None:
        pytest.skip("실문서 없음")
    tables = extract_tables(p.name, p.read_bytes())
    # 1쪽(PDF검토)은 독립, 2·3쪽(내부검토)은 하나로 → 표 2개
    assert len(tables) == 2
    from modules.preset.parse import build_items, find_header, guess_columns
    big = tables[1]
    h = find_header(big.rows)
    items = build_items(big.rows, h, guess_columns(big.rows[h]))
    # 2쪽 52 + 3쪽 45 근처. 최소한 3쪽 것(53번 이후)이 포함돼야 한다.
    assert len(items) > 90
    assert any("단어·약어 통일" in i.text for i in items)   # 3쪽 첫 항목
