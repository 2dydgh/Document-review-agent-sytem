"""구형 .hwp 로더 단위 테스트 — 실문서 없이 돈다.

.hwp 바이너리를 만들 수는 없으므로 rhwp 변환 단계(to_hwpx_bytes)를 최소 hwpx로
바꿔치기하고, 그 뒤 경로(HwpxLoader 위임 · source_path/meta 보정)를 검증한다.
실문서로 도는 통합 테스트는 tests/test_ingestion_hwp.py 에 있다.
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

import pytest

from modules.doc_parser.ingestion import hwp as hwp_mod
from modules.doc_parser.ingestion.hwp import HwpLoader, HwpParseUnavailable

_HP = "http://www.hancom.co.kr/hwpml/2011/paragraph"


def _minimal_hwpx(*paragraphs: str) -> bytes:
    """HwpxLoader가 읽을 수 있는 최소 hwpx(ZIP + section0.xml)."""
    body = "".join(
        f"<hp:p><hp:run><hp:t>{p}</hp:t></hp:run></hp:p>" for p in paragraphs)
    section = f'<hs:sec xmlns:hp="{_HP}" xmlns:hs="urn:sec">{body}</hs:sec>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/hwp+zip")
        z.writestr("Contents/section0.xml", section)
    return buf.getvalue()


def test_extensions():
    assert ".hwp" in HwpLoader().extensions


def test_parses_via_hwpx(monkeypatch):
    """rhwp가 낸 hwpx를 HwpxLoader가 읽고, 그 텍스트가 그대로 나온다."""
    monkeypatch.setattr(hwp_mod, "to_hwpx_bytes",
                        lambda p: _minimal_hwpx("과업 개요", "예산 1억"))

    doc = HwpLoader().load(Path("어떤.hwp"))

    assert "과업 개요" in doc.text
    assert "예산 1억" in doc.text


def test_keeps_original_path_not_tempfile(monkeypatch):
    """source_path는 임시 hwpx가 아니라 원본 .hwp여야 한다 — 리포트가 문서 이름으로 쓴다."""
    monkeypatch.setattr(hwp_mod, "to_hwpx_bytes", lambda p: _minimal_hwpx("본문"))

    doc = HwpLoader().load(Path("data/보고서.hwp"))

    # source_path 비교는 Path로 한다 — str 비교는 Windows에서 os.sep이
    # 백슬래시로 정규화되어 리터럴 "/"와 항상 불일치한다(실제 결함이 아니라
    # 테스트의 플랫폼 가정 문제). HwpLoader가 원본 경로를 그대로 돌려주는지가
    # 검증 대상이지, 구분자 문자가 아니다.
    assert Path(doc.source_path) == Path("data/보고서.hwp")
    assert "converted.hwpx" not in doc.source_path
    assert doc.meta["format"] == "hwp"      # hwpx를 거쳤어도 입력 형식은 hwp다


def test_missing_rhwp_tells_how_to_fix(monkeypatch):
    """rhwp import가 깨지면 조치 방법을 담은 예외를 던진다(휠의 freetype 문제)."""
    monkeypatch.setitem(sys.modules, "rhwp", None)   # import rhwp -> ImportError

    with pytest.raises(HwpParseUnavailable, match="fix-rhwp-freetype"):
        hwp_mod.to_hwpx_bytes(Path("어떤.hwp"))
