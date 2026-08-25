"""DOCX 로더 테스트. 실제 파일 없이 최소 DOCX(ZIP+XML)를 만들어 검증한다."""
import zipfile

import pytest

from modules.doc_parser import load_document
from modules.doc_parser import DocxLoader
from modules.doc_parser import normalize

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = f'xmlns:w="{W}"'

# Heading1 = 개요1(level 0), Heading2 = 개요2(level 1), ListParagraph = 제목 아님
STYLES = f"""<?xml version="1.0" encoding="UTF-8"?>
<w:styles {NS}>
  <w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2">
    <w:name w:val="heading 2"/><w:pPr><w:outlineLvl w:val="1"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="ListParagraph">
    <w:name w:val="List Paragraph"/>
  </w:style>
</w:styles>"""


def _runs(*texts):
    return "".join(f"<w:r><w:t>{t}</w:t></w:r>" for t in texts)


def _p(*texts, style=None):
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{ppr}{_runs(*texts)}</w:p>"


def _cell(*paras):
    return "<w:tc>" + "".join(paras) + "</w:tc>"


def _row(*cells):
    return "<w:tr>" + "".join(_cell(c) for c in cells) + "</w:tr>"


def _tbl(*rows):
    return "<w:tbl>" + "".join(rows) + "</w:tbl>"


def _sdt(inner):
    """콘텐츠 컨트롤(w:sdt)로 감싼다. 워드 양식 문서의 값 칸이 이 모양이다."""
    return ('<w:sdt><w:sdtPr><w:alias w:val="값"/></w:sdtPr><w:sdtEndPr/>'
            f"<w:sdtContent>{inner}</w:sdtContent></w:sdt>")


def _docx(tmp_path, body, name="doc.docx", styles=STYLES, document=True):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        if document:
            z.writestr(
                "word/document.xml",
                f'<?xml version="1.0" encoding="UTF-8"?><w:document {NS}>'
                f"<w:body>{body}</w:body></w:document>",
            )
        if styles is not None:
            z.writestr("word/styles.xml", styles)
    return path


def _load(tmp_path, body, **kw):
    return DocxLoader().load(_docx(tmp_path, body, **kw))


def test_스타일이_개요면_마크다운_제목이_된다(tmp_path):
    body = _p("개요", style="Heading1") + _p("본문이다.") + _p("배경", style="Heading2")
    lines = _load(tmp_path, body).text.splitlines()

    assert "# 개요" in lines
    assert "## 배경" in lines
    assert "본문이다." in lines


def test_목록_스타일은_제목이_아니다(tmp_path):
    body = _p("항목 하나", style="ListParagraph")
    text = _load(tmp_path, body).text

    assert "항목 하나" in text
    assert "#" not in text


def test_문단_직접_지정한_개요수준이_스타일을_이긴다(tmp_path):
    # Word는 문단에 직접 outlineLvl을 박을 수 있다. 이게 스타일보다 우선이다.
    body = (
        f'<w:p><w:pPr><w:pStyle w:val="Normal"/><w:outlineLvl w:val="1"/></w:pPr>'
        f"{_runs('직접 지정 제목')}</w:p>"
    )
    assert "## 직접 지정 제목" in _load(tmp_path, body).text


def test_한_단어가_런으로_쪼개져도_이어붙인다(tmp_path):
    # Word는 편집 이력 때문에 한 단어를 런 여러 개로 쪼갠다.
    # 공백을 끼워넣으면 요건 ID가 깨져 추적성 검사가 통째로 무너진다.
    body = _p("RQ-SFR", "-PR-01", "-001: 로그인")
    assert "RQ-SFR-PR-01-001: 로그인" in _load(tmp_path, body).text


def test_표는_문단에_붙지_않고_파이프_줄로_나온다(tmp_path):
    body = _p("요구사항", style="Heading1") + _tbl(
        _row(_p("ID"), _p("설명")),
        _row(_p("RQ-SFR-PR-01-001"), _p("사용자는 로그인할 수 있어야 한다.")),
    )
    lines = _load(tmp_path, body).text.splitlines()

    assert "| ID | 설명 |" in lines
    assert "| RQ-SFR-PR-01-001 | 사용자는 로그인할 수 있어야 한다. |" in lines
    # 셀 텍스트가 제목에 이어붙으면 안 된다
    assert "# 요구사항" in lines


