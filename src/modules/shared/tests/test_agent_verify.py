"""근거 검증 — agent가 인용한 문장이 원문에 실재하는지 문자열로 대조한다.

LLM을 한 번 더 부르는 self-critique보다 싸고, 무엇보다 결정적이다.
"""
from modules.shared import Anchor, Document, Section
from modules.shared import verify_quotes


def _doc():
    return Document(source_path="x", doc_type="generic", sections=[
        Section(id="s0", title="컴포넌트", level=1,
                text="| 예측 | 위험등급을 산청하며 |\n| 서빙 | 캐시 제공 |",
                anchor=Anchor(page=None, section="컴포넌트")),
        Section(id="s1", title="시퀀스", level=1,
                text="데이터 수집 및 피러 생성",
                anchor=Anchor(page=None, section="시퀀스")),
    ])


def test_verified_quote_gets_its_anchor():
    ok, bad = verify_quotes(_doc(), ["위험등급을 산청하며"])
    assert bad == []
    assert len(ok) == 1
    assert ok[0].anchor.section == "컴포넌트"
    assert ok[0].quote == "위험등급을 산청하며"


def test_fabricated_quote_is_rejected():
    """원문에 없는 인용은 환각이다. 통과시키면 지적이 지어내진다."""
    ok, bad = verify_quotes(_doc(), ["3초 이내에 응답한다"])
    assert ok == []
    assert bad == ["3초 이내에 응답한다"]


def test_partial_verification_reports_both():
    ok, bad = verify_quotes(_doc(), ["피러 생성", "존재하지 않는 문장"])
    assert [e.quote for e in ok] == ["피러 생성"]
    assert bad == ["존재하지 않는 문장"]


def test_whitespace_differences_are_tolerated():
    """모델이 공백을 다르게 옮겨 적는 것까지 환각으로 볼 필요는 없다."""
    ok, bad = verify_quotes(_doc(), ["데이터  수집 및 피러  생성"])
    assert bad == []
    assert len(ok) == 1


def test_empty_quotes_yield_nothing():
    ok, bad = verify_quotes(_doc(), [])
    assert ok == [] and bad == []


def test_single_character_quote_is_unverifiable():
    """"예"는 "예측" 안에 실재하는 substring이지만, 한 글자로는 아무 message나
    끌어다 붙일 수 있다 — 환각을 태우는 통로다. found에는 안 들어간다.

    missing에도 안 들어간다: 너무 짧아 애초에 검색하지 않았으므로, missing에
    넣으면 "원문에서 확인했지만 없더라"는 거짓 보고가 된다(예측 안에 실제로
    있으니까). loop.py는 found가 비어 있으면 판단불가로 강등한다."""
    ok, bad = verify_quotes(_doc(), ["예"])
    assert ok == []
    assert bad == []


def test_pure_punctuation_quote_is_unverifiable():
    """"|"는 표 구분자로 문서 어디에나 있다 — 문장부호뿐인 인용은 근거가
    아니다. 짧은 인용과 마찬가지로 검색 없이 조용히 버려진다(missing에도
    없다) — loop.py는 found가 비어 있으면 판단불가로 강등한다."""
    ok, bad = verify_quotes(_doc(), ["|"])
    assert ok == []
    assert bad == []


def test_whitespace_only_quote_is_not_counted_as_evidence():
    """공백만 있는 인용은 정규화하면 빈 문자열이라 애초에 "실질적"이지
    않다 — 짧은/문장부호뿐인 인용과 똑같이 검색 없이 조용히 버려진다
    (found에도 missing에도 안 남는다). 근거 없는 '불일치'가 새는 것은
    verify_quotes가 아니라 loop.py의 `if not found:`가 막는다
    (tests/test_agent_loop.py::test_whitespace_only_quotes_is_undecidable_not_a_mismatch)."""
    ok, bad = verify_quotes(_doc(), ["   "])
    assert ok == []
    assert bad == []


def test_short_but_substantive_quote_still_verifies():
    """문턱이 너무 높으면 정말 짧은 진짜 근거까지 버려진다 — "산청하며"(4자)는
    _MIN_QUOTE 경계값이면서 실제 원문에 있는 근거다."""
    ok, bad = verify_quotes(_doc(), ["산청하며"])
    assert bad == []
    assert [e.quote for e in ok] == ["산청하며"]


def test_short_quote_alongside_a_real_one_does_not_kill_the_finding():
    """모델이 문장 전체와 핵심 단어를 나란히 인용하는 것은 "무엇이
    어긋나는지 + 원문 인용"을 요구받았을 때 나오는 정상적인 응답 모양이다.
    문장 전체는 검증되는데 짧은 인용 하나 때문에 missing이 채워져 지적
    전체가 죽으면 안 된다 — 짧은 인용은 그냥 근거로 안 셀 뿐, missing에도
    안 들어간다."""
    ok, bad = verify_quotes(
        _doc(), ["위험등급을 산청하며", "예"])
    assert [e.quote for e in ok] == ["위험등급을 산청하며"]
    assert bad == []


def test_only_short_quotes_yield_no_evidence():
    """짧은 인용만 낸 경우 found는 비어 있어야 한다 — loop.py가 이걸 보고
    "근거를 인용하지 않았다"로 강등한다."""
    ok, bad = verify_quotes(_doc(), ["예"])
    assert ok == []


def test_quote_spanning_line_break_is_found():
    """PDF 하드 줄바꿈·표 행을 이어 읽은 인용은 원문에 실재한다 — 줄 단위
    대조만으로 missing 처리하면 진짜 지적이 오폐기된다(수정 2026-08-06).
    글자는 그대로 대조하므로 환각 방어력은 같고, 개행 위치만 용서한다."""
    ok, bad = verify_quotes(_doc(), ["산청하며 | | 서빙"])
    assert bad == []
    assert len(ok) == 1
    assert ok[0].anchor.section == "컴포넌트"
    assert ok[0].image_no is None
