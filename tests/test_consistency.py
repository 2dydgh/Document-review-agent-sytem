"""ChunkCriteriaChecker: 작업량 계획(plan)과 구조화된 진척(step).

작업 단위가 "청크"에서 "(청크 × 기준묶음)"으로 바뀌었다. 기준 하나를 청크마다
묻고, 기준이 많으면 묶음으로 나눠 여러 번 묻기 때문이다 — 화면 격자가 정직하려면
plan 이 실제 호출 수를 신고해야 한다.
"""
from modules.agent_quality import ChunkCriteriaChecker
from modules.llm_client import EchoLLM
from modules.preset import Criterion
from modules.shared import Anchor, Chunk, Context, ReviewConfig


def _chunks(n):
    return [Chunk(id=f"c{i}", text=f"조각 {i}", anchor=Anchor(page=None, section=f"s{i}"),
                  section_id=f"s{i}")
            for i in range(n)]


def _ctx(n_chunks):
    return Context(review=ReviewConfig(doc_type="generic"), llm=EchoLLM(),
                   chunks=_chunks(n_chunks))


def _crits(n):
    return [Criterion(no=str(i), text=f"기준 {i}", agent="표현·내용품질")
            for i in range(n)]


def test_plan_reports_chunk_total():
    ctx = _ctx(3)
    assert ChunkCriteriaChecker(criteria=_crits(1)).plan(doc=None, ctx=ctx) == {
        "kind": "chunk", "total": 3, "label": "표현 점검",
        "description": "문장·문단별 맞춤법, 모호성, 표현 오류", "scope": "3개 조각"}


def test_plan_multiplies_chunks_by_criterion_batches():
    # 기준 5개 = 묶음 2개(4+1). 청크 3개면 호출 6회다.
    ctx = _ctx(3)
    assert ChunkCriteriaChecker(criteria=_crits(5)).plan(doc=None, ctx=ctx) == {
        "kind": "chunk", "total": 6, "label": "표현 점검",
        "description": "문장·문단별 맞춤법, 모호성, 표현 오류", "scope": "3개 조각"}


def test_plan_reports_zero_when_no_chunks():
    ctx = _ctx(0)
    assert ChunkCriteriaChecker(criteria=_crits(1)).plan(doc=None, ctx=ctx) == {
        "kind": "chunk", "total": 0, "label": "표현 점검",
        "description": "문장·문단별 맞춤법, 모호성, 표현 오류", "scope": "0개 조각"}


def test_plan_is_none_without_criteria():
    # 기준이 없으면 이 검사기는 작업이 없다 — 격자에 빈 레인을 그리지 않는다.
    assert ChunkCriteriaChecker().plan(doc=None, ctx=_ctx(3)) is None


def test_progress_events_carry_a_structured_step():
    ctx = _ctx(2)
    events = []
    ctx.on_progress = events.append

    ChunkCriteriaChecker(criteria=_crits(1)).check(doc=None, ctx=ctx)

    steps = [e["step"] for e in events
             if e["key"] == "review" and e["status"] == "running"]
    assert steps == [
        {"kind": "chunk", "i": 1, "total": 2, "label": "표현 점검"},
        {"kind": "chunk", "i": 2, "total": 2, "label": "표현 점검"},
    ]
