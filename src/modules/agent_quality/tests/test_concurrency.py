"""표현 점검의 동시 호출.

청크끼리는 서로를 보지 않으므로 동시에 물어도 결과가 달라지지 않는다. vLLM 은
요청을 배치로 묶어 처리하도록 만들어져 하나씩 보내면 GPU 가 계속 대기한다 —
실측(27B, L40S x2): 순차 4건 145.0초(36.2초/건) · 동시 8건 33.3초(4.2초/건).

여기서 지키는 것은 속도가 아니라 **동시로 가도 깨지지 않는 성질**이다:
순서 · 카운터 · 진행 보고 · 실패 격리.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from modules.agent_quality import ChunkCriteriaChecker
from modules.shared import Anchor, Chunk, Context, Document, Section, Severity


@dataclass
class Response:
    """llm_client 의 Response 와 같은 모양. 그 모듈을 import 하지 않는다 —
    체커는 ctx.llm 을 덕타이핑으로만 쓰므로 테스트도 그래야 모듈이 홀로 돈다."""
    text: str
    error: str | None = None


@dataclass
class _Review:
    required_sections: list = field(default_factory=list)
    placeholder_markers: list = field(default_factory=list)
    id_pattern: str = ""


def _doc(lines: list[str]) -> Document:
    text = "\n".join(lines)
    return Document(source_path="x.md", doc_type="generic",
                    sections=[Section(id="1", title="개요", level=1, text=text,
                                      anchor=Anchor(None, "1"))])


def _chunks(n: int, text: str) -> list[Chunk]:
    return [Chunk(id=f"1#{i}", text=text, anchor=Anchor(None, "1"), section_id="1")
            for i in range(n)]


class _LLM:
    """청크 순서대로 정해진 답을 준다. 동시 호출 수를 기록한다."""

    def __init__(self, answers: list[str], delay: float = 0.0):
        self.answers = answers
        self.delay = delay
        self.calls = 0
        self.peak = 0
        self._live = 0
        self._lock = threading.Lock()

    def complete(self, prompt: str, **opts) -> Response:
        with self._lock:
            self._live += 1
            self.peak = max(self.peak, self._live)
            i = self.calls
            self.calls += 1
        try:
            if self.delay:
                time.sleep(self.delay)
            return Response(text=self.answers[i % len(self.answers)])
        finally:
            with self._lock:
                self._live -= 1

    def chat(self, messages, **opts) -> Response:
        raise AssertionError("표현 점검은 complete() 를 쓴다")


@dataclass
class _Crit:
    """체커가 기준에서 읽는 것은 no·text 뿐이다."""
    no: str
    text: str


# 기준 하나짜리 묶음 — 이 파일이 지키는 것은 동시성이지 기준 라우팅이 아니다.
_C = [_Crit(no="1", text="표현이 흔들리는가")]

_OK = ('{"results": [{"no": "1", "verdict": "위반", "issue": "표현이 흔들린다",'
       ' "quotes": ["해안선 변화 예측"]}]}')
_NONE = '{"results": [{"no": "1", "verdict": "통과"}]}'


def test_calls_run_concurrently():
    """설정한 만큼 동시에 물어야 GPU 가 대기하지 않는다."""
    doc = _doc(["해안선 변화 예측"])
    llm = _LLM([_NONE], delay=0.05)
    ctx = Context(review=_Review(), llm=llm, chunks=_chunks(8, "본문"),
                  llm_concurrency=4)

    ChunkCriteriaChecker(criteria=_C).check(doc, ctx)

    assert llm.calls == 8
    assert llm.peak > 1, "동시에 안 돌았다 — 순차면 GPU 가 계속 대기한다"
    assert llm.peak <= 4, f"설정보다 많이 띄웠다: {llm.peak}"


def test_default_is_sequential():
    """Context 를 직접 만드는 쪽이 아무 설정도 안 했으면 옛 동작 그대로다."""
    llm = _LLM([_NONE], delay=0.02)
    ctx = Context(review=_Review(), llm=llm, chunks=_chunks(4, "본문"))

    ChunkCriteriaChecker(criteria=_C).check(_doc(["x"]), ctx)

    assert llm.peak == 1


def test_finding_order_follows_chunk_order():
    """실행마다 순서가 흔들리면 리포트 번호가 달라지고 형광펜 짝도 어긋난다."""
    doc = _doc(["첫째 근거 문장", "둘째 근거 문장", "셋째 근거 문장"])
    answers = ['{"results": [{"no": "1", "verdict": "위반", "issue": "A",'
               ' "quotes": ["첫째 근거 문장"]}]}',
               '{"results": [{"no": "1", "verdict": "위반", "issue": "B",'
               ' "quotes": ["둘째 근거 문장"]}]}',
               '{"results": [{"no": "1", "verdict": "위반", "issue": "C",'
               ' "quotes": ["셋째 근거 문장"]}]}']
    # 뒤 청크가 먼저 끝나도 순서가 유지되는지 보려면 지연을 거꾸로 줘야 하는데,
    # 같은 지연이라도 완료 순서는 OS 가 정한다 — 여러 번 돌려 흔들리지 않음을 본다.
    for _ in range(5):
        llm = _LLM(answers, delay=0.01)
        ctx = Context(review=_Review(), llm=llm, chunks=_chunks(3, "본문"),
                      llm_concurrency=3)

        got = [f.message for f in ChunkCriteriaChecker(criteria=_C).check(doc, ctx)
               if f.severity == Severity.MINOR]

        assert got == ["A", "B", "C"], f"순서가 흔들렸다: {got}"


def test_progress_counts_completions_not_positions():
    """동시에 돌면 완료 순서가 뒤섞인다 — 누적 개수로 세야 격자가 맞는다."""
    events = []
    llm = _LLM([_NONE], delay=0.01)
    ctx = Context(review=_Review(), llm=llm, chunks=_chunks(6, "본문"),
                  on_progress=events.append, llm_concurrency=3)

    ChunkCriteriaChecker(criteria=_C).check(_doc(["x"]), ctx)

    seen = [e["step"]["i"] for e in events if e.get("step", {}).get("kind") == "chunk"]
    assert sorted(seen) == [1, 2, 3, 4, 5, 6], f"누적 개수가 아니다: {seen}"
    assert all(e["step"]["total"] == 6 for e in events if e.get("step"))


def test_counters_are_not_lost_under_concurrency():
    """unanswered·dropped 를 스레드에서 세도 하나도 빠지지 않아야 한다.

    빠지면 "검사 안 됨"이 조용한 0건으로 되돌아간다.
    """
    doc = _doc(["문서에 없는 근거는 버려진다"])
    # 빈 응답(unanswered) 과 문서에 없는 인용(dropped) 을 번갈아 준다.
    answers = ["", '{"results": [{"no": "1", "verdict": "위반", "issue": "X",'
               ' "quotes": ["문서에 결코 없는 문장"]}]}']
    llm = _LLM(answers, delay=0.01)
    ctx = Context(review=_Review(), llm=llm, chunks=_chunks(8, "본문"),
                  llm_concurrency=4)

    infos = [f.message for f in ChunkCriteriaChecker(criteria=_C).check(doc, ctx)
             if f.severity == Severity.INFO]

    assert any("4/8" in m for m in infos), f"unanswered 를 놓쳤다: {infos}"
    assert any("4건" in m for m in infos), f"dropped 를 놓쳤다: {infos}"


def test_no_chunks_calls_nothing():
    llm = _LLM([_NONE])
    ctx = Context(review=_Review(), llm=llm, chunks=[], llm_concurrency=8)

    assert ChunkCriteriaChecker(criteria=_C).check(_doc(["x"]), ctx) == []
    assert llm.calls == 0
