"""그림 설명에서 나온 지적을 그림 자체에 짚는다.

그림 설명은 파싱 본문에만 있고 뷰어용 PDF 의 텍스트 레이어에는 없다(거기엔 이미지가
있다). 그래서 그 설명에서 나온 근거는 인용문으로는 **영원히** 못 찾는다 — 실측으로
확인했다: 같은 문서에서 본문 근거는 형광펜 1개, 그림 근거는 unlocated 1건이었다.

연결은 두 조각이다.
  1) verify_quotes 가 근거를 확인한 줄이 `[그림 N: …]` 이면 image_no=N 을 남긴다.
  2) locate 가 그 번호를 뷰어 PDF 안의 이미지와 짝지어(match_images) 사각형을 낸다.
"""
from __future__ import annotations

import io
import struct
import zlib

import pytest

pytest.importorskip("pdfplumber")

from modules.report import locate
from modules.report.annotate_pdf import match_images
from modules.shared import Anchor, Document, Section, verify_quotes


def _png(w: int, h: int) -> bytes:
    """단색 PNG. 크기만 중요하다 — 짝짓기의 열쇠가 크기이기 때문이다."""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    rows = b"".join(b"\x00" + bytes([40, 90, 200]) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def _pdf_with_images(sizes: list[tuple[int, int]]) -> bytes:
    """이미지를 한 쪽에 하나씩 담은 PDF. fpdf2 로 만든다(web extra 에 이미 있다)."""
    fpdf = pytest.importorskip("fpdf")
    doc = fpdf.FPDF(unit="pt", format=(400, 500))
    for w, h in sizes:
        doc.add_page()
        doc.image(io.BytesIO(_png(w, h)), x=50, y=80, w=200)
    return bytes(doc.output())


# ── verify_quotes 가 그림 번호를 남기는가 ────────────────────────────────────

def _doc(text: str) -> Document:
    return Document(source_path="x.docx", doc_type="generic",
                    sections=[Section(id="1", title="개요", level=1, text=text,
                                      anchor=Anchor(None, "1"))])


def test_quote_from_an_image_description_carries_its_number():
    doc = _doc("본문 한 줄\n[그림 2: CDMS Server-P 는 IPS 와 통신한다]\n또 본문")

    found, _missing = verify_quotes(doc, ["CDMS Server-P 는 IPS 와 통신한다"])

    assert [e.image_no for e in found] == [2]


def test_quote_from_the_body_has_no_image_number():
    doc = _doc("본문 한 줄\n[그림 2: 그림 설명]\n또 본문 문장이다")

    found, _missing = verify_quotes(doc, ["또 본문 문장이다"])

    assert [e.image_no for e in found] == [None]


# ── 그림을 PDF 안 이미지와 짝짓는가 ──────────────────────────────────────────

def test_matches_by_size():
    pdfplumber = pytest.importorskip("pdfplumber")
    data = _pdf_with_images([(300, 150), (200, 400)])

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        got = match_images(pdf, [{"no": 1, "width": 300, "height": 150},
                                 {"no": 2, "width": 200, "height": 400}])

    assert sorted(got) == [1, 2]
    assert got[1]["page"] == 1 and got[2]["page"] == 2


def test_matches_a_uniformly_downscaled_image_by_aspect_ratio():
    """LibreOffice 가 균일 축소한다 — 실측 1563x925 → 1438x851(배율 0.920).

    크기는 8% 달라지지만 종횡비는 남는다. 그것으로 잡는다.
    """
    pdfplumber = pytest.importorskip("pdfplumber")
    data = _pdf_with_images([(1438, 851)])          # PDF 안에는 축소본만 있다

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        got = match_images(pdf, [{"no": 1, "width": 1563, "height": 925}])

    assert got[1]["page"] == 1


def test_unrelated_image_is_left_unmatched():
    """짝이 없으면 빼놓는다 — 엉뚱한 곳에 형광펜을 얹는 것보다 안 얹는 편이 낫다."""
    pdfplumber = pytest.importorskip("pdfplumber")
    data = _pdf_with_images([(100, 100)])           # 정사각형뿐

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        got = match_images(pdf, [{"no": 1, "width": 1949, "height": 708}])

    assert got == {}


def test_unknown_size_is_left_unmatched():
    pdfplumber = pytest.importorskip("pdfplumber")
    data = _pdf_with_images([(300, 150)])

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        got = match_images(pdf, [{"no": 1, "width": 0, "height": 0}])

    assert got == {}


# ── locate 가 그림 좌표를 내는가 ─────────────────────────────────────────────

def _finding(image_no):
    return [{"id": "f1", "sev": "minor", "message": "그림 안 표기가 흔들린다",
             "section": "1", "page": None,
             "evidence": [{"quote": "PDF 본문에는 결코 없는 문장",
                           "page": None, "image_no": image_no}]}]


def test_image_evidence_gets_the_image_rect():
    data = _pdf_with_images([(300, 150)])

    got = locate(data, _finding(1), images=[{"no": 1, "width": 300, "height": 150}])

    marks = got["items"][0]["marks"]
    assert len(marks) == 1
    assert marks[0]["page"] == 1
    x0, y0, x1, y1 = marks[0]["rect"]
    assert x1 > x0 and y1 > y0, "빈 사각형은 형광펜이 안 보인다"
    assert not got["unlocated"]


def test_image_evidence_without_a_match_says_why():
    """짝을 못 지었으면 이유를 본문 못 찾음과 구분해 말한다."""
    data = _pdf_with_images([(100, 100)])

    got = locate(data, _finding(1), images=[{"no": 1, "width": 1949, "height": 708}])

    assert got["items"][0]["marks"] == []
    assert "그림" in got["unlocated"][0]["reason"]


def test_body_evidence_is_unaffected():
    """image_no 가 없으면 예전과 똑같이 동작한다."""
    data = _pdf_with_images([(300, 150)])

    got = locate(data, _finding(None), images=[{"no": 1, "width": 300, "height": 150}])

    assert got["items"][0]["marks"] == []
    assert "PDF 본문에서 찾지 못했습니다" in got["unlocated"][0]["reason"]


def test_images_argument_is_optional():
    """옛 이력에는 그림 정보가 없다 — 없어도 깨지지 않아야 한다."""
    data = _pdf_with_images([(300, 150)])

    got = locate(data, _finding(1))

    assert got["items"][0]["marks"] == []
    assert got["unlocated"]
