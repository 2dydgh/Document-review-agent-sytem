"""그림 추출 — 문서에 그림이 있었다는 사실을 본문에 남긴다.

그림 안의 내용은 아직 읽지 못한다(비전 모델이 할 일). 다만 **있었다는 사실**은
남겨야 한다. 지금까지는 흔적조차 없어서 검토 Agent 에게 그 자리가 빈 곳이었고,
"그림으로 설명했다"는 문서를 "설명이 없다"고 읽을 수 있었다.

본문의 `[그림 N]` 번호와 meta["images"] 의 no 가 이어진다.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from modules.doc_parser.ingestion.docx import DocxLoader
from modules.doc_parser.ingestion.hwpx import HwpxLoader

_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PR = "http://schemas.openxmlformats.org/package/2006/relationships"


def _hwpx(tmp_path: Path) -> Path:
    """문단 하나 · 그림 하나가 든 최소 hwpx."""
    section = (
        f'<hs:sec xmlns:hp="{_HP}" xmlns:hs="urn:sec">'
        "<hp:p><hp:run><hp:t>본문 한 줄</hp:t></hp:run></hp:p>"
        '<hp:p><hp:run><hp:pic id="1"><hp:img binaryItemIDRef="image1"/>'
        "</hp:pic></hp:run></hp:p>"
        "</hs:sec>")
    manifest = (
        '<opf:package xmlns:opf="http://www.idpf.org/2007/opf/"><opf:manifest>'
        '<opf:item id="image1" href="BinData/image1.png" media-type="image/png"/>'
        "</opf:manifest></opf:package>")
    p = tmp_path / "s.hwpx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Contents/section0.xml", section)
        z.writestr("Contents/content.hpf", manifest)
        z.writestr("BinData/image1.png", b"\x89PNG fake")
    return p


def _docx(tmp_path: Path, *, alt: str, name: str = "그림 1",
          embed: bool = True) -> Path:
    """문단 하나 · 그림 하나가 든 최소 docx."""
    rid = ' r:embed="rId9"' if embed else ""
    body = (
        f'<w:document xmlns:w="{_W}" xmlns:wp="{_WP}" xmlns:r="{_R}"><w:body>'
        "<w:p><w:r><w:t>본문 한 줄</w:t></w:r></w:p>"
        f'<w:p><w:r><w:drawing><wp:docPr name="{name}" descr="{alt}"/>'
        f"<w:blip{rid}/></w:drawing></w:r></w:p>"
        "</w:body></w:document>")
    rels = (
        f'<Relationships xmlns="{_PR}">'
        '<Relationship Id="rId9" Type="…/image" Target="media/image1.png"/>'
        "</Relationships>")
    p = tmp_path / "d.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/document.xml", body)
        z.writestr("word/_rels/document.xml.rels", rels)
        z.writestr("word/media/image1.png", b"\x89PNG fake")
    return p


# ── hwpx ────────────────────────────────────────────────────────────────────

def test_hwpx_leaves_a_placeholder_in_the_body(tmp_path):
    raw = HwpxLoader().load(_hwpx(tmp_path))

    assert "[그림 1]" in raw.text
    assert "본문 한 줄" in raw.text


def test_hwpx_records_the_archive_path(tmp_path):
    """part 는 ZIP 내부 경로다. 바이트는 담지 않는다 — RawDoc 은 JSON 직렬화 가능해야 한다."""
    raw = HwpxLoader().load(_hwpx(tmp_path))

    assert raw.meta["images"] == [
        {"no": 1, "name": "", "alt": "", "part": "BinData/image1.png",
         # 가짜 PNG 라 크기를 못 읽는다 — 0 은 "모른다"는 뜻이다.
         "width": 0, "height": 0}]
    # 실제로 그 경로로 바이트를 얻을 수 있어야 한다.
    with zipfile.ZipFile(raw.source_path) as z:
        assert z.read(raw.meta["images"][0]["part"]).startswith(b"\x89PNG")


def test_hwpx_has_no_alt_text(tmp_path):
    """한컴은 대체텍스트를 넣지 않는다. 없는 설명을 지어내지 않고 번호만 남긴다."""
    raw = HwpxLoader().load(_hwpx(tmp_path))

    assert raw.meta["images"][0]["alt"] == ""
    assert "[그림 1]" in raw.text          # `[그림 1: …]` 이 아니다


# ── docx ────────────────────────────────────────────────────────────────────

def test_docx_carries_word_alt_text_into_the_body(tmp_path):
    """워드는 대체텍스트를 붙여 둔다. 품질은 낮지만 짐작할 근거는 된다."""
    raw = DocxLoader().load(_docx(tmp_path, alt="스크린샷이 표시된 사진"))

    assert "[그림 1: 스크린샷이 표시된 사진]" in raw.text
    assert raw.meta["images"][0]["alt"] == "스크린샷이 표시된 사진"
    assert raw.meta["images"][0]["name"] == "그림 1"
    assert raw.meta["images"][0]["part"] == "word/media/image1.png"


def test_docx_without_alt_text_leaves_only_a_number(tmp_path):
    raw = DocxLoader().load(_docx(tmp_path, alt=""))

    assert "[그림 1]" in raw.text
    assert "[그림 1:" not in raw.text


def test_docx_skips_shapes_that_have_no_image(tmp_path):
    """w:drawing 에는 이미지가 없는 도형도 온다("직사각형 10").

    도형 안의 글자는 이미 본문으로 읽으므로 "그림"으로 또 세면 개수만 부풀고,
    비전 모델에 보낼 바이트도 없다. 실문서에서 11개 중 5개가 그런 도형이었다.
    """
    raw = DocxLoader().load(
        _docx(tmp_path, alt="", name="직사각형 10", embed=False))

    assert raw.meta["images"] == []
    assert "[그림" not in raw.text
    assert "본문 한 줄" in raw.text        # 본문은 그대로 나온다


def test_docx_numbers_match_between_body_and_meta(tmp_path):
    """본문 자리표시 번호와 meta 의 no 가 어긋나면 비전 모델 결과를 되붙일 수 없다."""
    raw = DocxLoader().load(_docx(tmp_path, alt="설명"))

    nos = [im["no"] for im in raw.meta["images"]]
    marks = [ln for ln in raw.text.splitlines() if ln.startswith("[그림")]
    assert nos == [1]
    assert len(marks) == len(nos)
    assert marks[0].startswith(f"[그림 {nos[0]}")
