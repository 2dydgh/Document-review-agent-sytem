from modules.shared import Anchor, Document, Section, Severity
from modules.shared import Context
from modules.agent_trace import TraceabilityChecker
from modules.llm_client import EchoLLM


class _Review:
    def __init__(self, id_pattern, scope_pattern="", id_rollup_separator=""):
        self.id_pattern = id_pattern
        self.scope_pattern = scope_pattern
        self.id_rollup_separator = id_rollup_separator


def _sec(sid, text):
    return Section(id=sid, title=sid, level=1, text=text,
                   anchor=Anchor(page=None, section=sid), children=[])


def _doc(pairs):
    return Document(source_path="d.md", doc_type=None,
                    sections=[_sec(sid, text) for sid, text in pairs])


def _ctx(child):
    return Context(review=_Review(r"SR-\d+"), llm=EchoLLM(), chunks=[], other=child)


def test_no_ids_anywhere_is_reported_not_silently_passed():
    """실제로 겪은 사고: 기본 체크리스트(SR-\\d+)로 RQ-... 문서를 검토하니
    "지적사항 0건"이 떴다. 검토를 못 한 것이지 통과한 게 아니다."""
    parent = _doc([("1", "요건 없음")])
    child = _doc([("a", "설계만 있음")])
    findings = TraceabilityChecker().check(parent, _ctx(child))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity is Severity.INFO
    assert "한 건도 찾지 못했습니다" in f.message
    assert "SR-" in f.message              # 어떤 패턴을 썼는지 밝힌다
    assert "id_pattern" in f.suggestion


def test_ids_on_only_one_side_reports_unreviewed_not_flood():
    """수정 2026-08-06 채택: 하위문서 ID 0건은 대개 추출 실패(책갈피 없는 PDF·
    패턴 불일치)다 — 상위 ID 전부를 MAJOR 누락으로 쏟으면 오탐 폭주가 된다.
    '전부 누락'이라는 확신이 없으므로 미검토 INFO 로 드러낸다(모르면 모른다고 말한다).
    (예전 이름 test_ids_on_only_one_side_still_runs_normally 의 단정을 뒤집는
    의도 변경 — 3way 통합 보고서에 기재됨)"""
    parent = _doc([("1", "SR-001")])
    findings = TraceabilityChecker().check(parent, _ctx(_doc([("a", "무관")])))
    assert len(findings) == 1
    f = findings[0]
    assert f.severity is Severity.INFO
    assert f.unreviewed
    assert "하위문서" in f.message


def _scoped_ctx(child, scope):
    return Context(review=_Review(r"SR-[A-Z]{2}-\d+", scope), llm=EchoLLM(),
                   chunks=[], other=child)


def test_out_of_scope_missing_id_is_not_flagged():
    """실제 문서에서 누락 76건 중 73건이 이 소음이었다. scope 필터링 검증.
    픽스처에 dummy ID 추가(2026-08-11): 편측 0건 가드를 우회해 in_scope()
    필터링 로직이 실행되도록 한다. parent/child 양쪽에 SR-ZZ-999 추가."""
    parent = _doc([("1", "SR-PR-001 담당"), ("2", "SR-VP-001 남의 몫"), ("3", "SR-ZZ-999 검증")])
    findings = TraceabilityChecker().check(
        parent, _scoped_ctx(_doc([("a", "SR-ZZ-999 구현")]), r"SR-PR-\d+"))
    assert [f.message for f in findings] == ["하위문서에 누락된 ID: SR-PR-001"]


def test_scope_does_not_suppress_orphans():
    parent = _doc([("1", "SR-PR-001")])
    child = _doc([("a", "SR-PR-001"), ("b", "SR-VP-009")])
    findings = TraceabilityChecker().check(parent, _scoped_ctx(child, r"SR-PR-\d+"))
    assert [f.document for f in findings] == ["child"]
    assert "SR-VP-009" in findings[0].message


def test_empty_scope_keeps_old_behaviour():
    """픽스처에 dummy ID 추가(2026-08-11): 편측 0건 가드를 우회해 원래
    검증 대상(parent_ids에서 scope 필터링)이 실행되도록 한다. parent/child 양쪽에 SR-ZZ-999 추가."""
    parent = _doc([("1", "SR-VP-001"), ("2", "SR-ZZ-999")])
    findings = TraceabilityChecker().check(parent, _scoped_ctx(_doc([("a", "SR-ZZ-999")]), ""))
    assert len(findings) == 1 and findings[0].document == "parent"


