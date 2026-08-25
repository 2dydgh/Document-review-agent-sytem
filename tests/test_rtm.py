import json as _json

from modules.shared import Anchor, Document, Section
from modules.report import render_rtm_json, render_rtm_markdown
from modules.agent_trace import build_rtm

PATTERN = r"SR-\d+"


def _sec(sid, text):
    return Section(id=sid, title=sid, level=1, text=text,
                   anchor=Anchor(page=None, section=sid), children=[])


def _doc(pairs):
    return Document(source_path="d.md", doc_type=None,
                    sections=[_sec(sid, text) for sid, text in pairs])


def _by_status(rows):
    return {s: [r for r in rows if r.status == s]
            for s in ("linked", "missing", "orphan")}


def test_build_rtm_covers_linked_missing_orphan():
    parent = _doc([("1", "SR-001 정의"), ("2", "SR-002 정의"), ("3", "SR-003 정의")])
    child = _doc([("a", "SR-001 구현"), ("b", "SR-009 캐시")])
    rows = build_rtm(parent, child, PATTERN)
    groups = _by_status(rows)

    assert {r.upper_id for r in groups["linked"]} == {"SR-001"}
    assert groups["linked"][0].lower_ids == ["SR-001"]
    assert {r.upper_id for r in groups["missing"]} == {"SR-002", "SR-003"}
    assert groups["missing"][0].lower_ids == []
    assert {r.lower_ids[0] for r in groups["orphan"]} == {"SR-009"}
    assert groups["orphan"][0].upper_id is None


def test_build_rtm_preserves_parent_order_then_orphans():
    parent = _doc([("1", "SR-002"), ("2", "SR-001")])
    child = _doc([("a", "SR-001"), ("b", "SR-005")])
    rows = build_rtm(parent, child, PATTERN)
    assert [r.upper_id for r in rows] == ["SR-002", "SR-001", None]
    assert rows[-1].status == "orphan" and rows[-1].lower_ids == ["SR-005"]


def test_build_rtm_all_linked():
    parent = _doc([("1", "SR-001")])
    child = _doc([("a", "SR-001 구현")])
    rows = build_rtm(parent, child, PATTERN)
    assert len(rows) == 1 and rows[0].status == "linked"


def _by_id(rows):
    return {r.upper_id: r.status for r in rows if r.upper_id}


SCOPE = r"SR-PR-\d+"


def test_out_of_scope_upper_ids_are_not_missing():
    """부분 설계서는 남의 요건을 다루지 않는다. 그걸 '누락'이라 하면 소음이다."""
    parent = _doc([("1", "SR-PR-001 담당"), ("2", "SR-VP-001 남의 몫")])
    child = _doc([("a", "무관")])
    rows = build_rtm(parent, child, r"SR-[A-Z]{2}-\d+", SCOPE)
    assert _by_id(rows) == {"SR-PR-001": "missing", "SR-VP-001": "out_of_scope"}


def test_out_of_scope_rows_are_kept_not_deleted():
    """조용히 지우면 진짜 누락이 거기 묻힌다. 세어 보여줘야 한다."""
    parent = _doc([("1", "SR-VP-001"), ("2", "SR-VP-002")])
    child = _doc([("a", "무관")])
    rows = build_rtm(parent, child, r"SR-[A-Z]{2}-\d+", SCOPE)
    assert len(rows) == 2
    assert all(r.status == "out_of_scope" for r in rows)


def test_linked_wins_over_out_of_scope():
    """하위문서가 실제로 참조했으면 범위 밖일 리 없다. 연결로 본다."""
    parent = _doc([("1", "SR-VP-001")])
    child = _doc([("a", "SR-VP-001 구현")])
    rows = build_rtm(parent, child, r"SR-[A-Z]{2}-\d+", SCOPE)
    assert rows[0].status == "linked"


