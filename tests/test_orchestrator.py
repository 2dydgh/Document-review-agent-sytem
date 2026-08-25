from app.orchestrator import ReviewResult, review_document
from app.registry import default_checkers
from modules.shared import Config, ReviewConfig


def _cfg(required):
    return Config(llm_provider="echo", chunk_max_chars=4000,
                  review=ReviewConfig("generic", required))


def _common():
    """공통 기준(오탈자·문법). 서버가 review_document 에 넘기는 것과 같은 모양.

    안 넘기면 표현 점검(LLM)이 돌지 않는다 — 기준 없는 지적은 어느 기준에도
    붙일 수 없기 때문이다. 엔진에 기준을 박지 않고 주입받는 설계라 테스트도
    호출부처럼 넘긴다.
    """
    from modules.preset import Criterion
    return [
        # 규칙 — 기준이 자기를 검사할 규칙 이름을 댄다(common.yaml 9번과 같다).
        Criterion(no="9", text="문서 구조·양식·필수 구성", agent="형식·완전성",
                  check="required_sections"),
        Criterion(no="12", text="미작성 표시 잔존", agent="형식·완전성",
                  check="placeholder"),
        # LLM-조각 — 오탈자·맞춤법.
        Criterion(no="16", text="띄어쓰기·문법·오탈자", agent="표현·내용품질"),
    ]


def test_review_document_flags_missing_section(tmp_path):
    p = tmp_path / "d.md"
    p.write_text("# 개요\n내용", encoding="utf-8")
    result = review_document(p, _cfg(["개요", "요구사항"]), criteria=_common())
    assert isinstance(result, ReviewResult)
    assert result.source_path == str(p)
    msgs = [f.message for f in result.findings]
    assert any("요구사항" in m for m in msgs)


def test_review_document_clean_when_all_present(tmp_path):
    p = tmp_path / "d.md"
    p.write_text("# 개요\n내용\n# 요구사항\n항목", encoding="utf-8")
    result = review_document(p, _cfg(["개요", "요구사항"]), criteria=_common())
    # completeness 는 통과한다. consistency 는 EchoLLM 이라 판정을 못 내므로
    # "검사 못 함" 보고 한 건만 남는다 — 지적은 아니다(0건과 구분해야 한다).
    assert [f for f in result.findings if not f.unreviewed] == []
    assert len([f for f in result.findings if f.unreviewed]) == 1


def _cfg_trace():
    return Config(llm_provider="echo", chunk_max_chars=4000,
                  review=ReviewConfig("generic", [], id_pattern=r"SR-\d+"))


def test_review_documents_flags_missing_and_orphan(tmp_path):
    from app.orchestrator import review_documents
    parent = tmp_path / "srs.md"
    parent.write_text("# 개요\nSR-001 로그인\nSR-002 로그아웃", encoding="utf-8")
    child = tmp_path / "sdd.md"
    child.write_text("# 설계\nSR-002 구현\nSR-003 캐시", encoding="utf-8")
    result = review_documents(parent, child, _cfg_trace())
    msgs = [f.message for f in result.findings]
    assert any("SR-001" in m for m in msgs)   # 하위 누락
    assert any("SR-003" in m for m in msgs)   # 상위 근거없음
    assert not any("SR-002" in m for m in msgs)  # 매칭 → 지적 없음
    assert "↔" in result.source_path


def test_review_documents_clean_when_all_traced(tmp_path):
    from app.orchestrator import review_documents
    parent = tmp_path / "srs.md"
    parent.write_text("# 개요\nSR-001", encoding="utf-8")
    child = tmp_path / "sdd.md"
    child.write_text("# 설계\nSR-001 구현", encoding="utf-8")
    assert review_documents(parent, child, _cfg_trace()).findings == []


def test_review_document_reports_stage_progress(tmp_path):
    p = tmp_path / "d.md"
    p.write_text("# 개요\n내용\n# 요구사항\n항목", encoding="utf-8")
    events = []
    review_document(p, _cfg(["개요", "요구사항"]), on_progress=events.append,
                    criteria=_common())

    # 단계는 파이프라인 순서대로 완료된다.
    done = [e["key"] for e in events if e["status"] == "done"]
    assert done == ["ingestion", "normalize", "chunking", "review", "report"]

    # 숫자는 서버가 실제로 센 값이다. 지적은 0건이지만 EchoLLM 이라 표현 점검이
    # "검사 못 함"을 한 건 올린다 — 위 test_review_document_clean_when_all_present
    # 와 같은 문서다.
    detail = {e["key"]: e["detail"] for e in events if e["status"] == "done"}
    assert detail["report"] == "1 findings"
    assert detail["ingestion"].endswith(" chars")
    assert detail["normalize"].endswith(" sections")
    assert detail["chunking"].endswith(" chunks")


