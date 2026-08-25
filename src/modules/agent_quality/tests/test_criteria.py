"""기준이 검사를 이끈다 — 기준 본문이 프롬프트에 실리고 기준별로 판정이 나온다.

예전에는 프롬프트가 코드에 박혀 있어, 어떤 체크리스트를 올리든 LLM 에게 묻는 말이
항상 같았다("모호하거나 상호 모순되는 표현을 찾아라"). 그 결과 지적 목록 하나가
모든 기준에 똑같이 복사돼 화면이 사실과 달랐다.

이 파일은 모듈을 홀로 돌린다 — preset 을 import 하지 않고 기준도 여기서 만든다
(test_concurrency.py 가 ctx.llm 에 대해 쓰는 것과 같은 규약). 체커는 기준을
no·text 속성으로만 읽으므로 그 두 개를 가진 것이면 무엇이든 된다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from modules.agent_quality import ChunkCriteriaChecker
from modules.shared import Anchor, Chunk, Context, Document, Section, Severity


@dataclass
class Response:
    text: str
    error: str | None = None


@dataclass
class _Review:
    required_sections: list = field(default_factory=list)
    placeholder_markers: list = field(default_factory=list)
    id_pattern: str = ""


@dataclass
class _Crit:
    """체커가 기준에서 읽는 것은 no·text 뿐이다."""
    no: str
    text: str


def _doc(lines: list[str]) -> Document:
    return Document(source_path="x.md", doc_type="generic",
                    sections=[Section(id="1", title="개요", level=1,
                                      text="\n".join(lines),
                                      anchor=Anchor(None, "1"))])


def _chunks(n: int, text: str = "본문") -> list[Chunk]:
    return [Chunk(id=f"1#{i}", text=text, anchor=Anchor(None, "1"), section_id="1")
            for i in range(n)]


class _LLM:
    """받은 프롬프트를 남기고 정해둔 답을 돌려준다."""

    def __init__(self, answers: list[str] | str = "", error: str | None = None):
        self.answers = [answers] if isinstance(answers, str) else answers
        self.error = error
        self.prompts: list[str] = []

    def complete(self, prompt: str, **opts) -> Response:
        i = len(self.prompts)
        self.prompts.append(prompt)
        if self.error:
            return Response(text="", error=self.error)
        return Response(text=self.answers[i % len(self.answers)])

    def chat(self, messages, **opts) -> Response:
        raise AssertionError("표현 점검은 complete() 를 쓴다")


def _ctx(llm, chunks=1, text="본문"):
    return Context(review=_Review(), llm=llm, chunks=_chunks(chunks, text))


# ── 기준이 프롬프트에 들어간다 ────────────────────────────────────────────

def test_criterion_text_reaches_the_prompt():
    # 기준 본문이 프롬프트에 안 들어가면 모델은 그 기준으로 판단할 수 없다.
    llm = _LLM('{"results": [{"no": "15", "verdict": "통과"}]}')
    crit = _Crit(no="15", text="띄어쓰기·문법·오탈자 검토")

    ChunkCriteriaChecker(criteria=[crit]).check(_doc(["x"]), _ctx(llm))

    assert llm.prompts, "LLM 을 한 번도 부르지 않았다"
    assert "띄어쓰기·문법·오탈자 검토" in llm.prompts[0]
    assert "15" in llm.prompts[0]


def test_prompt_does_not_ask_for_suggestion():
    # 수정안은 온디맨드(/api/suggest)다. 검사 응답에 섞으면 판정이 흐려진다.
    llm = _LLM('{"results": []}')

    ChunkCriteriaChecker(criteria=[_Crit("15", "오탈자 검토")]).check(
        _doc(["x"]), _ctx(llm))

    assert "suggestion" not in llm.prompts[0]


def test_no_criteria_calls_nothing():
    # 기준 없이 만들면 검사할 것이 없다. 예전처럼 일반 프롬프트로 훑지 않는다 —
    # 기준 없는 지적은 어느 기준에도 붙일 수 없다.
    llm = _LLM('{"results": []}')

    assert ChunkCriteriaChecker().check(_doc(["x"]), _ctx(llm)) == []
    assert llm.prompts == []


# ── 판정이 기준별로 남는다 ────────────────────────────────────────────────

def test_pass_verdict_is_recorded_not_silence():
    # "지적 0건"과 "그 기준으로 봤더니 통과"는 다른 말이다.
    llm = _LLM('{"results": [{"no": "15", "verdict": "통과"}]}')
    ck = ChunkCriteriaChecker(criteria=[_Crit("15", "오탈자 검토")])

    ck.check(_doc(["x"]), _ctx(llm))

    assert ck.verdicts["15"] == "통과"


def test_finding_carries_the_criterion_it_came_from():
    # 한 검사기가 기준 여럿을 보므로, 검사기 이름만으로는 지적을 되짚을 수 없다.
    # 되짚는 자리는 Finding.rule_id 다 — "어느 기준 항목이 이 지적을 냈나"로
    # 이미 쓰이고 있다(W-의뢰번호·F-성적서번호). 같은 축에 필드를 둘로 늘리지 않는다.
    llm = _LLM('{"results": [{"no": "20", "verdict": "위반", '
               '"issue": "모호하다", "quotes": ["적절히 조치한다"]}]}')
    ck = ChunkCriteriaChecker(criteria=[_Crit("15", "오탈자"), _Crit("20", "모호 표현")])

    findings = ck.check(_doc(["적절히 조치한다"]), _ctx(llm))

    flagged = [f for f in findings if f.severity == Severity.MINOR]
    assert [f.rule_id for f in flagged] == ["20"]
    assert ck.verdicts["20"] == "위반"
    # 답이 안 온 기준은 통과가 아니다 — 안 본 것이다.
    assert ck.verdicts["15"] == "미판정"


def test_violation_in_any_chunk_wins_over_pass_in_another():
    # 청크마다 판정이 나온다. 마지막 값으로 덮으면 앞선 위반이 지워진다.
    llm = _LLM(['{"results": [{"no": "15", "verdict": "위반", "issue": "오타",'
                ' "quotes": ["오타가 잇다"]}]}',
                '{"results": [{"no": "15", "verdict": "통과"}]}'])
    ck = ChunkCriteriaChecker(criteria=[_Crit("15", "오탈자")])

    ck.check(_doc(["오타가 잇다"]), _ctx(llm, chunks=2))

    assert ck.verdicts["15"] == "위반"


def test_invented_criterion_number_is_dropped():
    # 모델이 기준 번호를 지어내면 그 판정은 어디에도 붙일 수 없다.
    llm = _LLM('{"results": [{"no": "999", "verdict": "위반", "issue": "x",'
               ' "quotes": ["본문"]}]}')
    ck = ChunkCriteriaChecker(criteria=[_Crit("15", "오탈자")])

    findings = ck.check(_doc([_TEXT]), _ctx(llm, text=_TEXT))

    assert "999" not in ck.verdicts
    assert [f for f in findings if f.severity == Severity.MINOR] == []


# ── 실패는 통과로 새지 않는다 (가장 중요) ──────────────────────────────────

def test_llm_failure_marks_unreviewed_never_pass():
    # 연결이 끊겼는데 '통과'가 되면 검토 도구가 거짓말을 한다.
    llm = _LLM(error="Connection refused")
    ck = ChunkCriteriaChecker(criteria=[_Crit("15", "오탈자 검토")])

    findings = ck.check(_doc(["x"]), _ctx(llm))

    assert ck.verdicts["15"] == "미판정"
    assert all(v != "통과" for v in ck.verdicts.values())
    assert any(f.unreviewed for f in findings)
    assert any("Connection refused" in f.message for f in findings)


def test_quotes_that_are_not_in_the_document_are_dropped():
    # 근거를 못 댄 지적은 올리지 않되, 버렸다는 사실은 드러낸다.
    llm = _LLM('{"results": [{"no": "15", "verdict": "위반", "issue": "x",'
               ' "quotes": ["문서에 결코 없는 문장"]}]}')
    ck = ChunkCriteriaChecker(criteria=[_Crit("15", "오탈자")])

    findings = ck.check(_doc(["실제 본문"]), _ctx(llm))

    assert [f for f in findings if f.severity == Severity.MINOR] == []
    assert any(f.severity == Severity.INFO and "원문 대조" in f.message
               for f in findings)
    # 근거가 없어 버린 것은 통과가 아니다.
    assert ck.verdicts["15"] != "통과"


# ── 한 번에 너무 많이 묻지 않는다 ─────────────────────────────────────────

def test_criteria_are_asked_in_small_batches():
    """실측: 규칙 7개를 한꺼번에 주면 하나를 조용히 빠뜨렸고(3/4), 좁혀 물으니
    네 번 다 잡았다(4/4). 통과 판정을 믿으려면 묶음이 작아야 한다."""
    llm = _LLM('{"results": []}')
    crits = [_Crit(str(i), f"기준 {i}") for i in range(9)]

    ChunkCriteriaChecker(criteria=crits).check(_doc(["x"]), _ctx(llm))

    # 청크 1개 × 묶음 3개(4+4+1) = 3회
    assert len(llm.prompts) == 3
    for p in llm.prompts:
        assert p.count("No.") <= 4, "한 프롬프트에 기준을 너무 많이 실었다"


def test_plan_counts_chunks_times_batches():
    # 진행 화면 퍼센트가 정직하려면 실제 호출 수를 신고해야 한다.
    llm = _LLM('{"results": []}')
    crits = [_Crit(str(i), f"기준 {i}") for i in range(5)]   # 묶음 2개
    ck = ChunkCriteriaChecker(criteria=crits)

    assert ck.plan(doc=None, ctx=_ctx(llm, chunks=3)) == {
        "kind": "chunk", "total": 6, "label": "표현 점검",
        "description": "문장·문단별 맞춤법, 모호성, 표현 오류", "scope": "3개 조각"}


def test_plan_is_none_without_criteria():
    assert ChunkCriteriaChecker().plan(doc=None, ctx=_ctx(_LLM())) is None


# ── LLM-문서: 문서를 통째로 넣고 묻는다 ────────────────────────────────────
# 조각으로 자르면 멀리 떨어진 두 곳을 못 맞댄다 — 3쪽 표 제목과 40쪽 본문 참조,
# 앞쪽 약어 목록과 뒤쪽 사용처. 실측(2026-07-30, Qwen3.6-27B)에서 기준 1개 ×
# 문서 통째가 4/4 로 가장 정확했다(조각 방식의 7개 묶음은 3/4).

def test_whole_doc_sends_the_document_not_chunks():
    from modules.agent_quality import WholeDocCriteriaChecker

    llm = _LLM('{"results": [{"no": "13", "verdict": "통과"}]}')
    doc = _doc(["3쪽: 표 2. 시험 환경", "40쪽: 시험 환경은 표 2 참조"])
    ck = WholeDocCriteriaChecker(criteria=[_Crit("13", "표·그림 정합성")])

    ck.check(doc, _ctx(llm, chunks=5))   # 청크가 5개여도

    assert len(llm.prompts) == 1, "문서는 한 번만 물어야 한다"
    # 멀리 떨어진 두 곳이 같은 프롬프트에 들어간다 — 조각으로는 불가능하다.
    assert "표 2. 시험 환경" in llm.prompts[0]
    assert "표 2 참조" in llm.prompts[0]


def test_whole_doc_falls_back_to_chunks_and_says_so():
    """문서가 창을 넘으면 조각으로 내려가되 **조용히 하지 않는다.**

    전체를 봐야 하는 기준을 조각으로 훑고 "이상 없음"이라 하면 거짓말이 된다.
    """
    from modules.agent_quality import WholeDocCriteriaChecker

    llm = _LLM('{"results": [{"no": "13", "verdict": "통과"}]}')
    doc = _doc(["가" * 500])
    ck = WholeDocCriteriaChecker(criteria=[_Crit("13", "표·그림 정합성")], max_chars=100)

    findings = ck.check(doc, _ctx(llm, chunks=3))

    assert len(llm.prompts) == 3, "창을 넘으면 조각으로 내려간다"
    notice = [f for f in findings if f.severity == Severity.INFO]
    assert notice, "폴백을 알리지 않으면 '전체를 봤다'가 거짓이 된다"
    assert any("문서가 커서" in f.message for f in notice)
    # 부분만 본 기준을 '통과'로 확정하지 않는다.
    assert ck.verdicts["13"] != "통과"


def test_whole_doc_keeps_the_verdict_when_it_fits():
    from modules.agent_quality import WholeDocCriteriaChecker

    llm = _LLM('{"results": [{"no": "13", "verdict": "통과"}]}')
    ck = WholeDocCriteriaChecker(criteria=[_Crit("13", "표·그림")], max_chars=100_000)

    ck.check(_doc(["짧은 문서"]), _ctx(llm, chunks=2))

    assert ck.verdicts["13"] == "통과"


def test_whole_doc_has_its_own_label_and_type():
    """orchestrator 가 type 으로 검사기를 모은다 — 조각과 같은 타입이면 덮인다."""
    from modules.agent_quality import ChunkCriteriaChecker, WholeDocCriteriaChecker

    assert WholeDocCriteriaChecker is not ChunkCriteriaChecker
    assert WholeDocCriteriaChecker(criteria=[_Crit("1", "x")]).label != ChunkCriteriaChecker(
        criteria=[_Crit("1", "x")]).label


def test_old_checker_names_remain_compatibility_aliases():
    """공개 이름 변경이 기존 모듈 사용자를 즉시 깨뜨리지는 않는다."""
    from modules.agent_quality import (
        ConsistencyChecker,
        WholeDocChecker,
        WholeDocCriteriaChecker,
    )

    assert ConsistencyChecker is ChunkCriteriaChecker
    assert WholeDocChecker is WholeDocCriteriaChecker


def test_whole_doc_plan_matches_the_calls_it_makes():
    """작업량 신고가 실제 호출 수와 다르면 진행바가 중간에서 멈춘다.

    청크 수로 신고하고 문서를 통째로 1회만 부르면 절반에서 멈춘 채로 끝난다.
    """
    from modules.agent_quality import WholeDocCriteriaChecker

    llm = _LLM('{"results": [{"no": "13", "verdict": "통과"}]}')
    ck = WholeDocCriteriaChecker(criteria=[_Crit("13", "표·그림")], max_chars=100_000)
    ctx = _ctx(llm, chunks=5)
    doc = _doc(["짧은 문서"])

    plan = ck.plan(doc, ctx)
    planned = plan["total"]
    ck.check(doc, ctx)

    assert planned == len(llm.prompts) == 1
    assert plan["scope"] == "문서 전체 입력"
    assert plan["limited"] is False


def test_whole_doc_progress_advances_per_criterion():
    """문서 전체 기준 셋이 한 호출로 뭉쳐 0→100%로만 뛰지 않아야 한다."""
    from modules.agent_quality import WholeDocCriteriaChecker

    crits = [_Crit("13", "표·그림"), _Crit("15", "용어·약어"),
             _Crit("32", "동일 ID")]
    answers = [f'{{"results": [{{"no": "{c.no}", "verdict": "통과"}}]}}'
               for c in crits]
    ctx = _ctx(_LLM(answers), chunks=5)
    events = []
    ctx.on_progress = events.append
    ck = WholeDocCriteriaChecker(criteria=crits, max_chars=100_000)
    doc = _doc(["짧은 문서"])

    assert ck.plan(doc, ctx)["total"] == 3
    ck.check(doc, ctx)

    steps = [e["step"] for e in events if "step" in e]
    assert [s["i"] for s in steps] == [1, 2, 3]
    assert all(s["total"] == 3 and s["label"] == "문서 전체 점검" for s in steps)
    assert len(ctx.llm.prompts) == 3


def test_whole_doc_plan_exposes_split_limit():
    from modules.agent_quality import WholeDocCriteriaChecker

    ck = WholeDocCriteriaChecker(criteria=[_Crit("13", "표·그림")], max_chars=3)
    plan = ck.plan(_doc(["긴 문서 본문"]), _ctx(_LLM(), chunks=2))

    assert plan["scope"] == "분할 검사 · 전체 비교 제한"
    assert plan["limited"] is True


# ── 지적 종류가 등급을 가른다 ──────────────────────────────────────────────
# 이 체커 하나가 전체 지적의 90%대를 낸다. 전부 같은 등급으로 내면 그 등급이 곧
# 전부가 되어 "무엇부터 볼 것인가" 를 못 가른다. 실측(기록 974개 표본): 모순·
# 불일치 40% · 표기 20% · 모호 19%. 오타와 요구사항 모순이 같은 칸에 있었다.

_TEXT = "요구사항 4.2 와 4.7 이 서로 다른 값을 말한다"


def _violation(kind_json: str) -> str:
    # 인용은 4자 이상이어야 짧은 인용 방어를 통과한다("본문" 같은 두 글자는
    # 아무 문서에나 있어 지어낸 지적을 통과시키므로 막혀 있다).
    return ('{"results": [{"no": "1", "verdict": "위반", ' + kind_json +
            '"issue": "문제가 있다", "quotes": ["' + _TEXT + '"]}]}')


def test_prompt_asks_for_kind_with_a_closed_vocabulary():
    """어휘를 안 닫으면 모델이 매번 다른 말을 만들어 등급 매핑이 무너진다."""
    llm = _LLM('{"results": []}')

    ChunkCriteriaChecker(criteria=[_Crit("1", "x")]).check(_doc([_TEXT]), _ctx(llm, text=_TEXT))

    p = llm.prompts[0]
    assert "kind" in p, "종류를 물어보지 않는다"
    for word in ("모순", "표기", "모호"):
        assert word in p, f"허용 어휘 '{word}' 가 프롬프트에 없다"


def test_contradiction_is_major():
    """그대로 두면 시스템이 잘못 만들어진다 — 문서를 그대로 낼 수 없다."""
    llm = _LLM(_violation('"kind": "모순", '))

    got = ChunkCriteriaChecker(criteria=[_Crit("1", "x")]).check(
        _doc([_TEXT]), _ctx(llm, text=_TEXT))

    assert [f.severity for f in got] == [Severity.MAJOR]


def test_typo_and_ambiguity_stay_minor():
    """고쳐야 하지만 문서를 막지는 않는다."""
    for kind in ("표기", "모호"):
        llm = _LLM(_violation(f'"kind": "{kind}", '))
        got = ChunkCriteriaChecker(criteria=[_Crit("1", "x")]).check(
            _doc([_TEXT]), _ctx(llm, text=_TEXT))
        assert [f.severity for f in got] == [Severity.MINOR], kind


def test_missing_or_unknown_kind_falls_to_the_lower_grade():
    """모르는 것을 위로 올리지 않는다.

    반대로 두면(기본 MAJOR) 모델이 칸을 빠뜨릴 때마다 거짓 경보가 된다. 옛 응답
    형식(kind 없음)도 그대로 돌아야 한다 — 그 지적이 사라지면 안 된다.
    """
    for kind_json in ("", '"kind": "치명적", ', '"kind": 3, '):
        llm = _LLM(_violation(kind_json))
        got = ChunkCriteriaChecker(criteria=[_Crit("1", "x")]).check(
            _doc([_TEXT]), _ctx(llm, text=_TEXT))
        assert [f.severity for f in got] == [Severity.MINOR], kind_json
        assert got[0].message == "문제가 있다", "등급을 가르다 지적을 잃었다"


# ── 해당없음: 기준이 이 문서를 대상으로 하지 않을 때 ────────────────────────
# 실측(2026-08-05, Qwen3.6-27B): 어휘가 위반·통과 둘뿐이던 때, 기준 24
# ("고객이 제출한 데이터 품질 요구사항 명세서를 분석하는 기능")를 원자력 V&V
# 보고서에 걸었더니 청크마다 "이 조각엔 데이터 품질 분석이 없다"를 **위반**으로
# 답해 35건이 나왔다. 전체 53건 중 66%가 그것이었다. 모델 잘못이 아니다 —
# 통과라고 하면 검사도 안 하고 통과시킨 거짓말이 되므로, 주어진 둘 중에서는
# 위반이 그나마 정직했다. 모를 방법을 안 준 쪽이 잘못이다.

def test_prompt_offers_not_applicable():
    llm = _LLM('{"results": []}')

    ChunkCriteriaChecker(criteria=[_Crit("1", "x")]).check(_doc([_TEXT]), _ctx(llm, text=_TEXT))

    assert "해당없음" in llm.prompts[0], "모델이 '이 기준은 대상이 아니다' 라고 말할 길이 없다"


def test_not_applicable_yields_no_finding():
    """지적이 아니다 — 문서의 결함이 아니라 기준이 안 맞는 것이다."""
    llm = _LLM('{"results": [{"no": "1", "verdict": "해당없음"}]}')
    ck = ChunkCriteriaChecker(criteria=[_Crit("1", "x")])

    got = ck.check(_doc([_TEXT]), _ctx(llm, text=_TEXT))

    assert got == [], f"해당없음이 지적을 냈다: {[f.message for f in got]}"
    assert ck.verdicts["1"] == "해당없음"


def test_not_applicable_never_flips_to_pass():
    """통과로 뒤집으면 "이 기준으로 봤고 문제 없다"는 거짓말이 된다 — 안 본 것이다."""
    llm = _LLM('{"results": [{"no": "1", "verdict": "해당없음"}]}')
    ck = ChunkCriteriaChecker(criteria=[_Crit("1", "x")])

    ck.check(_doc([_TEXT]), _ctx(llm, chunks=3, text=_TEXT))

    assert ck.verdicts["1"] != "통과", "해당없음이 통과로 뒤집혔다"


def test_one_real_pass_beats_not_applicable():
    """조각 하나라도 실제로 봤으면 통과다. 전부 해당없음일 때만 해당없음이다."""
    llm = _LLM(['{"results": [{"no": "1", "verdict": "해당없음"}]}',
                '{"results": [{"no": "1", "verdict": "통과"}]}'])
    ck = ChunkCriteriaChecker(criteria=[_Crit("1", "x")])

    ck.check(_doc([_TEXT]), _ctx(llm, chunks=2, text=_TEXT))

    assert ck.verdicts["1"] == "통과"


def test_violation_still_wins():
    """위반은 무엇보다 세다 — 다른 조각이 해당없음이어도 지워지면 안 된다."""
    llm = _LLM([_violation('"kind": "모순", '),
                '{"results": [{"no": "1", "verdict": "해당없음"}]}'])
    ck = ChunkCriteriaChecker(criteria=[_Crit("1", "x")])

    got = ck.check(_doc([_TEXT]), _ctx(llm, chunks=2, text=_TEXT))

    assert ck.verdicts["1"] == "위반"
    assert [f.severity for f in got] == [Severity.MAJOR]


# ── 지적 종류(kind)가 살아 나간다 ──────────────────────────────────────────
# 모델이 답한 kind(모순·표기·모호)로 등급만 뽑고 값 자체를 버리고 있었다. 그래서
# 화면은 스물몇 건을 전부 `표현 점검` 한 가지로 보여주고, 갈리는 것은 뱃지 색뿐이
# 었다(주황=major 노랑=minor). 검토자가 그 뜻을 알 리 없다.


def _one_finding(kind: str, doc_text: str = "본문에 문제가 있다"):
    llm = _LLM(
        f'{{"results": [{{"no": "15", "verdict": "위반", "kind": "{kind}", '
        f'"issue": "무언가 어긋난다", "quotes": ["{doc_text}"]}}]}}')
    crit = _Crit(no="15", text="표현 검토")
    fs = ChunkCriteriaChecker(criteria=[crit]).check(_doc([doc_text]),
                                                  _ctx(llm, text=doc_text))
    return [f for f in fs if not f.unreviewed]


def test_kind_가_지적에_실린다():
    fs = _one_finding("모순")
    assert fs and fs[0].kind == "모순"
    assert fs[0].severity is Severity.MAJOR      # 등급도 그대로 간다


def test_표기는_경미로_남는다():
    fs = _one_finding("표기")
    assert fs and fs[0].kind == "표기"
    assert fs[0].severity is Severity.MINOR


def test_어휘_밖의_kind_는_싣지_않는다():
    """모델이 지어낸 말을 뱃지에 그대로 내보내지 않는다."""
    fs = _one_finding("심각한 오류")
    assert fs and fs[0].kind == ""
    assert fs[0].severity is Severity.MINOR      # 어휘 밖은 낮은 쪽


# ── 지적은 근거가 있는 자리를 가리킨다 ──────────────────────────────────────
# verify_quotes 는 문서 전체를 뒤지므로 근거가 모델이 보던 조각 밖에서 나올 수 있다.
# 그때 chunk 위치를 달면 지적을 눌러도 인용이 없는 절로 간다 — 검토자가 문제를 눈으로
# 확인할 수 없다. 실측: "'운영 파일'과 '운영파일'이 다르다" 가 §10.3 을 가리키는데
# 두 인용은 §10.1·§10.2 에 있었다.


def test_지적은_첫_근거의_절을_가리킨다():
    doc = Document(source_path="x.md", doc_type="generic", sections=[
        Section(id="1", title="가", level=1, text="운영 파일을 쓴다",
                anchor=Anchor(None, "1")),
        Section(id="2", title="나", level=1, text="운영파일을 쓴다",
                anchor=Anchor(None, "2")),
    ])
    llm = _LLM('{"results": [{"no": "15", "verdict": "위반", "kind": "모순", '
               '"issue": "표기가 다르다", "quotes": ["운영파일을 쓴다"]}]}')
    # 모델은 1절 조각을 보고 있었다.
    ctx = Context(review=_Review(), llm=llm,
                  chunks=[Chunk(id="1#0", text="운영 파일을 쓴다",
                                anchor=Anchor(None, "1"), section_id="1")])
    fs = [f for f in ChunkCriteriaChecker(criteria=[_Crit(no="15", text="표기 통일")])
          .check(doc, ctx) if not f.unreviewed]
    assert fs, "지적이 없다"
    assert fs[0].evidence and fs[0].evidence[0].anchor.section == "2"
    assert fs[0].anchor.section == "2", \
        f"근거는 2절인데 지적이 {fs[0].anchor.section}절을 가리킨다"
