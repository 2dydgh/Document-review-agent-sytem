"""작성일자 선후 관계 (`rule: nondecreasing`).

문서 간 md §4: 의뢰서 작성 → 계획서 작성 → 설계서 작성 → 시험 수행 순으로 전체
프로젝트의 날짜 흐름이 꼬이지 않아야 한다.

`exact`(전부 같은가) 와 판정 모양이 다르다 — 여기서는 **순서**가 값이다.
"""
from modules.agent_trace import CaseWideRule, compare_case_wide
from modules.doc_parser import FieldValue
from modules.shared import Anchor


def _vals(**by_output):
    return {k: {"작성일자": FieldValue(name="작성일자", value=v, found=v is not None,
                                    anchor=Anchor(1, None))}
            for k, v in by_output.items()}


RULE = CaseWideRule(id="W-작성일자-순서", field="작성일자", rule="nondecreasing",
                    outputs=("시험의뢰서", "시험계획서", "시험설계서"))


def test_순서대로면_일치():
    got = compare_case_wide(_vals(시험의뢰서="2026. 01. 01.", 시험계획서="2026. 01. 02.",
                                 시험설계서="2026. 01. 03."), RULE)
    assert got.status == "일치" and got.finding is None


def test_같은_날이면_일치():
    """같은 날 작성은 정상이다. 커지거나 같으면 된다."""
    got = compare_case_wide(_vals(시험의뢰서="2026. 01. 02.", 시험계획서="2026. 01. 02.",
                                 시험설계서="2026. 01. 02."), RULE)
    assert got.status == "일치"


def test_뒤집히면_그_쌍을_짚는다():
    got = compare_case_wide(_vals(시험의뢰서="2026. 01. 05.", 시험계획서="2026. 01. 02.",
                                 시험설계서="2026. 01. 03."), RULE)
    assert got.status == "불일치"
    msg = got.finding.message
    assert "선후가 뒤집혔습니다" in msg
    assert "시험의뢰서" in msg and "시험계획서" in msg
    # 어긋나지 않은 쌍까지 나열하면 어디가 문제인지 안 보인다.
    assert "시험설계서 '2026. 01. 03.'" not in msg


def test_못_읽은_날짜는_미검토다():
    """형식이 안 맞으면 비교하지 않는다 — 비교 못 할 값을 비교한 것처럼 보이면 안 된다."""
    got = compare_case_wide(_vals(시험의뢰서="2026. 01. 01.", 시험계획서="작성중",
                                 시험설계서="2026. 01. 03."), RULE)
    assert got.status == "미검토"
    assert got.finding.unreviewed and "시험계획서" in got.finding.message


def test_못_찾은_산출물도_미검토다():
    got = compare_case_wide(_vals(시험의뢰서="2026. 01. 01.", 시험계획서=None,
                                 시험설계서="2026. 01. 03."), RULE)
    assert got.status == "미검토" and "시험계획서" in got.finding.message


def test_뒤집힘이_미검토를_이긴다():
    """미검토가 불일치를 덮으면 틀린 것이 안 보인다(exact 와 같은 처방)."""
    got = compare_case_wide(_vals(시험의뢰서="2026. 01. 05.", 시험계획서="2026. 01. 02.",
                                 시험설계서=None), RULE)
    assert got.status == "불일치"


def test_짚는_칸은_쌍의_뒤_문서다():
    """의뢰서 1/10 → 계획서 1/05 라면 틀린 쪽은 계획서다.

    앞을 짚으면 검토자가 멀쩡한 의뢰서를 고치고, 진짜 역전은 다음 검토에도 남는다.
    """
    got = compare_case_wide(_vals(시험의뢰서="2026. 01. 10.", 시험계획서="2026. 01. 05.",
                                  시험설계서="2026. 01. 20."), RULE)
    ok = {c.output: c.ok for c in got.cells}
    assert ok == {"시험의뢰서": True, "시험계획서": False, "시험설계서": True}
    assert got.finding.anchor is not None
