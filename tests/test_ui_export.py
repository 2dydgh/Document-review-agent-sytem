import json as _json
import re

from modules.agent_trace import build_rtm
from modules.report import (
    render_review_ui_js,
    render_ui_js,
    to_ui_payload,
    to_ui_review_payload,
)
from modules.shared import Anchor, Document, Evidence, Finding, Section, Severity

PATTERN = r"SR-\d+"


def _sec(sid, text):
    return Section(id=sid, title=sid, level=1, text=text,
                   anchor=Anchor(page=None, section=sid), children=[])


def _doc(pairs):
    return Document(source_path="d.md", doc_type=None,
                    sections=[_sec(sid, text) for sid, text in pairs])


def _rows():
    parent = _doc([("1", "SR-001"), ("2", "SR-003")])
    child = _doc([("a", "SR-001"), ("b", "SR-009")])
    return build_rtm(parent, child, PATTERN)


def _finding(document, message, section):
    return Finding(checker="traceability", severity=Severity.MAJOR,
                   message=message, anchor=Anchor(None, section),
                   suggestion="고치세요", document=document)


def _findings():
    return [_finding("parent", "하위문서에 누락된 ID: SR-003", "2"),
            _finding("child", "상위문서에 근거 없는 ID: SR-009", "b")]


def test_stats_match_rtm_counts():
    payload = to_ui_payload(_rows(), _findings(), "srs.md", "sdd.md")
    # 상위 요건은 SR-001(연결) + SR-003(누락) = 2건. orphan은 요건 수에 안 들어간다.
    assert payload["stats"] == {"requirements": 2, "matched": 1, "missing": 1,
                                "mismatch": 0, "extra": 1, "out_of_scope": 0,
                                "rolled_up": 0}


def test_parent_finding_becomes_missing_on_side_a():
    payload = to_ui_payload(_rows(), _findings(), "srs.md", "sdd.md")
    miss = next(f for f in payload["findings"] if f["type"] == "missing")
    assert miss["a"] == "2" and miss["b"] is None
    assert "SR-003" in miss["message"] and miss["suggestion"] == "고치세요"


def test_child_finding_becomes_extra_on_side_b():
    payload = to_ui_payload(_rows(), _findings(), "srs.md", "sdd.md")
    extra = next(f for f in payload["findings"] if f["type"] == "extra")
    assert extra["a"] is None and extra["b"] == "b"


def test_finding_types_and_sevs_are_known_to_app_js():
    payload = to_ui_payload(_rows(), _findings(), "srs.md", "sdd.md")
    # app.js는 typeMeta/sevMeta에 없는 키를 만나면 렌더 중 터진다.
    assert {f["type"] for f in payload["findings"]} <= {"missing", "mismatch", "extra"}
    assert {f["sev"] for f in payload["findings"]} <= {
        "critical", "major", "minor", "info"}
    assert len({f["id"] for f in payload["findings"]}) == 2  # id는 고유해야 선택이 동작


def test_finding_without_document_falls_back_to_mismatch():
    f = Finding(checker="consistency", severity=Severity.MINOR, message="용어 불일치",
                anchor=Anchor(None, "1"), suggestion=None, document=None)
    payload = to_ui_payload(_rows(), [f], "srs.md", "sdd.md")
    got = payload["findings"][0]
    assert got["type"] == "mismatch"
    assert got["suggestion"] == ""      # None이면 렌더가 "null"을 출력함
    assert got["a"] is None and got["b"] == "1"   # 고칠 곳은 하위문서(설계)


def test_mismatch_count_reaches_the_stats_card():
    """'불일치' 카드가 하드코딩 0이 아니라 실제 triage 결과를 센다."""
    mismatch = Finding(checker="consistency", severity=Severity.MINOR,
                       message="[SR-001] 3초 vs 5초", anchor=Anchor(None, "2"),
                       document=None)
    payload = to_ui_payload(_rows(), _findings() + [mismatch], "srs.md", "sdd.md")
    assert payload["stats"]["mismatch"] == 1
    # 결정적 항목 수는 triage가 늘어나도 그대로다
    assert payload["stats"]["missing"] == 1 and payload["stats"]["extra"] == 1