def test_empty_scope_means_everything_in_scope():
    parent = _doc([("1", "SR-VP-001")])
    child = _doc([("a", "무관")])
    assert build_rtm(parent, child, r"SR-[A-Z]{2}-\d+", "")[0].status == "missing"


def test_scope_does_not_affect_orphans():
    """하위에만 있는 ID는 범위와 무관하게 근거없음이다."""
    parent = _doc([("1", "SR-PR-001")])
    child = _doc([("a", "SR-PR-001"), ("b", "SR-VP-009")])
    rows = build_rtm(parent, child, r"SR-[A-Z]{2}-\d+", SCOPE)
    orphans = [r for r in rows if r.status == "orphan"]
    assert [r.lower_ids for r in orphans] == [["SR-VP-009"]]


# --- 하위요건 롤업 --------------------------------------------------------
# 상위문서가 요건을 더 잘게 쪼개 쓰고(FR-CCG_01_01) 하위문서는 부모 수준
# (FR-CCG_01)에서만 검증하는 문서쌍이 있다. 실측(SHN34 SRS↔RVVR): 누락 54건
# 중 46건이 이것이었고, 46건 전부 부모 ID가 하위문서에 있었다 — 즉 전부 오탐.
# 접는 규칙은 문서마다 다르므로 구분자를 체크리스트에서 준다(빈 값이면 끔).

SUB = r"FR-[A-Z]{2,4}(?:_\d+)+"


def test_sub_requirement_rolls_up_to_parent_id():
    parent = _doc([("1", "FR-CCG_01 정의"), ("2", "FR-CCG_01_01 세부")])
    child = _doc([("a", "FR-CCG_01 검증")])
    rows = build_rtm(parent, child, SUB, rollup_separator="_")
    assert _by_id(rows) == {"FR-CCG_01": "linked", "FR-CCG_01_01": "rolled_up"}


def test_rolled_up_row_records_the_parent_it_matched():
    """무엇에 접혔는지 남겨야 검토자가 되짚을 수 있다."""
    parent = _doc([("1", "FR-CCG_01_01 세부")])
    child = _doc([("a", "FR-CCG_01 검증")])
    rows = build_rtm(parent, child, SUB, rollup_separator="_")
    assert rows[0].lower_ids == ["FR-CCG_01"]


def test_rollup_target_is_not_counted_as_orphan():
    """접힌 상대를 근거없음으로 세면 오탐이 반대편으로 옮겨갈 뿐이다."""
    parent = _doc([("1", "FR-CCG_01_01 세부")])
    child = _doc([("a", "FR-CCG_01 검증")])
    rows = build_rtm(parent, child, SUB, rollup_separator="_")
    assert [r.status for r in rows] == ["rolled_up"]


def test_rollup_off_by_default_keeps_missing():
    """기본은 꺼짐. 켜지 않은 문서쌍의 판정을 조용히 바꾸면 안 된다."""
    parent = _doc([("1", "FR-CCG_01_01 세부")])
    child = _doc([("a", "FR-CCG_01 검증")])
    assert build_rtm(parent, child, SUB)[0].status == "missing"


def test_rollup_does_not_invent_a_parent_that_is_absent():
    """부모가 하위문서에 없으면 진짜 누락이다. 접어서 덮으면 결함이 사라진다."""
    parent = _doc([("1", "FR-CCG_09_01 세부")])
    child = _doc([("a", "FR-CCG_01 검증")])
    assert build_rtm(parent, child, SUB, rollup_separator="_")[0].status == "missing"


def test_direct_link_wins_over_rollup():
    parent = _doc([("1", "FR-CCG_01_01 세부")])
    child = _doc([("a", "FR-CCG_01_01 검증"), ("b", "FR-CCG_01 도")])
    assert build_rtm(parent, child, SUB, rollup_separator="_")[0].status == "linked"