def test_review_document_without_callback_still_works(tmp_path):
    p = tmp_path / "d.md"
    p.write_text("# 개요\n내용", encoding="utf-8")
    result = review_document(p, _cfg(["개요"]))   # CLI가 이렇게 부른다
    assert result.section_count >= 1


def test_no_criteria_says_it_did_not_review(tmp_path):
    """기준 없이 부르면 "이상 없음"이 아니라 "안 쟀음"이라고 말한다.

    presets/criteria/ 가 없는 배포에서 cli._common_criteria 가 [] 를 준다. 그
    빈 목록이 그대로 흘러 지적 0건짜리 리포트가 나오면 검토를 통과한 것으로 읽힌다.
    """
    p = tmp_path / "d.md"
    p.write_text("# 개요\n내용", encoding="utf-8")
    result = review_document(p, _cfg(["개요"]))
    assert [f for f in result.findings if not f.unreviewed] == []
    assert any(f.unreviewed and "검토 기준이 없어" in f.message
               for f in result.findings)


def test_review_stage_reports_each_checker(tmp_path):
    p = tmp_path / "d.md"
    p.write_text("# 개요\n내용", encoding="utf-8")
    events = []
    review_document(p, _cfg(["개요"]), on_progress=events.append, criteria=_common())

    running = [e["detail"] for e in events
               if e["key"] == "review" and e["status"] == "running"]
    # 체커마다 자신이 지금 뭘 검사하는지 알리는 시작 문구를 정확히 한 번씩 낸다.
    # 문구가 서로 겹치면(이름 충돌) 몇 개 체커가 실제로 돌았는지 화면에서
    # 구분이 안 된다 — 그러니 체커 수만큼 서로 다른 문구가 나와야 한다.
    start_labels = [f"{c.label} 중" if getattr(c, "label", None) else f"{c.name} 검사 중"
                    for c in default_checkers()]
    assert len(set(start_labels)) == len(start_labels)
    for label in start_labels:
        assert running.count(label) == 1


def test_review_stage_labels_distinguish_same_named_checkers(tmp_path):
    # CompletenessChecker/PlaceholderChecker는 둘 다 name="completeness"다.
    # 라벨이 없으면 진행 문구가 겹쳐서 어느 체커가 도는지 구분이 안 된다.
    # 여기서는 실제 문구를 리터럴로 박아 둔다 — 라벨 조립 방식이 조용히
    # 되돌아가 다시 겹치는 회귀를 문구 자체로도 잡기 위함이다.
    p = tmp_path / "d.md"
    p.write_text("# 개요\n내용", encoding="utf-8")
    events = []
    review_document(p, _cfg(["개요"]), on_progress=events.append, criteria=_common())

    running = [e["detail"] for e in events
               if e["key"] == "review" and e["status"] == "running"]
    # label은 명사("표현 점검")이고 진행 문구는 orchestrator가 "중"을 붙여 만든다.
    # 화면은 같은 label을 레인 이름으로도 쓴다 — 문구 출처가 하나다.
    assert running.count("필수 항목 확인 중") == 1      # CompletenessChecker
    assert running.count("미작성 표시 검사 중") == 1     # PlaceholderChecker
    assert running.count("표현 점검 중") == 1           # ChunkCriteriaChecker


def test_review_marks_the_active_lane_before_its_first_completed_unit(tmp_path):
    """LLM 첫 응답 전에도 화면은 해당 레인을 대기가 아니라 실행 중으로 그린다."""
    p = tmp_path / "d.md"
    p.write_text("# 개요\n내용", encoding="utf-8")
    events = []
    review_document(p, _cfg(["개요"]), on_progress=events.append, criteria=_common())

    starts = [e for e in events if e.get("detail") == "표현 점검 중"]
    assert len(starts) == 1
    assert starts[0]["active"] == "표현 점검"


