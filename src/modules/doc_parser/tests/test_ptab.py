"""w:ptab(절대위치 탭) 치환.

실측 근거는 ptab.py 머리말에 있다. 여기서는 그 규칙이 지켜지는지만 본다 —
LibreOffice 없이 돌아야 하므로 변환은 하지 않고 만들어진 XML 을 읽는다.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

from modules.doc_parser.ptab import rewrite_ptabs, style_tab_stops

# A4(11906) - 좌우 여백 567 씩 = 본문 폭 10772 twip
_DOC = ('<?xml version="1.0"?><w:document xmlns:w="w"><w:body><w:sectPr>'
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="567" w:right="567" w:bottom="567" w:left="567"/>'
        "</w:sectPr></w:body></w:document>")
_TEXT_WIDTH = 11906 - 567 - 567

# 스타일 a5 는 Word 기본 머리글 — 기본 여백(1인치) 기준의 낡은 정지를 갖고 있다.
_STYLES = ('<?xml version="1.0"?><w:styles xmlns:w="w">'
           '<w:style w:type="paragraph" w:styleId="a5"><w:name w:val="header"/>'
           '<w:pPr><w:tabs><w:tab w:val="center" w:pos="4513"/>'
           '<w:tab w:val="right" w:pos="9026"/></w:tabs></w:pPr></w:style>'
           "</w:styles>")


def _header(inner: str) -> str:
    return ('<?xml version="1.0"?><w:hdr xmlns:w="w" xmlns:w14="w14">'
            f"{inner}</w:hdr>")


_PARA_WITH_PTAB = (
    '<w:p w14:paraId="1"><w:pPr><w:pStyle w:val="a5"/></w:pPr>'
    "<w:r><w:t>의뢰번호: SST-26-999</w:t></w:r>"
    '<w:r><w:ptab w:relativeTo="margin" w:alignment="right" w:leader="none"/></w:r>'
    "<w:r><w:t>성적서번호: SST-26-999-C01</w:t></w:r></w:p>"
)


def _docx(tmp_path: Path, parts: dict[str, str], name: str = "in.docx") -> Path:
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        for n, body in parts.items():
            z.writestr(n, body)
    return path


def _read(path: Path, name: str) -> str:
    with zipfile.ZipFile(path) as z:
        return z.read(name).decode("utf-8")


def test_right_ptab_becomes_tab_at_text_width(tmp_path: Path) -> None:
    """오른쪽 절대탭 → 본문 폭 위치의 right 정지 + 탭 문자.

    스타일의 낡은 right@9026 을 쓰면 87pt 짧게 붙는다(ptab.py 실측). 여백에서
    계산한 10772 여야 한다.
    """
    src = _docx(tmp_path, {"word/document.xml": _DOC,
                           "word/styles.xml": _STYLES,
                           "word/header2.xml": _header(_PARA_WITH_PTAB)})
    dest = tmp_path / "out.docx"
    assert rewrite_ptabs(src, dest) == 1

    xml = _read(dest, "word/header2.xml")
    assert "<w:ptab" not in xml, "절대탭이 남아 있으면 LibreOffice 가 또 무시한다"
    assert "<w:tab/>" in xml, "탭 문자가 없으면 간격이 안 생긴다"
    assert f'<w:tab w:val="right" w:pos="{_TEXT_WIDTH}"/>' in xml


def test_inherited_stops_are_cleared(tmp_path: Path) -> None:
    """스타일이 물려준 앞쪽 정지를 지운다.

    안 지우면 탭이 center@4513 에서 멈춰 성적서번호가 쪽 한가운데에 남는다 —
    실측으로 그랬다.
    """
    src = _docx(tmp_path, {"word/document.xml": _DOC,
                           "word/styles.xml": _STYLES,
                           "word/header2.xml": _header(_PARA_WITH_PTAB)})
    dest = tmp_path / "out.docx"
    rewrite_ptabs(src, dest)
    xml = _read(dest, "word/header2.xml")

    assert '<w:tab w:val="clear" w:pos="4513"/>' in xml
    assert '<w:tab w:val="clear" w:pos="9026"/>' in xml
    # 우리 정지는 지우면 안 된다.
    assert f'<w:tab w:val="clear" w:pos="{_TEXT_WIDTH}"/>' not in xml


def test_center_ptab_goes_to_half_width(tmp_path: Path) -> None:
    para = ('<w:p><w:pPr><w:pStyle w:val="a5"/></w:pPr><w:r><w:t>왼쪽</w:t></w:r>'
            '<w:r><w:ptab w:relativeTo="margin" w:alignment="center"/></w:r>'
            "<w:r><w:t>가운데</w:t></w:r></w:p>")
    src = _docx(tmp_path, {"word/document.xml": _DOC,
                           "word/styles.xml": _STYLES,
                           "word/header2.xml": _header(para)})
    dest = tmp_path / "out.docx"
    rewrite_ptabs(src, dest)
    xml = _read(dest, "word/header2.xml")
    assert f'<w:tab w:val="center" w:pos="{_TEXT_WIDTH // 2}"/>' in xml


def test_document_without_ptab_is_copied_untouched(tmp_path: Path) -> None:
    """절대탭이 없으면 한 바이트도 안 바꾼다. 옛 문서를 괜히 건드리지 않는다."""
    plain = _header('<w:p><w:r><w:t>머릿말</w:t></w:r></w:p>')
    src = _docx(tmp_path, {"word/document.xml": _DOC,
                           "word/styles.xml": _STYLES,
                           "word/header2.xml": plain})
    dest = tmp_path / "out.docx"
    assert rewrite_ptabs(src, dest) == 0
    assert dest.read_bytes() == src.read_bytes()


def test_body_is_never_touched(tmp_path: Path) -> None:
    """본문의 절대탭은 그대로 둔다.

    본문은 문단마다 탭 정지가 제각각이라, 머릿말과 같은 규칙으로 고치면 멀쩡한
    줄이 밀린다. 지금 문제가 된 것은 머릿말·꼬리말이다.
    """
    body_doc = _DOC.replace("<w:body>",
                            '<w:body><w:p><w:r><w:ptab w:alignment="right"/></w:r></w:p>')
    src = _docx(tmp_path, {"word/document.xml": body_doc,
                           "word/styles.xml": _STYLES,
                           "word/header2.xml": _header(_PARA_WITH_PTAB)})
    dest = tmp_path / "out.docx"
    rewrite_ptabs(src, dest)
    assert "<w:ptab" in _read(dest, "word/document.xml")


def test_unreadable_page_size_changes_nothing(tmp_path: Path) -> None:
    """쪽 규격을 못 읽으면 손대지 않는다. 지어낸 폭으로 탭을 놓으면 더 나빠진다."""
    src = _docx(tmp_path, {"word/document.xml": '<?xml version="1.0"?><w:document/>',
                           "word/styles.xml": _STYLES,
                           "word/header2.xml": _header(_PARA_WITH_PTAB)})
    dest = tmp_path / "out.docx"
    assert rewrite_ptabs(src, dest) == 0
    assert "<w:ptab" in _read(dest, "word/header2.xml")


def test_style_chain_with_a_cycle_terminates() -> None:
    """basedOn 이 서로를 가리키는 문서가 실제로 있다. 멈춰야 한다."""
    xml = ('<w:styles xmlns:w="w">'
           '<w:style w:styleId="a"><w:basedOn w:val="b"/>'
           '<w:pPr><w:tabs><w:tab w:val="right" w:pos="100"/></w:tabs></w:pPr></w:style>'
           '<w:style w:styleId="b"><w:basedOn w:val="a"/>'
           '<w:pPr><w:tabs><w:tab w:val="center" w:pos="200"/></w:tabs></w:pPr></w:style>'
           "</w:styles>")
    stops = style_tab_stops(xml)
    assert sorted(stops["a"]) == [100, 200]


def test_style_clear_entries_are_not_inherited() -> None:
    """스타일이 `clear` 로 지운 정지는 물려받지 않는다 — 지운 것을 되살리면 안 된다."""
    xml = ('<w:styles xmlns:w="w"><w:style w:styleId="a">'
           '<w:pPr><w:tabs><w:tab w:val="clear" w:pos="4513"/>'
           '<w:tab w:val="right" w:pos="9026"/></w:tabs></w:pPr></w:style></w:styles>')
    assert style_tab_stops(xml)["a"] == [9026]


def test_paragraph_own_stops_are_cleared_too(tmp_path: Path) -> None:
    """문단이 직접 가진 낡은 정지도 지운다. 스타일만 지우면 그쪽에 걸린다."""
    para = ('<w:p><w:pPr><w:pStyle w:val="a5"/>'
            '<w:tabs><w:tab w:val="center" w:pos="3000"/></w:tabs></w:pPr>'
            "<w:r><w:t>왼쪽</w:t></w:r>"
            '<w:r><w:ptab w:relativeTo="margin" w:alignment="right"/></w:r>'
            "<w:r><w:t>오른쪽</w:t></w:r></w:p>")
    src = _docx(tmp_path, {"word/document.xml": _DOC,
                           "word/styles.xml": _STYLES,
                           "word/header2.xml": _header(para)})
    dest = tmp_path / "out.docx"
    rewrite_ptabs(src, dest)
    xml = _read(dest, "word/header2.xml")
    assert '<w:tab w:val="clear" w:pos="3000"/>' in xml
    assert f'<w:tab w:val="right" w:pos="{_TEXT_WIDTH}"/>' in xml


def test_all_zip_entries_survive(tmp_path: Path) -> None:
    """고친 파트만 갈아끼우고 나머지는 그대로 남아야 한다 — 하나라도 빠지면
    docx 가 열리지 않는다."""
    parts = {"word/document.xml": _DOC, "word/styles.xml": _STYLES,
             "word/header2.xml": _header(_PARA_WITH_PTAB),
             "[Content_Types].xml": "<Types/>", "word/media/x.png": "PNG"}
    src = _docx(tmp_path, parts)
    dest = tmp_path / "out.docx"
    rewrite_ptabs(src, dest)
    with zipfile.ZipFile(dest) as z:
        assert set(z.namelist()) == set(parts)
        assert z.read("word/media/x.png") == b"PNG"


def test_multiple_ptabs_in_one_paragraph(tmp_path: Path) -> None:
    """가운데·오른쪽이 이어지면 정지도 탭 문자도 둘이다."""
    para = ('<w:p><w:pPr><w:pStyle w:val="a5"/></w:pPr><w:r><w:t>왼</w:t></w:r>'
            '<w:r><w:ptab w:relativeTo="margin" w:alignment="center"/></w:r>'
            '<w:r><w:t>중</w:t></w:r>'
            '<w:r><w:ptab w:relativeTo="margin" w:alignment="right"/></w:r>'
            '<w:r><w:t>우</w:t></w:r></w:p>')
    src = _docx(tmp_path, {"word/document.xml": _DOC,
                           "word/styles.xml": _STYLES,
                           "word/header2.xml": _header(para)})
    dest = tmp_path / "out.docx"
    assert rewrite_ptabs(src, dest) == 2
    xml = _read(dest, "word/header2.xml")
    assert len(re.findall(r"<w:tab/>", xml)) == 2
    assert f'<w:tab w:val="center" w:pos="{_TEXT_WIDTH // 2}"/>' in xml
    assert f'<w:tab w:val="right" w:pos="{_TEXT_WIDTH}"/>' in xml


# ── 구역(sectPr)마다 여백이 다른 문서 ──────────────────────────────────
# 실측: 문서 표준화 가이드는 구역이 16개였고 첫 구역만 좌 85pt, 나머지는 71pt.
# 첫 구역 폭으로 탭을 놓으면 나머지 쪽 꼬리말이 13pt 왼쪽으로 밀린다.

_RELS = ('<Relationships><Relationship Id="rId1" Target="header1.xml"/>'
         '<Relationship Id="rId2" Target="header2.xml"/></Relationships>')


def _multi_section_doc(second_left: int) -> str:
    """구역 둘. 첫 구역은 좌여백 1700, 둘째는 인자로 받는다."""
    return (
        '<?xml version="1.0"?><w:document xmlns:w="w" xmlns:r="r"><w:body>'
        '<w:p><w:pPr><w:sectPr>'
        '<w:headerReference r:id="rId1" w:type="default"/>'
        '<w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:right="567" w:left="1700"/>'
        "</w:sectPr></w:pPr></w:p>"
        "<w:sectPr>"
        '<w:headerReference r:id="rId2" w:type="default"/>'
        '<w:pgSz w:w="11906" w:h="16838"/>'
        f'<w:pgMar w:right="567" w:left="{second_left}"/>'
        "</w:sectPr></w:body></w:document>")


def test_each_part_uses_its_own_section_width(tmp_path: Path) -> None:
    """머릿말마다 자기 구역의 폭을 쓴다. 첫 구역 폭을 모두에 쓰면 밀린다."""
    doc = _multi_section_doc(second_left=567)
    src = _docx(tmp_path, {"word/document.xml": doc,
                           "word/_rels/document.xml.rels": _RELS,
                           "word/styles.xml": _STYLES,
                           "word/header1.xml": _header(_PARA_WITH_PTAB),
                           "word/header2.xml": _header(_PARA_WITH_PTAB)})
    dest = tmp_path / "out.docx"
    rewrite_ptabs(src, dest)

    assert f'w:pos="{11906 - 1700 - 567}"' in _read(dest, "word/header1.xml")
    assert f'w:pos="{11906 - 567 - 567}"' in _read(dest, "word/header2.xml")


def test_part_shared_by_sections_of_different_width_is_left_alone(tmp_path: Path) -> None:
    """한 파트가 폭이 다른 구역 여럿에 걸리면 손대지 않는다.

    어느 쪽에 맞출지 알 수 없다. 반쯤 맞히면 고치기 전보다 나빠질 수 있다 —
    실제로 그 회귀를 냈다.
    """
    shared = _RELS.replace('Id="rId2" Target="header2.xml"',
                           'Id="rId2" Target="header1.xml"')
    src = _docx(tmp_path, {"word/document.xml": _multi_section_doc(second_left=567),
                           "word/_rels/document.xml.rels": shared,
                           "word/styles.xml": _STYLES,
                           "word/header1.xml": _header(_PARA_WITH_PTAB)})
    dest = tmp_path / "out.docx"
    rewrite_ptabs(src, dest)
    xml = _read(dest, "word/header1.xml")
    # 폴백(문서 첫 구역 폭)으로 가지 말고, 두 구역 중 어느 폭도 쓰지 않아야 한다.
    assert f'w:pos="{11906 - 1700 - 567}"' not in xml
    assert f'w:pos="{11906 - 567 - 567}"' not in xml or "<w:ptab" in xml


def test_inherited_part_across_different_widths_is_left_alone(tmp_path: Path) -> None:
    """참조를 생략한 다음 구역도 앞 구역의 머릿말을 물려받는다."""
    doc = _multi_section_doc(second_left=567).replace(
        '<w:headerReference r:id="rId2" w:type="default"/>', "")
    src = _docx(tmp_path, {"word/document.xml": doc,
                           "word/_rels/document.xml.rels": _RELS,
                           "word/styles.xml": _STYLES,
                           "word/header1.xml": _header(_PARA_WITH_PTAB)})
    dest = tmp_path / "out.docx"

    assert rewrite_ptabs(src, dest) == 0
    assert "<w:ptab" in _read(dest, "word/header1.xml")


def test_검증하지_않은_ptab_형태는_원문대로_둔다(tmp_path: Path) -> None:
    para = ('<w:p><w:r><w:ptab w:relativeTo="indent" w:alignment="right"/>'
            '</w:r><w:r><w:ptab w:relativeTo="margin" w:alignment="left"/>'
            "</w:r></w:p>")
    src = _docx(tmp_path, {"word/document.xml": _DOC,
                           "word/styles.xml": _STYLES,
                           "word/header2.xml": _header(para)})
    dest = tmp_path / "out.docx"

    assert rewrite_ptabs(src, dest) == 0
    assert _read(dest, "word/header2.xml") == _header(para)