def test_rollup_is_single_level_only():
    """한 단계만 접는다. 끝까지 접으면 FR-CCG 같은 비-ID까지 부모로 삼는다."""
    parent = _doc([("1", "FR-CCG_01_01_01 손자")])
    child = _doc([("a", "FR-CCG_01 검증")])
    assert build_rtm(parent, child, SUB, rollup_separator="_")[0].status == "missing"


def test_build_rtm_empty_pattern_returns_empty():
    parent = _doc([("1", "SR-001")])
    assert build_rtm(parent, parent, "") == []


def test_missing_anchor_points_to_parent_section():
    parent = _doc([("7", "SR-042 정의")])
    child = _doc([("a", "무관")])
    rows = build_rtm(parent, child, PATTERN)
    assert rows[0].status == "missing"
    assert rows[0].anchor.section == "7"


def _sample_rows():
    parent = _doc([("1", "SR-001"), ("2", "SR-003")])
    child = _doc([("a", "SR-001"), ("b", "SR-009")])
    return build_rtm(parent, child, PATTERN)


def test_render_rtm_markdown_shows_full_table_and_counts():
    md = render_rtm_markdown(_sample_rows(), [], "srs.md ↔ sdd.md")
    assert "추적성 매트릭스" in md
    assert "| 상위 ID | 하위 연결 | 상태 |" in md
    # 연결된 항목도 표에 보인다 (예외만 나오는 게 아님)
    assert "SR-001" in md and "연결됨" in md
    assert "누락" in md and "근거없음" in md
    assert "연결 1, 누락 1, 근거없음 1" in md


def test_render_rtm_markdown_action_section_from_findings():
    from modules.shared import Finding, Severity
    findings = [Finding(checker="traceability", severity=Severity.MAJOR,
                        message="하위문서에 누락된 ID: SR-003",
                        anchor=Anchor(None, "2"), suggestion="반영하세요",
                        document="parent")]
    md = render_rtm_markdown(_sample_rows(), findings, "s ↔ d")
    assert "조치 필요 (1건)" in md
    assert "SR-003" in md and "반영하세요" in md


def test_render_rtm_json_structure():
    payload = _json.loads(render_rtm_json(_sample_rows(), [], "s ↔ d"))
    assert payload["summary"] == {"total": 3, "linked": 1, "missing": 1,
                                  "orphan": 1, "out_of_scope": 0,
                                  "rolled_up": 0}
    statuses = [r["status"] for r in payload["rtm"]]
    assert statuses.count("linked") == 1
    orphan = next(r for r in payload["rtm"] if r["status"] == "orphan")
    assert orphan["upper_id"] is None and orphan["lower_ids"] == ["SR-009"]
    assert "findings" in payload  # 기존 예외 목록도 유지


def _scoped_rows():
    parent = _doc([("1", "SR-PR-001"), ("2", "SR-PR-002"), ("3", "SR-VP-001")])
    child = _doc([("a", "SR-PR-001")])
    return build_rtm(parent, child, r"SR-[A-Z]{2}-\d+", r"SR-PR-\d+")


def test_render_rtm_markdown_reports_out_of_scope_count():
    md = render_rtm_markdown(_scoped_rows(), [], "s ↔ d")
    assert "연결 1, 누락 1, 근거없음 0, 범위 밖 1(검사 안 함)" in md
    assert "➖ 범위 밖" in md


def test_render_rtm_markdown_omits_out_of_scope_when_zero():
    md = render_rtm_markdown(_sample_rows(), [], "s ↔ d")
    assert "범위 밖" not in md


def test_render_rtm_json_has_out_of_scope_in_summary():
    payload = _json.loads(render_rtm_json(_scoped_rows(), [], "s ↔ d"))
    assert payload["summary"]["out_of_scope"] == 1
    assert payload["summary"]["missing"] == 1
    assert {r["status"] for r in payload["rtm"]} == {"linked", "missing", "out_of_scope"}


def test_render_rtm_json_hangul_not_escaped():
    payload_str = render_rtm_json(_sample_rows(), [], "상위 ↔ 하위")
    assert "상위" in payload_str