def test_no_triage_findings_means_zero_mismatch():
    payload = to_ui_payload(_rows(), _findings(), "srs.md", "sdd.md")
    assert payload["stats"]["mismatch"] == 0


def test_out_of_scope_is_excluded_from_requirements_but_still_counted():
    """범위 밖은 매칭률 분모에서 빠지되, 화면에 개수가 보여야 한다."""
    parent = _doc([("1", "SR-PR-001"), ("2", "SR-PR-002"), ("3", "SR-VP-001")])
    child = _doc([("a", "SR-PR-001")])
    rows = build_rtm(parent, child, r"SR-[A-Z]{2}-\d+", r"SR-PR-\d+")
    stats = to_ui_payload(rows, [], "s.md", "d.md")["stats"]
    assert stats["requirements"] == 2      # 범위 밖 1건은 분모에서 제외
    assert stats["matched"] == 1 and stats["missing"] == 1
    assert stats["out_of_scope"] == 1      # 그러나 사라지지는 않는다


def test_out_of_scope_is_zero_without_a_scope_pattern():
    stats = to_ui_payload(_rows(), [], "s.md", "d.md")["stats"]
    assert stats["out_of_scope"] == 0


def test_llm_failure_is_visible_but_not_counted_as_mismatch():
    """판정 실패는 '불일치 1건'이 아니다. 목록에는 보이되 카드는 0이어야 한다."""
    failure = Finding(checker="consistency", severity=Severity.INFO,
                      message="[SR-001] LLM 판정 실패 — 이 항목은 검토되지 않았습니다",
                      anchor=Anchor(None, "2"), document=None)
    payload = to_ui_payload(_rows(), [failure], "srs.md", "sdd.md")
    assert payload["stats"]["mismatch"] == 0
    assert len(payload["findings"]) == 1              # 목록에는 남는다
    assert payload["findings"][0]["sev"] == "info"


def test_doc_names_come_from_paths():
    payload = to_ui_payload(_rows(), [], "data/srs_sample.md", "data/sdd_sample.md")
    assert payload["docA"]["name"] == "srs_sample.md"
    assert payload["docB"]["name"] == "sdd_sample.md"
    assert payload["docA"]["type"] == "MD"


def test_empty_rtm_yields_zero_requirements_not_crash():
    payload = to_ui_payload([], [], "a.md", "b.md")
    assert payload["stats"]["requirements"] == 0
    assert payload["findings"] == []


def test_render_ui_js_assigns_compare_and_guards_missing_global():
    js = render_ui_js(to_ui_payload(_rows(), _findings(), "srs.md", "sdd.md"))
    assert "window.DOCREVIEW.compare = {" in js
    assert "if (!window.DOCREVIEW) return;" in js
    assert "SR-003" in js  # 한글/ID가 이스케이프되지 않고 그대로


def test_render_ui_js_escapes_angle_bracket_to_survive_script_tag():
    f = _finding("parent", "누락: </script><script>alert(1)</script>", "1")
    js = render_ui_js(to_ui_payload(_rows(), [f], "a.md", "b.md"))
    assert "</script>" not in js
    assert "\\u003c/script>" in js


def test_render_ui_js_body_is_valid_json():
    js = render_ui_js(to_ui_payload(_rows(), _findings(), "srs.md", "sdd.md"))
    body = re.search(r"window\.DOCREVIEW\.compare = (\{.*\});", js, re.S).group(1)
    parsed = _json.loads(body.replace("\\u003c", "<"))
    assert parsed["stats"]["matched"] == 1
    assert len(parsed["stages"]) == 4


# ---- 단일 검토 ------------------------------------------------------------

def _review_findings():
    return [
        Finding(checker="completeness", severity=Severity.MAJOR,
                message="필수 항목 누락: 보안", anchor=Anchor(None, None),
                suggestion="보안 섹션을 추가하세요"),
        Finding(checker="consistency", severity=Severity.MINOR,
                message="용어 불일치", anchor=Anchor(None, "2"), suggestion=None),
    ]


