"""필수 절 검사 — 번호로 찾고 제목으로 대조한다.

실측(2026-07-22): 두 RVVR 이 4.0 을 각각 "Definitions and Abbreviations" 와
"Definition of Terms" 로 적었다. 정확 일치로 대조하면 후자가 "누락"으로 뜨는데
절은 분명히 있다 — 없는 결함을 만들어내는 것이다.
"""
from modules.llm_client import EchoLLM
from modules.shared import Anchor, Document, Section, Severity
from modules.shared import Context
from modules.agent_format import CompletenessChecker


class _Review:
    def __init__(self, required_sections):
        self.required_sections = required_sections


def _sec(title, sid="1"):
    return Section(id=sid, title=title, level=1, text="본문",
                   anchor=Anchor(page=None, section=sid), children=[])


def _doc(titles):
    return Document(source_path="d.pdf", doc_type=None,
                    sections=[_sec(t, str(i)) for i, t in enumerate(titles, 1)])


def _ctx(required):
    return Context(review=_Review(required), llm=EchoLLM(), chunks=[])


def test_exact_numbered_match_is_clean():
    findings = CompletenessChecker().check(
        _doc(["1.0 Purpose", "2.0 Scope"]), _ctx(["1.0 Purpose", "2.0 Scope"]))
    assert findings == []


def test_missing_number_is_major():
    findings = CompletenessChecker().check(
        _doc(["1.0 Purpose"]), _ctx(["1.0 Purpose", "3.0 References"]))
    assert [f.severity for f in findings] == [Severity.MAJOR]
    assert "3.0 References" in findings[0].message


def test_same_number_different_title_is_minor():
    """절은 있는데 제목만 다르다. 누락이 아니다 — 실측된 실제 사례다."""
    findings = CompletenessChecker().check(
        _doc(["4.0 Definition of Terms"]),
        _ctx(["4.0 Definitions and Abbreviations"]))
    assert [f.severity for f in findings] == [Severity.MINOR]
    msg = findings[0].message
    assert "Definition of Terms" in msg             # 문서에 있는 것
    assert "Definitions and Abbreviations" in msg   # 표준


def test_title_mismatch_anchors_to_the_section_found():
    """어느 절인지 짚어줘야 검토자가 찾아간다."""
    doc = Document(source_path="d.pdf", doc_type=None,
                   sections=[_sec("4.0 Definition of Terms", sid="7")])
    findings = CompletenessChecker().check(
        doc, _ctx(["4.0 Definitions and Abbreviations"]))
    assert findings[0].anchor.section == "7"


def test_whitespace_differences_are_not_a_mismatch():
    """PDF 추출은 자간 때문에 공백을 흘린다. 공백 차이로 지적하면 소음이다."""
    findings = CompletenessChecker().check(
        _doc(["4.0  Definitions   and Abbreviations"]),
        _ctx(["4.0 Definitions and Abbreviations"]))
    assert findings == []


def test_case_differences_are_a_mismatch():
    """표기 통일이 검사 목적이다. 내부검토 체크리스트가 대소문자까지 요구한다."""
    findings = CompletenessChecker().check(
        _doc(["4.0 Definitions And Abbreviations"]),
        _ctx(["4.0 Definitions and Abbreviations"]))
    assert [f.severity for f in findings] == [Severity.MINOR]


def test_unnumbered_entry_keeps_exact_match():
    """번호 없는 항목은 예전 그대로. 무번호 문서(한국어 docx)가 실재한다."""
    assert CompletenessChecker().check(_doc(["목적", "범위"]),
                                       _ctx(["목적", "범위"])) == []
    findings = CompletenessChecker().check(_doc(["목적"]), _ctx(["참고문헌"]))
    assert [f.severity for f in findings] == [Severity.MAJOR]


def test_deeper_number_does_not_satisfy_a_top_level_requirement():
    """3.1.1 이 3.1 을 대신하면 안 된다."""
    findings = CompletenessChecker().check(
        _doc(["3.1.1 Regulations"]), _ctx(["3.1 References"]))
    assert [f.severity for f in findings] == [Severity.MAJOR]


def test_empty_required_reports_not_checked():
    """필수 절 목록이 없으면 "이상 없음"이 아니라 "못 했음"이다.

    조용한 0건을 내면 required_sections 를 안 적은 여섯 팀이 필수 절 검사를
    통과한 것처럼 보인다.
    """
    findings = CompletenessChecker().check(_doc(["1.0 Purpose"]), _ctx([]))
    assert [f.severity for f in findings] == [Severity.INFO]
    assert findings[0].unreviewed


# --- 절 구조를 확인할 수 없는 문서 -----------------------------------------
# 책갈피 없는 PDF 는 절 제목이 "1쪽"·"2쪽"이다(실측: SKN56 CPS SRS 책갈피 0개).
# 번호 요건을 그대로 걸면 필수 절이 전부 누락으로 뜬다 — 문서의 결함이 아니라
# 검토를 못 했다는 뜻이다. 대량 오탐으로 내보내면 목록을 통째로 무시하게 된다.


def test_page_titled_document_reports_not_checked_instead_of_missing():
    doc = _doc(["1쪽", "2쪽", "3쪽"])
    findings = CompletenessChecker().check(
        doc, _ctx(["1.0 Purpose", "2.0 Scope"]))
    assert [f.severity for f in findings] == [Severity.INFO]
    assert "수행하지 않았습니다" in findings[0].message
    assert not any(f.severity is Severity.MAJOR for f in findings)


def test_the_not_checked_notice_is_reported_once():
    """요건 개수만큼 반복하면 그 자체가 소음이다."""
    findings = CompletenessChecker().check(
        _doc(["1쪽"]), _ctx(["1.0 Purpose", "2.0 Scope", "3.0 References"]))
    assert len(findings) == 1


def test_unnumbered_requirements_still_run_on_a_page_titled_document():
    """가드는 번호 요건에만 걸린다. 번호 없는 요건까지 끄면 정상 검사가 죽는다."""
    findings = CompletenessChecker().check(
        _doc(["1쪽", "목적"]), _ctx(["목적", "참고문헌", "1.0 Purpose"]))
    sev = sorted(f.severity.value for f in findings)
    assert sev == ["info", "major"]          # 참고문헌 누락 + 번호 요건 미검사
    assert any("참고문헌" in f.message for f in findings)


def test_documents_with_numbered_sections_are_checked_normally():
    """번호 절이 하나라도 있으면 가드가 걸리면 안 된다."""
    findings = CompletenessChecker().check(
        _doc(["1.0 Purpose", "9쪽"]), _ctx(["1.0 Purpose", "3.0 References"]))
    assert [f.severity for f in findings] == [Severity.MAJOR]


def test_mismatch_message_does_not_repeat_the_number():
    """실문서 검증에서 잡힌 버그: "4.0 '4.0 Definition of Terms'" 로 번호가 겹쳤다.

    부분 문자열만 보는 테스트로는 못 잡는다 — 겹쳐도 두 조각이 다 들어 있다.
    """
    findings = CompletenessChecker().check(
        _doc(["4.0 Definition of Terms"]),
        _ctx(["4.0 Definitions and Abbreviations"]))
    msg = findings[0].message
    assert "'Definition of Terms'" in msg
    assert "4.0 '4.0" not in msg
