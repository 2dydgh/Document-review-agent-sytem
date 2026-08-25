"""`라벨 | 값` 인용을 못 찾으면 값만으로 한 번 더 — 가로 표 형광펜.

칸 값 검사와 문서 간 대조는 인용을 `f"{라벨} | {값}"` 으로 만든다. 세로 표(라벨
오른쪽이 값)는 PDF 에도 둘이 나란히 있어 붙여서 찾히지만, **가로 표**(라벨 행 / 값
행 — 팀 기준의 `at: below`)는 PDF 에서 라벨 다음에 옆 칸 라벨이 온다. 그래서
`라벨+값` 이라는 문자열이 문서에 존재하지 않는다.

실측(을지 SST-K-TI-03-04): `at: below` 필드 4개가 **전부** 위치를 못 찾았다.
을지는 주요 필드가 거의 below 라 형광펜이 사실상 하나도 안 떴다. 재시도를 붙인 뒤
6개 중 6개를 찾는다.

**순서가 계약이다.** 라벨까지 붙은 쪽을 먼저 찾는다 — 라벨을 붙인 이유가 "같은 값이
여러 번 나오는 문서에서 제 칸을 짚기 위해"라, 재시도를 먼저 하면 그 방어가 죽는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from modules.report.annotate_pdf import (  # noqa: E402
    _find,
    _label_stripped,
    _page_index,
)


def _words(text: str) -> list[dict]:
    """PDF 낱말 목록 흉내. 가로 좌표만 맞으면 _find 가 돈다."""
    out = []
    x = 0.0
    for token in text.split():
        out.append({"text": token, "x0": x, "x1": x + len(token) * 5,
                    "top": 0.0, "bottom": 10.0})
        x += len(token) * 5 + 5
    return out


def _locate(quote: str, page_text: str) -> bool:
    words = _words(page_text)
    return _find(quote, _page_index(words), words) is not None


# ── 라벨 떼기 ────────────────────────────────────────────────────────

def test_no_pipe_means_nothing_to_strip() -> None:
    assert _label_stripped("그냥 문장이다") == ""


def test_strips_the_label_before_the_pipe() -> None:
    assert _label_stripped("의뢰번호 | SST-26-999") == "SST-26-999"


def test_takes_the_last_field_when_several_pipes() -> None:
    """표 행 인용은 `| 셀 | 셀 |` 꼴이라 파이프가 여럿이다. 값은 마지막 칸이다."""
    assert _label_stripped("| 순번 | 확인 사항 | SST-26-999 ") == "SST-26-999"


@pytest.mark.parametrize("short", ["버전 | 1.0", "쪽 | 2", "구분 | -"])
def test_short_values_are_not_retried(short: str) -> None:
    """짧은 값은 문서 아무 데나 있다. 엉뚱한 곳에 형광펜을 얹느니 안 얹는 게 낫다."""
    assert _label_stripped(short) == ""


# ── 찾기 ─────────────────────────────────────────────────────────────

def test_vertical_table_still_matches_with_the_label() -> None:
    """세로 표는 원래대로 라벨까지 붙여 찾는다 — 되던 것을 안 건드린다."""
    assert _locate("시험 대상 품명 | Apple", "시험 대상 품명 Apple 1.0.1")


def test_horizontal_table_is_found_by_the_value(monkeypatch) -> None:
    """가로 표: PDF 에서 라벨 다음은 옆 칸 라벨이다. 값만으로 찾아야 한다."""
    page = "의뢰번호 성적서번호 시험기간 SST-26-999 SST-26-999-C01 2026.01.01"
    assert not _locate("의뢰번호 | 없는값999999", page), "없는 값까지 찾으면 안 된다"
    assert _locate("의뢰번호 | SST-26-999", page)


def test_label_form_wins_when_both_exist() -> None:
    """라벨까지 맞는 자리가 있으면 그쪽을 짚는다.

    같은 값이 두 번 나오는 문서에서 재시도가 먼저 걸리면 엉뚱한 칸을 짚는다 —
    라벨을 붙인 이유가 바로 그것이다.
    """
    page = "SST-26-999 다른표 의뢰번호 SST-26-999"
    words = _words(page)
    got = _find("의뢰번호 | SST-26-999", _page_index(words), words)
    assert got is not None
    assert got[0]["text"] == "의뢰번호", (
        f"라벨이 붙은 뒤쪽 자리를 짚어야 하는데 {got[0]['text']!r} 를 짚었다")


def test_missing_value_stays_unfound() -> None:
    """재시도가 아무거나 걸리게 만들면 안 된다. 없으면 없는 것이다."""
    assert not _locate("의뢰번호 | SST-26-777", "의뢰번호 SST-26-999")


def test_quote_without_pipe_behaves_as_before() -> None:
    assert _locate("한국소프트웨어시험연구소", "의뢰기관 한국소프트웨어시험연구소")
    assert not _locate("없는 문장입니다", "의뢰기관 한국소프트웨어시험연구소")
