from dataclasses import dataclass

from modules.llm_client import EchoLLM, Response
from modules.shared import Anchor, Document, Section, Severity
from modules.shared import Context
from modules.agent_trace import ContentMatchChecker


@dataclass
class _Review:
    id_pattern: str = r"SR-\d+"


class _ScriptedLLM:
    """정해진 문자열을 그대로 돌려준다. 호출된 프롬프트를 기록한다."""

    def __init__(self, text: str):
        self.text = text
        self.prompts: list[str] = []

    def complete(self, prompt: str, **opts) -> Response:
        self.prompts.append(prompt)
        return Response(text=self.text)


def _sec(sid, text):
    return Section(id=sid, title=sid, level=1, text=text,
                   anchor=Anchor(page=None, section=sid), children=[])


def _doc(pairs):
    return Document(source_path="d.md", doc_type=None,
                    sections=[_sec(sid, text) for sid, text in pairs])


def _ctx(llm, child, pattern=r"SR-\d+"):
    return Context(review=_Review(pattern), llm=llm, chunks=[], other=child)


PARENT = [("1", "SR-001 결제는 3초 이내에 응답해야 한다.")]
CHILD = [("2", "SR-001 결제 응답 목표는 5초로 한다.")]


def test_echo_llm_produces_no_findings():
    """LLM 백엔드가 없으면 지적사항을 지어내지 않는다. 이 성질이 깨지면 안 된다."""
    parent, child = _doc(PARENT), _doc(CHILD)
    assert ContentMatchChecker().check(parent, _ctx(EchoLLM(), child)) == []


def test_issue_response_becomes_a_finding():
    parent, child = _doc(PARENT), _doc(CHILD)
    llm = _ScriptedLLM(
        'ISSUE: 상위 "3초 이내에 응답" vs 하위 "5초로 한다" — 응답시간 충돌')
    findings = ContentMatchChecker().check(parent, _ctx(llm, child))
    assert len(findings) == 1
    f = findings[0]
    assert f.checker == "consistency"
    assert f.severity is Severity.MINOR  # 결정적 판정(major)보다 뒤로 정렬된다
    assert "SR-001" in f.message and "3초 이내에 응답" in f.message
    assert f.document is None            # UI에서 mismatch로 매핑된다
    assert f.anchor.section == "2"       # 하위문서(설계) 위치
    # 대조를 통과한 인용이 근거로 실린다 — 검증 없이 믿은 게 아니라는 증거.
    assert {e.quote for e in f.evidence} == {"3초 이내에 응답", "5초로 한다"}


def test_fabricated_quotes_are_dropped_and_reported():
    """지어낸 인용은 지적을 통과시키지 못한다 — 환각은 코드로 막는다.

    폐기는 조용히 하지 않는다: 건수가 INFO로 남아야 "지적이 없다"는
    거짓말이 되지 않는다(CLAUDE.md 계약)."""
    parent, child = _doc(PARENT), _doc(CHILD)
    llm = _ScriptedLLM(
        'ISSUE: 상위 "10초 이내 처리" vs 하위 "20초로 완화" — 지어낸 충돌')
    findings = ContentMatchChecker().check(parent, _ctx(llm, child))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity is Severity.INFO
    assert "1건" in f.message and "제외" in f.message


def test_issue_without_parseable_quotes_is_dropped():
    """인용 형식 없이 주장만 있는 ISSUE도 근거 0건 — 같은 길로 폐기된다."""
    parent, child = _doc(PARENT), _doc(CHILD)
    llm = _ScriptedLLM("ISSUE: 응답시간이 3초 vs 5초로 다르다")
    findings = ContentMatchChecker().check(parent, _ctx(llm, child))
    assert len(findings) == 1
    assert findings[0].severity is Severity.INFO
    assert "제외" in findings[0].message


def test_one_verified_side_keeps_the_finding():
    """문턱은 지적 전체에 건다 — 한쪽 인용이 대조를 통과하면 유지한다.

    (단일 검토 loop.py와 같은 규칙: found가 완전히 비어 있을 때만 폐기.
    "3초"처럼 짧아 검색을 건너뛴 쪽이 진짜 근거를 끌고 죽으면 안 된다.)"""
    parent, child = _doc(PARENT), _doc(CHILD)
    llm = _ScriptedLLM(
        'ISSUE: 상위 "3초 이내에 응답" vs 하위 "실재하지 않는 문장" — 절반 실재')
    findings = ContentMatchChecker().check(parent, _ctx(llm, child))
    minors = [f for f in findings if f.severity is Severity.MINOR]
    assert len(minors) == 1
    assert [e.quote for e in minors[0].evidence] == ["3초 이내에 응답"]


def test_llm_failure_is_reported_not_silently_passed():
    """실제로 겪은 사고: 타임아웃이 빈 응답이 되어 "모순 없음"으로 읽혔다.

    검토 도구가 실패를 통과로 보고하면, 사용자는 놓친 결함을 영원히 모른다.
    """
    class _FailingLLM:
        def complete(self, prompt, **opts):
            return Response(text="", error="240초 안에 응답 없음")

    parent, child = _doc(PARENT), _doc(CHILD)
    findings = ContentMatchChecker().check(parent, _ctx(_FailingLLM(), child))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity is Severity.INFO       # 판정이 아니라 "모르는 상태"
    assert "검토되지 않았습니다" in f.message
    assert "240초" in f.message              # 왜 실패했는지도 남긴다
    assert "SR-001" in f.message