def test_review_payload_shape_matches_app_js():
    p = to_ui_review_payload(_review_findings(), "prd.md",
                             sections=9, chunks=12, chars=6180)
    assert p["doc"] == {"name": "prd.md", "type": "MD"}
    assert len(p["stages"]) == 5
    ids = [f["id"] for f in p["findings"]]
    assert ids == ["f1", "f2"] and len(set(ids)) == 2


def test_review_payload_carries_rescued_flag():
    # 재질의 끝에 근거를 찾은 지적(rescue)은 출처 표시를 payload 까지 나른다 —
    # 화면 뱃지("근거 재확인됨")와 이력 재열기가 이 값을 읽는다.
    fs = _review_findings()
    fs[1].rescued = True
    fs[1].rescue_trace = {"failed_quotes": ["고쳐 쓴 인용"], "searched": ["용어"]}
    p = to_ui_review_payload(fs, "d.md")
    assert [f["rescued"] for f in p["findings"]] == [False, True]
    # 여정(처음 인용·검색어)도 함께 — 화면이 "어떻게 다시 찾았나"를 그린다.
    assert p["findings"][0]["rescue_trace"] is None
    assert p["findings"][1]["rescue_trace"] == {
        "failed_quotes": ["고쳐 쓴 인용"], "searched": ["용어"]}


def test_review_payload_checkers_are_known_to_app_js():
    # app.js의 chk 맵과 checkerChips가 이 두 이름만 안다.
    p = to_ui_review_payload(_review_findings(), "d.md")
    assert {f["checker"] for f in p["findings"]} <= {"completeness", "consistency"}
    assert {f["sev"] for f in p["findings"]} <= {"critical", "major", "minor", "info"}


def test_review_finding_without_section_is_none_not_string():
    # app.js: f.section ? "§"+f.section : "doc"  → None이어야 "doc"으로 렌더된다.
    p = to_ui_review_payload(_review_findings(), "d.md")
    assert p["findings"][0]["section"] is None
    assert p["findings"][1]["section"] == "2"
    assert p["findings"][1]["suggestion"] == ""  # None이면 "null"이 찍힌다


def test_review_stages_carry_real_counts():
    p = to_ui_review_payload([], "d.md", sections=9, chunks=12, chars=6180)
    details = [s["detail"] for s in p["stages"]]
    assert "6,180 chars" in details and "9 sections" in details
    assert "12 chunks" in details and "0 findings" in details


def test_render_review_ui_js_restores_review_state_only():
    js = render_review_ui_js(to_ui_review_payload(_review_findings(), "prd.md"))
    for key in ("doc", "findings", "stages"):
        assert f"window.DOCREVIEW.{key} = r.{key};" in js
    assert "window.DOCREVIEW.criteriaResults = r.criteriaResults || null;" in js
    assert "window.DOCREVIEW.checklist = r.checklist || null;" in js
    # compare는 건드리지 않는다 (compare용 생성물과 공존해야 한다)
    assert "window.DOCREVIEW.compare" not in js
    assert "if (!window.DOCREVIEW) return;" in js


def test_render_review_ui_js_escapes_angle_bracket():
    f = Finding(checker="consistency", severity=Severity.INFO,
                message="</script><script>alert(1)</script>", anchor=Anchor(None, None))
    js = render_review_ui_js(to_ui_review_payload([f], "d.md"))
    assert "</script>" not in js


# --- 미리보기: 본문과 근거 -------------------------------------------------

def _doc_with_body():
    return Document(
        source_path="srs.md", doc_type=None,
        sections=[Section(id="3.2", title="성능", level=2,
                          text="응답시간은 3초 이내여야 한다.\n| 항목 | 값 |\n| 지연 | 5초 |",
                          anchor=Anchor(page=42, section="3.2"), children=[])])


def _evidence_finding():
    ev = Evidence(anchor=Anchor(page=42, section="3.2"), quote="응답시간은 3초 이내")
    return Finding(checker="consistency", severity=Severity.MINOR,
                   message="3초 vs 5초", anchor=Anchor(page=42, section="3.2"),
                   suggestion="대조하세요", evidence=[ev])