def test_rules_only_review_does_not_plan_or_run_llm_lanes(tmp_path):
    p = tmp_path / "d.md"
    p.write_text("# 개요\n내용", encoding="utf-8")
    cfg = _cfg(["개요"])
    cfg.llm_enabled = False
    events = []

    result = review_document(p, cfg, on_progress=events.append, criteria=_common())

    first = next(e for e in events if e.get("plan"))
    assert [lane["label"] for lane in first["plan"]] == ["규칙 검사"]
    assert not any(f.checker in {"consistency", "consistency_doc"}
                   for f in result.findings)


def test_review_reports_a_plan_event_before_running_checkers(tmp_path):
    """화면이 '작업 모자이크'를 그리려면 체커 루프가 시작되기 전에 각 체커의

    작업량(총 청크·총 그룹)을 한 번에 알아야 한다 — 안 그러면 청크를 다
    끝낸 뒤에야 그룹이 나타나며 퍼센트가 역주행한다.
    """
    p = tmp_path / "d.md"
    p.write_text("# 개요\n내용\n# 요구사항\n항목", encoding="utf-8")
    events = []
    result = review_document(p, _cfg(["개요", "요구사항"]), on_progress=events.append,
                             criteria=_common())

    running = [e for e in events if e["key"] == "review" and e["status"] == "running"]
    assert running, "review 단계의 running 이벤트가 없다"
    assert "plan" in running[0], "plan은 체커 루프보다 먼저(첫 running 이벤트에) 나와야 한다"
    assert running[0]["plan"] == [
        {"kind": "rule", "total": 2, "label": "규칙 검사",
         "description": "필수 항목·서식·목록을 자동 규칙으로 확인", "scope": "2개 검사"},
        {"kind": "chunk", "total": result.chunk_count, "label": "표현 점검",
         "description": "문장·문단별 맞춤법, 모호성, 표현 오류",
         "scope": f"{result.chunk_count}개 조각"}]
    assert all(item["kind"] != "group" for item in running[0]["plan"])
    # 한 번만 신고한다 — 나머지 running 이벤트에는 plan이 없다.
    assert all("plan" not in e for e in running[1:])


def test_review_documents_passes_rollup_separator_to_rtm(tmp_path):
    """체크리스트가 켠 롤업이 RTM까지 닿아야 한다. 여기서 끊기면 설정이
    있으나 마나이고, 실측(SHN34)에서 오탐 46건이 그대로 남는다."""
    from app.orchestrator import review_documents
    cfg = Config(llm_provider="echo", chunk_max_chars=4000,
                 review=ReviewConfig("generic", [],
                                     id_pattern=r"FR-[A-Z]{2,4}(?:_\d+)+",
                                     id_rollup_separator="_"))
    parent = tmp_path / "srs.md"
    parent.write_text("# 상위\nFR-CCG_01_01 세부", encoding="utf-8")
    child = tmp_path / "rvvr.md"
    child.write_text("# 하위\nFR-CCG_01 검증", encoding="utf-8")
    result = review_documents(parent, child, cfg)
    assert [r.status for r in result.rtm] == ["rolled_up"]
    assert result.findings == []


def test_rule_checkers_run_before_llm_lanes_even_when_added_last(tmp_path):
    """extra_checkers(기준 구조 절 검사기)는 목록 맨 뒤에 붙는다. 그대로 돌리면
    규칙 검사 레인이 중간에 '대기'로 멈췄다가 맨 끝에 완료되는 것처럼 보인다 —
    화면은 규칙 검사를 한 레인으로 묶어 그리므로 실행도 한 덩어리로 먼저 온다.
    """
    class _ExtraRule:
        name = "field"

        def check(self, doc, ctx):
            return []

    p = tmp_path / "d.md"
    p.write_text("# 개요\n내용", encoding="utf-8")
    events = []
    review_document(p, _cfg(["개요"]), on_progress=events.append,
                    criteria=_common(), extra_checkers=[_ExtraRule()])

    rule_steps = [i for i, e in enumerate(events)
                  if (e.get("step") or {}).get("kind") == "rule"]
    llm_start = [i for i, e in enumerate(events) if e.get("detail") == "표현 점검 중"]
    assert rule_steps and llm_start
    assert max(rule_steps) < min(llm_start), "규칙 검사가 LLM 레인 뒤에 남았다"
