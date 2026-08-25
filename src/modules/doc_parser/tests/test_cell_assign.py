"""find_tables() 셀 텍스트 배정 — 단어는 자르지 않는다(§4-0 이슈㉑).

예전 clip 추출은 셀 경계에 걸친 단어의 텍스트를 글자 단위로 잘라 양쪽 칸에
조각을 남겼다("detail" → "d il"). 실측(SKN56_CDMS_RVVR_Rev05.pdf 평가표)에서
그 조각이 검토 본문에 실려 표현 점검이 가짜 오타를 수십 건 지적했다.
지금은 단어 중심점이 든 칸에 통째로 배정한다 — 이 계약이 깨지면 여기가 죽는다.
"""
import fitz

from modules.doc_parser.pdf_backend import _pymupdf_cell_text


def test_경계에_걸친_단어는_한_칸에_통째로_들어간다():
    doc = fitz.open()
    page = doc.new_page(width=300, height=100)
    page.insert_text((10, 50), "sufficient detail shown")

    det = [w for w in page.get_text("words") if w[4] == "detail"][0]
    mid = (det[0] + det[2]) / 2 + 2   # 경계가 "detail" 한가운데를 지난다
    page_h = float(page.rect.height)
    left = _pymupdf_cell_text(page, (0, 0, mid, 100), page_h)
    right = _pymupdf_cell_text(page, (mid, 0, 300, 100), page_h)
    doc.close()

    both = (left + " " + right).split()
    assert both.count("detail") == 1, f"통째로 한 번만: {left!r} | {right!r}"
    # 잘린 조각이 어느 칸에도 남지 않는다 (clip 시절엔 "de"/"tail"이 갈라졌다)
    assert not {"de", "tail", "d", "il"} & set(both), f"{left!r} | {right!r}"


def test_좁은_여백_칸은_이웃_단어를_줍지_않는다():
    """§4-0 이슈⑳의 슬리버 칸 — 어떤 단어의 중심도 못 품으면 빈 칸이다."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=100)
    page.insert_text((10, 50), "TF1. value")
    page_h = float(page.rect.height)
    sliver = _pymupdf_cell_text(page, (0, 0, 12, 100), page_h)   # 12pt 여백 칸
    doc.close()
    assert sliver == ""


def test_같은_줄의_여러_pdf_조각_중_맨_끝_공백을_보존한다():
    """Word PDF는 같은 시각적 줄을 여러 text-line으로 나눈다.

    문자열 전체로 줄 끝 공백을 찾으면 ``software`` 조각의 공백 신호를
    합쳐진 ``software traceable to software`` 줄에 못 옮겨, 다음 줄과
    ``softwarerequirements``로 붙는다.
    """
    doc = fitz.open()
    page = doc.new_page(width=300, height=120)
    # 같은 y의 서로 다른 PDF text-line 세 개. 마지막 조각이 공백으로 끝난다.
    page.insert_text((10, 45), "software ")
    page.insert_text((70, 45), "traceable to ")
    page.insert_text((150, 45), "software ")
    page.insert_text((10, 57), "requirements? ")

    got = _pymupdf_cell_text(page, (0, 0, 230, 80), float(page.rect.height))
    doc.close()

    assert got == "software traceable to software requirements?"


def test_가짜_행_경계가_단어_줄바꿈을_가라도_한_단어로_배정한다():
    """옆 열의 가로선이 병합 셀을 가른 것처럼 인식되어도, PDF 글자
    흐름에서 공백 없이 이어진 ``Communicati`` + ``on``은 위쪽 셀의
    ``Communication`` 한 단어여야 한다. 아래쪽 셀에 ``on`` 조각이 중복되어도
    안 된다.
    """
    doc = fitz.open()
    page = doc.new_page(width=300, height=120)
    page.insert_text((10, 40), "Communicati")
    page.insert_text((10, 52), "on Monitoring ")
    words = page.get_text("words")
    first = next(w for w in words if w[4] == "Communicati")
    second = next(w for w in words if w[4] == "on")
    boundary = ((first[1] + first[3]) / 2 + (second[1] + second[3]) / 2) / 2
    page_h = float(page.rect.height)

    upper = _pymupdf_cell_text(page, (0, 0, 150, boundary), page_h)
    lower = _pymupdf_cell_text(page, (0, boundary, 150, 100), page_h)
    doc.close()

    assert upper == "Communication"
    assert lower == "Monitoring"