def test_review_payload_carries_document_body_for_preview():
    p = to_ui_review_payload([], "srs.md", document=_doc_with_body())
    assert len(p["sections"]) == 1
    s = p["sections"][0]
    assert s["id"] == "3.2" and s["title"] == "성능" and s["page"] == 42
    # 본문은 가공하지 않고 그대로 넘긴다 — 표 파이프 행이 살아 있어야 한다.
    assert "| 지연 | 5초 |" in s["text"]


def test_review_payload_without_document_has_empty_sections_not_crash():
    # 이 기능 이전의 이력이 그렇다. 화면은 "본문이 저장되지 않았습니다"를 띄운다.
    p = to_ui_review_payload(_review_findings(), "d.md")
    assert p["sections"] == []


def test_finding_carries_evidence_quotes_for_highlight():
    p = to_ui_review_payload([_evidence_finding()], "srs.md", document=_doc_with_body())
    f = p["findings"][0]
    assert f["page"] == 42
    assert [e["quote"] for e in f["evidence"]] == ["응답시간은 3초 이내"]
    assert f["evidence"][0]["section"] == "3.2"


def test_rule_findings_have_no_evidence_but_still_point_at_a_section():
    # 규칙 체커는 근거를 달지 않는다. 화면은 하이라이트 없이 절 스크롤만 한다 —
    # evidence 키 자체가 없으면 프론트가 undefined를 훑다 터진다.
    p = to_ui_review_payload(_review_findings(), "d.md")
    assert all(f["evidence"] == [] for f in p["findings"])
    assert p["findings"][1]["section"] == "2"


def test_evidence_quote_actually_occurs_in_its_section_text():
    """하이라이트의 전제. 이게 깨지면 화면은 근거를 영영 못 찾는다.

    verify_quotes가 공백 정규화 후 대조하므로, 프론트도 같은 규칙이어야 한다.
    """
    p = to_ui_review_payload([_evidence_finding()], "srs.md", document=_doc_with_body())
    body = {s["id"]: s["text"] for s in p["sections"]}
    for f in p["findings"]:
        for e in f["evidence"]:
            text = _norm(body[e["section"]])
            assert _norm(e["quote"]) in text


def _norm(text):
    return re.sub(r"\s+", " ", text).strip()


def test_render_review_ui_js_also_assigns_sections():
    js = render_review_ui_js(to_ui_review_payload([], "d.md", document=_doc_with_body()))
    assert "window.DOCREVIEW.sections = r.sections;" in js


def test_rolled_up_is_counted_and_not_called_missing():
    """부모 수준 검증은 누락이 아니다. 그러나 연결과도 구분해 세어야 한다 —
    세부 요건이 개별로 검증됐는지는 사람이 봐야 하기 때문이다."""
    parent = _doc([("1", "FR-CCG_01_01 세부")])
    child = _doc([("a", "FR-CCG_01 검증")])
    rows = build_rtm(parent, child, r"FR-[A-Z]{2,4}(?:_\d+)+", rollup_separator="_")
    stats = to_ui_payload(rows, [], "p", "c")["stats"]
    assert stats["missing"] == 0 and stats["extra"] == 0
    assert stats["rolled_up"] == 1