def test_successful_empty_answer_produces_no_finding():
    """error 없는 빈 응답은 진짜 '모순 없음'이다. 실패와 구분되어야 한다."""
    class _OkEmptyLLM:
        def complete(self, prompt, **opts):
            return Response(text="", error=None)

    parent, child = _doc(PARENT), _doc(CHILD)
    assert ContentMatchChecker().check(parent, _ctx(_OkEmptyLLM(), child)) == []


def test_non_issue_response_is_ignored():
    parent, child = _doc(PARENT), _doc(CHILD)
    for reply in ["", "  ", "문제 없음", "괜찮아 보입니다", "issue: 소문자"]:
        assert ContentMatchChecker().check(parent, _ctx(_ScriptedLLM(reply), child)) == []


def test_only_linked_ids_are_compared():
    """누락(SR-002)/orphan(SR-009)은 TraceabilityChecker 몫 — LLM을 부르지 않는다."""
    parent = _doc([("1", "SR-001 a"), ("2", "SR-002 b")])
    child = _doc([("3", "SR-001 a"), ("4", "SR-009 c")])
    llm = _ScriptedLLM("")
    ContentMatchChecker().check(parent, _ctx(llm, child))
    assert len(llm.prompts) == 1
    assert "SR-001" in llm.prompts[0]
    assert "SR-002" not in llm.prompts[0] and "SR-009" not in llm.prompts[0]


def test_each_prompt_carries_only_its_own_requirement_line():
    """한 섹션에 여러 요건이 나열돼도 ID별로 자기 줄만 보낸다.

    섹션 전체를 보내면 LLM이 어느 요건을 판단하는지 흐려지고, 같은 텍스트를
    ID 수만큼 반복 전송하게 된다.
    """
    body = "- SR-001 로그인할 수 있다.\n- SR-002 로그아웃할 수 있다."
    parent = _doc([("1", body)])
    child = _doc([("2", body)])
    llm = _ScriptedLLM("")
    ContentMatchChecker().check(parent, _ctx(llm, child))

    assert len(llm.prompts) == 2
    first = next(p for p in llm.prompts if "'SR-001'" in p)
    assert "로그인할 수 있다" in first
    assert "SR-002" not in first and "로그아웃" not in first


def test_prompt_carries_both_sides_and_discourages_guessing():
    parent, child = _doc(PARENT), _doc(CHILD)
    llm = _ScriptedLLM("")
    ContentMatchChecker().check(parent, _ctx(llm, child))
    p = llm.prompts[0]
    assert "3초 이내" in p and "5초로 한다" in p
    assert "확실하지 않으면" in p


def test_prompt_rules_out_the_known_false_positives():
    """오탐 3건이 전부 "설계가 덜 상세하다"였다. 그 경계를 프롬프트가 명시해야 한다.

    이 문구가 사라지면 precision이 100%에서 57%로 떨어진다
    (scripts/eval_triage.py로 측정).
    """
    parent, child = _doc(PARENT), _doc(CHILD)
    llm = _ScriptedLLM("")
    ContentMatchChecker().check(parent, _ctx(llm, child))
    p = llm.prompts[0]
    assert "세부 조건(횟수·순서·수단)을 언급하지 않은 경우" in p  # 생략은 모순이 아니다
    assert "더 상세하거나" in p             # 구현 수단 추가도 모순이 아니다
    assert "다른 용어로 부른 경우" in p      # 동의어도 모순이 아니다
    assert "서로 다른 대상" in p            # 원본 vs 토큰: 대상이 다르면 모순이 아니다
    assert "인용할 수 없으면" in p           # 근거 인용 강제 (인용 못 하면 지어낸 것)


def test_prompt_does_not_use_the_ambiguous_example_as_a_contradiction():
    """'보관하지 않는다 vs 저장한다'를 모순 예시로 쓰면 27B가 토큰화 설계까지 지적한다.

    이 예시가 다시 들어오면 Qwen3.6-27B precision이 100%에서 71%로 떨어진다.
    """
    parent, child = _doc(PARENT), _doc(CHILD)
    llm = _ScriptedLLM("")
    ContentMatchChecker().check(parent, _ctx(llm, child))
    p = llm.prompts[0]
    head, _, tail = p.partition("모순이 **아니다**")
    assert "보관하지 않는다" not in head    # 모순 예시 목록에는 없어야 하고
    assert "보관하지 않는다" in tail        # 예외 규칙에는 있어야 한다


def test_no_child_or_no_pattern_is_a_noop():
    parent = _doc(PARENT)
    llm = _ScriptedLLM("ISSUE: 불러선 안 된다")
    assert ContentMatchChecker().check(
        parent, Context(review=_Review(), llm=llm, chunks=[], other=None)) == []
    assert ContentMatchChecker().check(parent, _ctx(llm, _doc(CHILD), pattern="")) == []
    assert llm.prompts == []
