"""구형 .hwp 로더 실문서 통합 — rhwp로 hwpx를 거쳐 네이티브 파싱한다.

로더 경로 자체의 단위 테스트는 src/modules/doc_parser/tests/test_hwp.py 에 있다.
여기는 진짜 .hwp 를 읽어 "실제로 파싱이 되는가"를 보는 유일한 관문이다.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from modules.doc_parser import HwpLoader

# 실 문서는 대외비라 저장소에 없을 수 있다 — 있을 때만 돈다.
HWP = Path("data/형식확인용예시파일/1. 과업지시서_민군경 해양데이터를 활용한 "
           "지능형 해양사고 분석 및 정책결정 지원 모델 연구 용역_슈어 수정.hwp")

pytestmark = pytest.mark.skipif(not HWP.exists(), reason=f"샘플 hwp 없음: {HWP}")


@pytest.fixture(scope="module")
def doc():
    return HwpLoader().load(HWP)


def test_extracts_body(doc):
    assert len(doc.text) > 500, "실 hwp 본문이 충분히 나와야 한다"
    assert "과업" in doc.text
    assert doc.meta["format"] == "hwp"
    assert doc.source_path == str(HWP)


def test_no_pdf_artifacts(doc):
    """PDF를 거치지 않으므로 폼피드·페이지번호 잔재가 없어야 한다.

    예전 경로(H2Orestart→PDF→PdfDigitalLoader)에서는 쪽 경계마다 \\x0c 와 페이지
    번호가 본문에 섞여 들어왔다. 네이티브 파싱으로 바꾼 이유가 이것이다.
    """
    assert "\x0c" not in doc.text, "폼피드가 본문에 섞였다"

    bare_numbers = [ln for ln in doc.text.splitlines() if ln.strip().isdigit()]
    assert not bare_numbers, f"페이지 번호로 보이는 줄이 남았다: {bare_numbers[:5]}"


def test_sentences_not_split_by_layout(doc):
    """PDF 줄바꿈에 잘리지 않고 문장이 한 줄에 온전히 들어온다."""
    assert any("정책결정 지원 모델 연구 용역" in ln for ln in doc.text.splitlines()), \
        "제목이 레이아웃 줄바꿈으로 쪼개졌다"


def test_tables_become_pipe_rows(doc):
    """표는 hwpx 로더 규약대로 `| 셀 | 셀 |` 한 줄로 나온다(내용 대조가 줄 단위다)."""
    rows = [ln for ln in doc.text.splitlines() if ln.strip().startswith("|")]
    assert rows, "예정 공정표가 표로 복원되지 않았다"
    assert any("추진 내용" in r and "추진 일정" in r for r in rows), \
        f"표 머리행이 한 줄에 오지 않았다: {rows[:3]}"