def test_셀_안_여러_문단은_한_줄로_합친다(tmp_path):
    body = _tbl(_row(_p("첫 줄") + _p("둘째 줄"), _p("설명")))
    assert "| 첫 줄 둘째 줄 | 설명 |" in _load(tmp_path, body).text.splitlines()


def test_셀_안_파이프는_치환한다(tmp_path):
    body = _tbl(_row(_p("a|b"), _p("c")))
    assert "| a/b | c |" in _load(tmp_path, body).text.splitlines()


def test_표_안의_문단은_제목이_되지_않는다(tmp_path):
    body = _tbl(_row(_p("셀 제목", style="Heading1"), _p("값")))
    lines = _load(tmp_path, body).text.splitlines()

    assert "| 셀 제목 | 값 |" in lines
    assert not any(line.startswith("#") for line in lines)


def test_콘텐츠_컨트롤로_감싼_셀도_읽는다(tmp_path):
    # 워드 양식 문서는 값 칸을 콘텐츠 컨트롤로 감싼다. 실문서(시험성적서 갑지)의
    # w:tr 직접 자식이 [trPr, tc(라벨), sdt(값)] 이라, 직접 자식만 훑으면 값이
    # 통째로 사라진다 — 라벨만 남아 "기관명이 비었다"는 거짓 지적이 된다.
    body = _tbl("<w:tr>" + _cell(_p("기관명"))
                + _sdt(_cell(_p("한국소프트웨어시험연구소"))) + "</w:tr>")

    assert "| 기관명 | 한국소프트웨어시험연구소 |" in _load(tmp_path, body).text.splitlines()


def test_콘텐츠_컨트롤로_감싼_행도_읽는다(tmp_path):
    # w:sdt 는 행 하나를 통째로 감쌀 수도 있다(w:tbl 의 직접 자식).
    body = _tbl(_sdt(_row(_p("의뢰번호"), _p("SST-26-999"))))

    assert "| 의뢰번호 | SST-26-999 |" in _load(tmp_path, body).text.splitlines()


def test_삭제된_텍스트는_읽지_않는다(tmp_path):
    # 변경내용 추적(w:delText)은 지워진 글자다. 읽으면 없는 내용을 검토하게 된다.
    body = (
        "<w:p>"
        "<w:del><w:r><w:delText>3초 이내</w:delText></w:r></w:del>"
        "<w:ins><w:r><w:t>5초 이내</w:t></w:r></w:ins>"
        "</w:p>"
    )
    text = _load(tmp_path, body).text

    assert "5초 이내" in text
    assert "3초" not in text


def test_탭은_공백이_된다(tmp_path):
    body = f"<w:p><w:r><w:t>ID</w:t><w:tab/><w:t>설명</w:t></w:r></w:p>"
    assert "ID 설명" in _load(tmp_path, body).text


def test_확장자로_라우팅된다(tmp_path):
    path = _docx(tmp_path, _p("본문", style="Heading1"))
    doc = load_document(path)

    assert doc.meta["format"] == "docx"
    assert "# 본문" in doc.text


def test_normalize가_섹션으로_인식한다(tmp_path):
    body = _p("개요", style="Heading1") + _p("본문이다.") + _p("요구사항", style="Heading1")
    doc = normalize(_load(tmp_path, body))

    titles = [s.title for s in doc.sections]
    assert "개요" in titles
    assert "요구사항" in titles


def test_스타일_파일이_없어도_읽는다(tmp_path):
    # styles.xml이 없으면 제목 정보만 잃고 본문은 살린다.
    text = _load(tmp_path, _p("본문", style="Heading1"), styles=None).text
    assert "본문" in text


def test_zip이_아니면_알려준다(tmp_path):
    path = tmp_path / "fake.docx"
    path.write_text("이건 워드가 아니다", encoding="utf-8")

    with pytest.raises(ValueError, match="ZIP"):
        DocxLoader().load(path)


def test_본문이_없으면_알려준다(tmp_path):
    path = _docx(tmp_path, "", document=False)

    with pytest.raises(ValueError, match="word/document.xml"):
        DocxLoader().load(path)