def test_checklist_review_payload_groups_by_item():
    from app.orchestrator import ChecklistReviewResult, ItemResult
    from modules.report import to_ui_checklist_review_payload
    from modules.shared import Anchor, Finding, Severity
    f = Finding(checker="consistency", severity=Severity.MINOR, message="흔들림",
                anchor=Anchor(None, "1"))
    res = ChecklistReviewResult(
        source_path="d.md",
        items=[ItemResult("1", "용어 일관성", "Consistency", "flagged", [f]),
               ItemResult("2", "서명 스캔", "", "manual", [])],
        findings=[f])
    p = to_ui_checklist_review_payload(res, "d.md")
    assert p["criteriaResults"] == p["checklist"]
    # na: 이 기준이 이 문서를 대상으로 하지 않는 항목. unreviewed(고쳐야 할 것)와
    # 갈라 센다 — 뭉치면 "검사 안 됨"이 부풀어 검토자가 장비·설정을 뒤진다.
    # na        — 이 기준이 이 문서를 대상으로 하지 않는다(고칠 것 없음).
    # outofscope — 애초에 문서 검토 항목이 아니다(생성 기능·이력 관리).
    # 둘 다 unreviewed(고쳐야 할 것)·manual(사람이 이 문서를 봐야 함)과 갈라 센다.
    assert p["checklist"]["summary"] == {"flagged": 1, "clean": 0,
                                         "unreviewed": 0, "na": 0,
                                         "outofscope": 0, "noanswer": 0,
                                         "manual": 1, "total": 2}
    items = p["checklist"]["items"]
    assert items[0]["no"] == "1" and items[0]["status"] == "flagged"
    assert len(items[0]["findings"]) == 1
    assert items[1]["status"] == "manual"
    # 평면 findings 도 있어 기존 단일 검토 렌더가 그대로 동작한다.
    assert len(p["findings"]) == 1


def test_criteria_payload_preserves_mapping_without_enabling_checklist_view():
    from app.orchestrator import CriteriaReviewResult, ItemResult
    from modules.report import to_ui_criteria_review_payload
    from modules.shared import Anchor, Finding, Severity

    finding = Finding(checker="placeholder", severity=Severity.MAJOR,
                      message="TBD", anchor=Anchor(None, "1"))
    result = CriteriaReviewResult(
        source_path="d.md",
        items=[ItemResult("C-1", "미작성 표시", "공통", "flagged", [finding])],
        findings=[finding])

    payload = to_ui_criteria_review_payload(result, "d.md")

    assert "checklist" not in payload
    assert payload["criteriaResults"]["items"][0]["findings"][0]["id"] == \
        payload["findings"][0]["id"]


def test_checklist_payload_carries_the_criterion_itself():
    """화면이 "이 기준이 뭐였는지"를 보여주려면 본문 밖의 것도 필요하다.

    지금은 no·text 만 실려, 검토자가 "공통3" 을 보고도 무엇을 확인하라는 건지,
    왜 사람 확인 필요인지 알 길이 없다 — 원본 엑셀은 사내 파일이라 앱에 없다.
    산출물 세트는 같은 문제를 "기준" 탭으로 풀었다(/api/teams/{team}/criteria).
    """
    from app.orchestrator import ChecklistReviewResult, ItemResult
    from modules.report import to_ui_checklist_review_payload

    res = ChecklistReviewResult(
        source_path="d.md",
        items=[ItemResult("C-1", "띄어쓰기·문법·오탈자를 검토한다.", "공통", "clean",
                          [], note="- SI 단위계는 수치와 단위를 띄운다", mode="LLM-조각"),
               ItemResult("3", "개정바를 아래 기준으로 표시했는가?", "공통", "manual",
                          [], note="- 개정바는 변경된 위치에 표시", mode="사람")])
    items = to_ui_checklist_review_payload(res, "d.md")["checklist"]["items"]

    # 확인 방법 — 본문이 "아래 기준으로"에서 끊겨 있어도 여기 실려 있다.
    assert items[0]["note"] == "- SI 단위계는 수치와 단위를 띄운다"
    assert "변경된 위치" in items[1]["note"]
    # 판정 방식 — "왜 사람 확인 필요인가"에 답한다.
    assert items[0]["mode"] == "LLM-조각"
    assert items[1]["mode"] == "사람"


def test_items_without_note_or_mode_still_load():
    # 업로드 체크리스트는 note·mode 가 없다. 키는 있되 빈 문자열이라야 화면이
    # undefined 를 그리지 않는다.
    from app.orchestrator import ChecklistReviewResult, ItemResult
    from modules.report import to_ui_checklist_review_payload

    res = ChecklistReviewResult(
        source_path="d.md",
        items=[ItemResult("1", "서명 스캔", "", "manual", [])])
    it = to_ui_checklist_review_payload(res, "d.md")["checklist"]["items"][0]

    assert it["note"] == "" and it["mode"] == ""
