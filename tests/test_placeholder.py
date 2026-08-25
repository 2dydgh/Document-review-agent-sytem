from dataclasses import dataclass, field

from modules.llm_client import EchoLLM
from modules.shared import Anchor, Document, Section, Severity
from modules.shared import Context
from modules.agent_format import PlaceholderChecker
from modules.report import collect


@dataclass
class _Review:
    placeholder_markers: list[str] = field(default_factory=lambda: ["TBD"])


def _sec(sid, text):
    return Section(id=sid, title=sid, level=1, text=text,
                   anchor=Anchor(page=None, section=sid), children=[])


def _doc(pairs):
    return Document(source_path="d.hwpx", doc_type=None,
                    sections=[_sec(sid, text) for sid, text in pairs])


def _ctx(markers=None):
    review = _Review() if markers is None else _Review(markers)
    return Context(review=review, llm=EchoLLM(), chunks=[])


def test_tbd_line_is_flagged_with_the_line_quoted():
    doc = _doc([("2.2.1", "| DS-SCD-PR-01-010 | 결과 저장 | TBD |")])
    findings = PlaceholderChecker().check(doc, _ctx())
    assert len(findings) == 1
    f = findings[0]
    assert f.severity is Severity.MAJOR
    assert "DS-SCD-PR-01-010" in f.message   # 어느 항목인지 보여야 고칠 수 있다
    assert f.anchor.section == "2.2.1"
    assert f.checker == "completeness"


def test_clean_document_produces_nothing():
    doc = _doc([("1", "요구사항은 모두 확정되었다.")])
    assert PlaceholderChecker().check(doc, _ctx()) == []


def test_marker_inside_a_word_is_not_flagged():
    """단어 경계가 없으면 'TBDX' 같은 식별자까지 지적한다."""
    doc = _doc([("1", "코드명 TBDX-1은 확정본이다."), ("2", "SUBTBD 항목")])
    assert PlaceholderChecker().check(doc, _ctx()) == []


def test_marker_is_case_insensitive():
    doc = _doc([("1", "결정 사항: tbd")])
    assert len(PlaceholderChecker().check(doc, _ctx())) == 1


def test_repeated_identical_line_is_reported_once_with_its_count():
    """collect()가 같은 절의 똑같은 줄을 중복으로 합쳐 개수를 조용히 줄인다.

    실제 상세설계서에서 TBD 23줄이 18건으로 줄어 5건이 사라졌다.
    """
    doc = _doc([("3.1.3.1", "| TBD | TBD |\n다른 줄\n| TBD | TBD |")])
    findings = collect(PlaceholderChecker().check(doc, _ctx()))
    assert len(findings) == 1
    assert "(이 절에 2회)" in findings[0].message


def test_single_occurrence_has_no_repeat_note():
    doc = _doc([("1", "| 설명 | TBD |")])
    assert "회)" not in PlaceholderChecker().check(doc, _ctx())[0].message


def test_same_line_in_different_sections_is_two_findings():
    doc = _doc([("1", "| 설명 | TBD |"), ("2", "| 설명 | TBD |")])
    findings = collect(PlaceholderChecker().check(doc, _ctx()))
    assert {f.anchor.section for f in findings} == {"1", "2"}


def test_markers_are_configurable():
    doc = _doc([("1", "이 값은 미정이다."), ("2", "TBD")])
    findings = PlaceholderChecker().check(doc, _ctx(["미정"]))
    assert len(findings) == 1 and "미정" in findings[0].message


def test_korean_marker_matches_inside_a_phrase():
    r"""\b는 한글에 쓸 수 없다. "미정이다"의 정과 이 사이엔 경계가 없어 안 잡힌다."""
    doc = _doc([("1", "일정은 미정이며 추후 확정한다.")])
    assert len(PlaceholderChecker().check(doc, _ctx(["미정"]))) == 1


def test_ascii_marker_still_respects_word_boundary():
    doc = _doc([("1", "코드 TBDX는 확정본"), ("2", "값: TBD")])
    findings = PlaceholderChecker().check(doc, _ctx(["TBD"]))
    assert [f.anchor.section for f in findings] == ["2"]


def test_empty_marker_list_disables_the_check():
    doc = _doc([("1", "TBD")])
    assert PlaceholderChecker().check(doc, _ctx([])) == []


def test_long_line_is_truncated_in_the_message():
    doc = _doc([("1", "TBD " + "가" * 200)])
    msg = PlaceholderChecker().check(doc, _ctx())[0].message
    assert msg.endswith("…") and len(msg) < 160


def test_document_label_is_carried_for_two_document_reviews():
    doc = _doc([("1", "TBD")])
    findings = PlaceholderChecker(document="child").check(doc, _ctx())
    assert findings[0].document == "child"


def test_default_document_label_is_none():
    doc = _doc([("1", "TBD")])
    assert PlaceholderChecker().check(doc, _ctx())[0].document is None


def test_missing_config_key_falls_back_to_tbd():
    """체크리스트에 placeholder_markers가 없어도 TBD는 잡아야 한다."""
    class _Bare:
        pass

    doc = _doc([("1", "TBD")])
    ctx = Context(review=_Bare(), llm=EchoLLM(), chunks=[])
    assert len(PlaceholderChecker().check(doc, ctx)) == 1