def test_missing_id_in_child_is_flagged_on_parent():
    parent = _doc([("1", "SR-001 정의"), ("2", "SR-002 정의")])
    child = _doc([("a", "SR-002 구현")])
    findings = TraceabilityChecker().check(parent, _ctx(child))
    miss = [f for f in findings if "SR-001" in f.message]
    assert len(miss) == 1
    assert miss[0].document == "parent"
    assert miss[0].severity == Severity.MAJOR
    assert miss[0].anchor.section == "1"


def test_orphan_id_in_child_is_flagged_on_child():
    parent = _doc([("1", "SR-002 정의")])
    child = _doc([("a", "SR-002 구현"), ("b", "SR-003 구현")])
    findings = TraceabilityChecker().check(parent, _ctx(child))
    orphan = [f for f in findings if "SR-003" in f.message]
    assert len(orphan) == 1
    assert orphan[0].document == "child"


def test_matched_ids_produce_no_finding():
    parent = _doc([("1", "SR-002 정의")])
    child = _doc([("a", "SR-002 구현")])
    assert TraceabilityChecker().check(parent, _ctx(child)) == []


def test_no_other_returns_empty():
    """문서가 하나면 추적성은 아예 적용 대상이 아니다 — 할 말이 없다."""
    parent = _doc([("1", "SR-001")])
    ctx_no_other = Context(review=_Review(r"SR-\d+"), llm=EchoLLM(), chunks=[], other=None)
    assert TraceabilityChecker().check(parent, ctx_no_other) == []


def test_no_pattern_reports_not_checked():
    """두 문서를 받았는데 ID 형식이 없으면 "못 했음"이다.

    조용한 0건은 "대조해 봤더니 다 맞더라"로 읽힌다. 어느 팀 기준도 ID 형식을
    적지 않아 문서 비교가 통째로 이 경로를 탄다.
    """
    parent = _doc([("1", "SR-001")])
    ctx_no_pat = Context(review=_Review(""), llm=EchoLLM(), chunks=[], other=parent)
    findings = TraceabilityChecker().check(parent, ctx_no_pat)
    assert [f.severity for f in findings] == [Severity.INFO]
    assert findings[0].unreviewed


# --- 하위요건 롤업 --------------------------------------------------------

_SUB = r"FR-[A-Z]{2,4}(?:_\d+)+"


def _sub_ctx(child, sep="_"):
    return Context(review=_Review(_SUB, id_rollup_separator=sep),
                   llm=EchoLLM(), chunks=[], other=child)


def test_rolled_up_sub_requirement_is_not_reported_as_missing():
    """부모 수준에서 검증됐으면 누락이 아니다. 실측(SHN34)에서 이 오탐이 46건이었다."""
    parent = _doc([("1", "FR-CCG_01 정의"), ("2", "FR-CCG_01_01 세부")])
    child = _doc([("a", "FR-CCG_01 검증")])
    assert TraceabilityChecker().check(parent, _sub_ctx(child)) == []


def test_rollup_target_in_child_is_not_an_orphan():
    """접힌 상대(부모 ID)를 근거없음이라 하면 오탐을 반대편으로 옮길 뿐이다."""
    parent = _doc([("1", "FR-CCG_01_01 세부")])      # 부모 ID는 상위문서에 없다
    child = _doc([("a", "FR-CCG_01 검증")])
    assert TraceabilityChecker().check(parent, _sub_ctx(child)) == []


def test_missing_parent_is_still_reported_when_rollup_on():
    """롤업을 켰다고 진짜 누락까지 덮으면 안 된다."""
    parent = _doc([("1", "FR-CCG_09_01 세부")])
    child = _doc([("a", "FR-CCG_01 검증")])
    miss = [f for f in TraceabilityChecker().check(parent, _sub_ctx(child))
            if f.document == "parent"]
    assert [f.severity for f in miss] == [Severity.MAJOR]
    assert "FR-CCG_09_01" in miss[0].message
