"""HWPX 로더 테스트. 실제 파일 없이 최소 HWPX(ZIP+XML)를 만들어 검증한다."""
import zipfile

import pytest

from modules.doc_parser import UnsupportedFormatError, load_document
from modules.doc_parser import HwpxLoader
from modules.doc_parser import normalize

NS = (
    'xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph" '
    'xmlns:hh="http://www.hancom.co.kr/hwpml/2011/head" '
    'xmlns:hs="http://www.hancom.co.kr/hwpml/2011/section"'
)

# paraPr 27 = 개요1(level 0), 28 = 개요2(level 1), 49 = 불릿(제목 아님)
HEADER = f"""<?xml version="1.0" encoding="UTF-8"?>
<hh:head {NS}>
  <hh:paraPr id="9"><hh:heading type="NONE" level="0"/></hh:paraPr>
  <hh:paraPr id="27"><hh:heading type="OUTLINE" level="0"/></hh:paraPr>
  <hh:paraPr id="28"><hh:heading type="OUTLINE" level="1"/></hh:paraPr>
  <hh:paraPr id="49"><hh:heading type="BULLET" level="0"/></hh:paraPr>
</hh:head>"""


def _p(text, para_pr="9"):
    return (f'<hp:p paraPrIDRef="{para_pr}"><hp:run><hp:t>{text}</hp:t>'
            "</hp:run></hp:p>")


def _cell(text):
    return f"<hp:tc><hp:subList>{_p(text)}</hp:subList></hp:tc>"


def _row(*cells):
    return "<hp:tr>" + "".join(_cell(c) for c in cells) + "</hp:tr>"


def _section(body):
    return f'<?xml version="1.0" encoding="UTF-8"?><hs:sec {NS}>{body}</hs:sec>'


def _hwpx(tmp_path, body, name="doc.hwpx"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/header.xml", HEADER)
        z.writestr("Contents/section0.xml", _section(body))
    return path


def test_outline_paragraphs_become_markdown_headings(tmp_path):
    path = _hwpx(tmp_path, _p("개요", "27") + _p("목적", "28") + _p("본문 문장"))
    text = HwpxLoader().load(path).text
    assert "# 개요" in text
    assert "## 목적" in text
    assert "본문 문장" in text


def test_bullet_is_not_a_heading(tmp_path):
    """BULLET/NUMBER는 목록이지 제목이 아니다. #를 붙이면 섹션 트리가 오염된다."""
    path = _hwpx(tmp_path, _p("항목 하나", "49"))
    text = HwpxLoader().load(path).text
    assert "항목 하나" in text
    assert "#" not in text


def test_table_rows_keep_cells_separate(tmp_path):
    """표 셀이 이어붙으면 'ID' + 'RQ-001' → 'IDRQ-001'이 된다. 실제로 겪은 버그."""
    body = "<hp:tbl>" + _row("ID", "설명") + _row("RQ-001", "로그인 기능") + "</hp:tbl>"
    text = HwpxLoader().load(_hwpx(tmp_path, body)).text
    assert "| ID | 설명 |" in text
    assert "| RQ-001 | 로그인 기능 |" in text
    assert "IDRQ-001" not in text


def test_table_nested_in_paragraph_does_not_merge_into_it(tmp_path):
    """표는 hp:p 안에 중첩된다. 문단 텍스트로 빨려들어가면 안 된다."""
    body = ('<hp:p paraPrIDRef="9"><hp:run><hp:t>표 앞 문장</hp:t>'
            "<hp:tbl>" + _row("RQ-002", "결제 기능") + "</hp:tbl>"
            "</hp:run></hp:p>")
    lines = [ln for ln in HwpxLoader().load(_hwpx(tmp_path, body)).text.splitlines() if ln]
    assert "표 앞 문장" in lines
    assert "| RQ-002 | 결제 기능 |" in lines
    assert not any("표 앞 문장RQ-002" in ln for ln in lines)


def test_heading_inside_table_cell_is_not_promoted(tmp_path):
    """셀 안 문단이 개요 스타일이어도 표 행 안에서 #가 되면 안 된다."""
    body = "<hp:tbl><hp:tr>" + f"<hp:tc><hp:subList>{_p('개요', '27')}</hp:subList></hp:tc>" \
           + "</hp:tr></hp:tbl>"
    text = HwpxLoader().load(_hwpx(tmp_path, body)).text
    assert "| 개요 |" in text
    assert "# 개요" not in text


def test_id_and_description_land_on_one_line(tmp_path):
    """내용 대조가 줄 단위라, 요건 ID와 설명이 같은 줄에 있어야 한다."""
    body = "<hp:tbl>" + _row("RQ-003", "3초 이내 응답") + "</hp:tbl>"
    doc = normalize(HwpxLoader().load(_hwpx(tmp_path, body)))
    from modules.agent_trace import extract_id_statements
    stmt = extract_id_statements(doc, r"RQ-\d{3}")["RQ-003"]
    assert "3초 이내 응답" in stmt.text


def test_multiple_sections_are_read_in_order(tmp_path):
    path = tmp_path / "multi.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/header.xml", HEADER)
        z.writestr("Contents/section0.xml", _section(_p("첫째")))
        z.writestr("Contents/section1.xml", _section(_p("둘째")))
    text = HwpxLoader().load(path).text
    assert text.index("첫째") < text.index("둘째")


def test_missing_header_still_reads_body(tmp_path):
    """header.xml이 없으면 제목 정보만 잃고, 본문은 읽을 수 있어야 한다."""
    path = tmp_path / "noheader.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/section0.xml", _section(_p("제목", "27")))
    text = HwpxLoader().load(path).text
    assert "제목" in text and "#" not in text


def test_not_a_zip_is_a_clear_error(tmp_path):
    path = tmp_path / "fake.hwpx"
    path.write_bytes(b"this is not a zip")
    with pytest.raises(ValueError, match="ZIP이 아님"):
        HwpxLoader().load(path)


def test_zip_without_body_is_a_clear_error(tmp_path):
    path = tmp_path / "empty.hwpx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
    with pytest.raises(ValueError, match="본문"):
        HwpxLoader().load(path)


def test_registry_dispatches_hwpx(tmp_path):
    path = _hwpx(tmp_path, _p("등록 확인"))
    assert load_document(path).meta["format"] == "hwpx"


# (구 test_legacy_hwp_gives_conversion_advice 제거: .hwp는 이제 H2Orestart로 변환해
#  읽는다 — 미지원 안내가 아니다. HwpLoader 동작은 tests/test_ingestion_hwp.py 가 커버.)


def test_unknown_extension_still_unsupported(tmp_path):
    path = tmp_path / "x.zip"
    path.write_bytes(b"PK")
    with pytest.raises(UnsupportedFormatError):
        load_document(path)
