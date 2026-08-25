"""포맷→PDF 변환 (LibreOffice)."""
from __future__ import annotations

import io
import shutil
import subprocess
import types
import zipfile
from pathlib import Path

import pytest

from modules.doc_parser import UnsupportedFormatError
from modules.doc_parser import convert
from modules.doc_parser import ConvertUnavailable, build_html, to_pdf

pytestmark = pytest.mark.skipif(shutil.which("soffice") is None, reason="soffice 없음")

# 실 문서는 대외비라 저장소에 없을 수 있다 — 있을 때만 돈다.
_SAMPLES = Path("data/형식확인용예시파일")
HWP = _SAMPLES / ("1. 과업지시서_민군경 해양데이터를 활용한 "
                  "지능형 해양사고 분석 및 정책결정 지원 모델 연구 용역_슈어 수정.hwp")
HWPX = _SAMPLES / "민군경 2세부 시연 화면과 시나리오(안).hwpx"


def _has_text(pdf_bytes: bytes, needle: str) -> bool:
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as p:
        return needle in "".join((pg.extract_text() or "") for pg in p.pages)


def _make_docx(text: str) -> bytes:
    """최소 OOXML docx 한 장. LibreOffice가 열 수 있으면 충분하다."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels",
            '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml",
            '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>')
    return buf.getvalue()


def test_build_html_renders_heading_table_paragraph():
    html = build_html("# 제목\n본문 문단\n| 항목 | 값 |\n| 응답시간 | 3초 |")
    assert "<h1>제목</h1>" in html
    assert "<table" in html and "<td>항목</td>" in html and "<td>응답시간</td>" in html
    assert "<p>본문 문단</p>" in html
    assert "NanumGothic" in html


def test_docx_converts_to_pdf_with_text(tmp_path):
    docx = tmp_path / "sample.docx"
    docx.write_bytes(_make_docx("요구사항 RQ-001 응답시간 검증"))
    pdf = to_pdf(docx)
    assert pdf[:4] == b"%PDF"
    assert _has_text(pdf, "요구사항")


def test_hwpx_falls_back_to_reproduction_when_h2orestart_missing(monkeypatch):
    """H2Orestart 없으면 hwpx 는 추출 텍스트 재현본으로 폴백한다(후방 호환)."""
    calls = []
    def fake_soffice(src, work):
        calls.append(src.suffix.lower())
        if src.suffix.lower() == ".hwpx":     # 원본 직접 변환 = H2Orestart 없음
            raise RuntimeError("no hwp filter")
        return b"%PDF-recon"                    # recon.html 변환은 성공
    monkeypatch.setattr(convert, "_soffice_to_pdf", fake_soffice)
    monkeypatch.setattr(convert, "load_document",
                        lambda p: types.SimpleNamespace(text="# 제목\n본문"))
    out = convert.to_pdf(Path("x.hwpx"))
    assert out == b"%PDF-recon"
    assert calls == [".hwpx", ".html"]          # 직접 시도 → 실패 → html 폴백


def test_hwp_raises_convert_unavailable_when_h2orestart_missing(monkeypatch):
    """hwp 는 폴백이 없다(네이티브 재현본도 못 만든다) — 설치 안내를 던진다."""
    def fail(src, work):
        raise RuntimeError("no hwp filter")
    monkeypatch.setattr(convert, "_soffice_to_pdf", fail)
    with pytest.raises(ConvertUnavailable, match="H2Orestart"):
        convert.to_pdf(Path("x.hwp"))


@pytest.mark.skipif(not HWP.exists(), reason="샘플 hwp 없음")
def test_real_hwp_converts_to_pdf_with_text():
    """H2Orestart 로 hwp → PDF, 본문 텍스트가 추출된다(레이아웃 보존)."""
    pdf = to_pdf(HWP)
    assert pdf[:4] == b"%PDF"
    assert _has_text(pdf, "과업지시서") or _has_text(pdf, "해양")


@pytest.mark.skipif(not HWPX.exists(), reason="샘플 hwpx 없음")
def test_real_hwpx_converts_to_pdf_with_text():
    pdf = to_pdf(HWPX)
    assert pdf[:4] == b"%PDF"
    assert _has_text(pdf, "시나리오") or _has_text(pdf, "해양")


def test_pdf_passthrough(tmp_path):
    src = Path("tests/data/probe.pdf")
    if not src.exists():
        pytest.skip("probe.pdf 없음")
    assert to_pdf(src)[:4] == b"%PDF"


def test_unknown_extension_is_unsupported(tmp_path):
    """지원하지 않는 확장자는 명확히 거부한다(hwp/hwpx는 이제 지원이라 대상 아님)."""
    f = tmp_path / "x.xyz"
    f.write_bytes(b"whatever")
    with pytest.raises(UnsupportedFormatError):
        to_pdf(f)


def test_convert_unavailable_when_soffice_missing(monkeypatch, tmp_path):
    import modules.doc_parser.convert as cv
    monkeypatch.setattr(cv.shutil, "which", lambda _n: None)
    docx = tmp_path / "s.docx"
    docx.write_bytes(_make_docx("x"))
    with pytest.raises(ConvertUnavailable):
        to_pdf(docx)


# ── 실패 사유를 오진하지 않는다 ──────────────────────────────────────────────
# 옛 코드는 무슨 이유든 "H2Orestart 를 설치하세요"였다. 실제로 본 실패는 확장이
# 멀쩡한 상태에서 soffice 가 segfault(139) 한 것이었고, 그 메시지 때문에 원인을
# 세 번 놓쳤다. 동시 변환이 겹칠 때 죽는다 — 그래서 _SOFFICE_LOCK 으로 직렬화한다.

def test_crash_is_not_reported_as_a_missing_extension(monkeypatch):
    def boom(src, work):
        raise subprocess.CalledProcessError(139, ["soffice"])
    monkeypatch.setattr(convert, "_soffice_to_pdf", boom)

    with pytest.raises(ConvertUnavailable) as err:
        convert.to_pdf(Path("x.hwp"))

    assert "비정상 종료" in str(err.value)
    assert "139" in str(err.value)
    assert "unopkg" not in str(err.value), "설치 안내는 실행이 안 될 때만 맞다"


def test_real_missing_extension_still_says_how_to_install(monkeypatch):
    def nope(src, work):
        raise subprocess.CalledProcessError(1, ["soffice"])   # 필터 없음
    monkeypatch.setattr(convert, "_soffice_to_pdf", nope)

    with pytest.raises(ConvertUnavailable, match="H2Orestart"):
        convert.to_pdf(Path("x.hwp"))


def test_soffice_calls_are_serialized():
    """프로파일 격리만으로는 부족했다 — 동시에 겹치면 segfault 한다."""
    import inspect
    src = inspect.getsource(convert._soffice_to_pdf)
    assert "_SOFFICE_LOCK" in src, "락 없이 부르면 동시 변환에서 죽는다"
    assert "with _SOFFICE_LOCK:" in src


# ── 반환코드가 아니라 산출물을 본다 ──────────────────────────────────────────
# soffice 는 변환을 다 끝내고 종료할 때 segfault(139) 하는 일이 잦다. 실측으로 같은
# hwpx 를 네 번 변환했더니 두 번이 139 였고, 그 PDF 는 성공한 것과 크기·쪽수·그림수·
# %%EOF 까지 똑같았다. 반환코드만 보던 옛 코드는 그 멀쩡한 PDF 를 버렸다 — hwpx 는
# 텍스트 재현본으로 폴백했고(사용자는 절반의 확률로 원본이 아닌 문서를 봤다),
# hwp 는 아예 "변환 실패"가 됐다.

_GOOD_PDF = b"%PDF-1.4\n... body ...\ntrailer\n%%EOF\n"


def _fake_soffice(monkeypatch, returncode: int, writes: bytes | None):
    """soffice 를 흉내낸다. writes 가 있으면 그 바이트로 PDF 를 만들어 둔다."""
    import subprocess as sp

    # _run_soffice 를 가로챈다 — subprocess.run 이 아니다. 시한 초과 때 손자
    # 프로세스(soffice.bin)까지 죽이려고 Popen + killpg 로 내려갔기 때문이다
    # (convert._run_soffice 주석 · test_convert_timeout.py).
    def run(cmd, work, **kw):
        if writes is not None:
            outdir = Path(cmd[cmd.index("--outdir") + 1])
            src = Path(cmd[-1])
            (outdir / (src.stem + ".pdf")).write_bytes(writes)
        return sp.CompletedProcess(cmd, returncode, b"", b"")

    monkeypatch.setattr(convert, "_run_soffice", run)
    monkeypatch.setattr(convert.shutil, "which", lambda _n: "/usr/bin/soffice")


def test_crash_after_writing_a_complete_pdf_is_accepted(monkeypatch, tmp_path):
    """종료할 때 죽어도 PDF 가 온전하면 그것을 쓴다."""
    _fake_soffice(monkeypatch, 139, _GOOD_PDF)
    src = tmp_path / "s.docx"
    src.write_bytes(b"x")

    assert convert.to_pdf(src) == _GOOD_PDF


def test_hwpx_does_not_fall_back_when_the_pdf_is_complete(monkeypatch, tmp_path):
    """폴백하면 그림 없는 텍스트 재현본이 된다 — 원본 레이아웃을 버리는 셈이다."""
    _fake_soffice(monkeypatch, 139, _GOOD_PDF)
    src = tmp_path / "s.hwpx"
    src.write_bytes(b"x")

    assert convert.to_pdf(src) == _GOOD_PDF


def test_truncated_pdf_is_rejected(monkeypatch, tmp_path):
    """변환 도중에 죽었으면 %%EOF 가 없다. 잘린 파일을 통과시키지 않는다."""
    _fake_soffice(monkeypatch, 139, b"%PDF-1.4\n... cut off mid-write ...")
    src = tmp_path / "s.hwp"
    src.write_bytes(b"x")

    with pytest.raises(ConvertUnavailable, match="비정상 종료|온전한 PDF"):
        convert.to_pdf(src)


def test_no_output_at_all_is_rejected(monkeypatch, tmp_path):
    _fake_soffice(monkeypatch, 1, None)
    src = tmp_path / "s.hwp"
    src.write_bytes(b"x")

    with pytest.raises(ConvertUnavailable):
        convert.to_pdf(src)
