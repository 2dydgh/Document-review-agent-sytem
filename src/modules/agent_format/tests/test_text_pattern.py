"""표기 규칙 검사 — 정규식 하나로 되는 것들.

팀 기준에는 "날짜는 `YYYY. MM. DD.`", "`%` 앞에 공백", "천 단위 쉼표 금지" 처럼
글자 모양만 보면 판정되는 항목이 많다(AI시험인증1팀 md §1.3 이 통째로 그렇다).
검사기를 아홉 개 만드는 대신 하나로 묶고 규칙값은 기준의 params 가 준다.

**여기서 지키는 계약 셋**
  1. 규칙을 안 주면 검사한 척하지 않는다 — 미검토로 알린다.
  2. 정규식이 깨져도 지적하지 않는다 — 재지 못했다고 알린다.
  3. 지적에는 문서에서 꺼낸 인용이 붙는다. 화면이 그 자리를 짚어야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from modules.agent_format import TextPatternChecker
from modules.shared import Anchor


@dataclass
class _Section:
    text: str
    anchor: Anchor = field(default_factory=lambda: Anchor(page=1, section="1"))


@dataclass
class _Doc:
    sections: list

    def iter_sections(self):
        return iter(self.sections)


def _doc(text: str) -> _Doc:
    return _Doc([_Section(text)])


def _run(text: str, **kw) -> list:
    return [f for f in TextPatternChecker(**kw).check(_doc(text)) if not f.unreviewed]


# ── 없는 규칙·깨진 규칙 ──────────────────────────────────────────────

def test_no_rule_reports_unreviewed() -> None:
    """규칙이 없으면 조용한 0건이 아니라 '검사하지 않았다'고 말한다."""
    got = TextPatternChecker().check(_doc("아무 내용"))
    assert len(got) == 1
    assert got[0].unreviewed
    assert "검사를 수행하지 않았습니다" in got[0].message


def test_find_without_must_is_unreviewed() -> None:
    """무엇을 찾을지만 알고 무엇이 맞는지 모르면 판정할 수 없다."""
    got = TextPatternChecker(find=r"\d+").check(_doc("123"))
    assert got and got[0].unreviewed


def test_broken_regex_is_reported_not_flagged() -> None:
    """정규식이 깨졌으면 '맞지 않는다'가 아니라 '재지 못했다'다.

    지적으로 내면 멀쩡한 문서가 전부 틀린 것으로 뜬다(FilenameChecker 와 같은 처방).
    """
    got = TextPatternChecker(forbid=r"[unclosed").check(_doc("아무 내용"))
    assert len(got) == 1
    assert got[0].unreviewed
    assert "정규식이 올바르지 않아" in got[0].message


# ── forbid: 나오면 안 되는 표기 ──────────────────────────────────────

@pytest.mark.parametrize(("text", "hit"), [
    ("총 10,000 건", True),
    ("총 10000 건", False),
    ("1,234,567 원", True),
])
def test_forbid_thousands_separator(text: str, hit: bool) -> None:
    got = _run(text, forbid=r"\d{1,3}(,\d{3})+", message="천 단위 쉼표")
    assert bool(got) is hit


@pytest.mark.parametrize(("text", "hit"), [
    ("정확도 95%", True),      # 붙어 있으면 위반
    ("정확도 95 %", False),    # 공백이 있으면 정상
])
def test_forbid_percent_without_space(text: str, hit: bool) -> None:
    """실측(을지)에서 이 규칙이 오탐을 냈다 — `\\d\\s*%` 로 잡으면 **맞게 쓴**
    `95 %` 까지 걸린다. 공백 없이 붙은 것만 잡아야 한다."""
    got = _run(text, forbid=r"\d%", message="% 앞 공백")
    assert bool(got) is hit


# ── find + must: 찾아서 형식을 맞춰본다 ──────────────────────────────

_DATE = {"find": r"\d{4}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}\.?",
         "must": r"\d{4}\. \d{2}\. \d{2}\.", "message": "날짜 형식"}


@pytest.mark.parametrize(("text", "hit"), [
    ("작성일 2026. 01. 05.", False),   # 맞는 형식
    ("작성일 2026.1.5", True),
    ("작성일 2026-02-03", True),
    ("작성일 2026/02/03", True),
])
def test_find_must_date_format(text: str, hit: bool) -> None:
    assert bool(_run(text, **_DATE)) is hit


def test_must_is_matched_whole_not_partial() -> None:
    """must 를 부분일치로 재면 틀린 표기가 통과한다.

    `2026. 01. 05.` 가 뒤에 붙은 `2026. 01. 05.15` 같은 값은 앞부분이 형식과
    맞아 search 로는 통과한다 — fullmatch 여야 잡힌다.
    """
    got = _run("기간 2026. 01. 0515", **_DATE)
    assert got, "부분일치로 재고 있다"


# ── 지적의 모양 ─────────────────────────────────────────────────────

def test_finding_carries_a_quote_from_the_document() -> None:
    """인용이 없으면 화면이 그 자리를 못 짚는다. 값만 실으면 같은 값이 여러 번
    나오는 문서에서 엉뚱한 곳을 짚으므로 앞뒤를 함께 싣는다."""
    got = _run("총 10,000 건을 처리했다", forbid=r"\d{1,3}(,\d{3})+", message="쉼표")
    assert got and got[0].evidence
    quote = got[0].evidence[0].quote
    assert "10,000" in quote
    assert len(quote) > len("10,000"), "앞뒤 맥락 없이 값만 실었다"


def test_severity_is_minor() -> None:
    """표기 규칙은 '고쳐야 하지만 이대로도 낼 수는 있는' 것이다(CLAUDE.md 심각도)."""
    got = _run("95%", forbid=r"\d%", message="공백")
    assert got[0].severity.value == "minor"


def test_rule_id_is_carried_so_findings_reach_their_criterion() -> None:
    """한 문서에 이 검사가 여럿 붙는다(표기 8건). rule_id 로 갈라야 화면이
    지적을 제 기준 아래에 붙인다."""
    got = _run("95%", forbid=r"\d%", message="공백", rule_id="표기-4")
    assert got[0].rule_id == "표기-4"


def test_flood_is_capped_and_says_so() -> None:
    """같은 실수가 문서 전체에 퍼지면 수백 건이 나와 화면이 그것만으로 덮인다.
    자르되 **잘랐다는 사실을 밝힌다** — 조용히 자르면 '이만큼만 있다'가 거짓이 된다."""
    text = " ".join(f"{i}%" for i in range(100))
    got = TextPatternChecker(forbid=r"\d%", message="공백").check(_doc(text))
    flagged = [f for f in got if not f.unreviewed]
    notice = [f for f in got if f.unreviewed]
    assert len(flagged) == 30
    assert notice and "넘어" in notice[0].message
