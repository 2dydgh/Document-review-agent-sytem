"""rescue — 사전 유사 검색과 구조 라운드."""
from __future__ import annotations

import json
import threading
from types import SimpleNamespace

from modules.agent_quality import ChunkCriteriaChecker
from modules.agent_quality.rescue import (
    RescueCandidate,
    closest_lines,
    rescue_round,
)
from modules.llm_client import Response
from modules.shared import Anchor, Chunk, Context, Document, Section


class ScriptedLLM:
    """응답 목록을 순서대로 재생하는 가짜 LLM. 소진되면 빈 응답."""

    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.calls = 0

    def chat(self, messages, **opts) -> Response:
        self.calls += 1
        if not self.responses:
            return Response(text="")
        return Response(text=self.responses.pop(0))

    def complete(self, prompt: str, **opts) -> Response:
        return self.chat([{"role": "user", "content": prompt}], **opts)


def _doc(*texts: str) -> Document:
    sections = [
        Section(id=f"s{i}", title=f"절{i}", level=1, text=t,
                anchor=Anchor(page=i + 1, section=f"절{i}"))
        for i, t in enumerate(texts)
    ]
    return Document(source_path="t.pdf", doc_type=None, sections=sections)


def test_closest_lines_exact_substring_wins():
    doc = _doc("응답 시간은 3초 이내여야 한다.\n다른 줄이다.",
               "전혀 관련 없는 절이다.")
    hits = closest_lines(doc, "응답 시간은 3초", k=3)
    assert hits
    assert "응답 시간은 3초" in hits[0][0]
    assert hits[0][1].section == "절0"


def test_closest_lines_token_overlap():
    # 통짜로는 없지만 낱말이 겹치는 줄을 찾는다 — 모델이 고쳐 쓴 인용의 원형 찾기.
    doc = _doc("시스템은 데이터를구현하여 저장한다.",
               "무관한 내용만 있는 절.")
    hits = closest_lines(doc, "시스템은 데이터를 구현하여 저장한다", k=3)
    assert hits
    assert "데이터를구현하여" in hits[0][0]


def test_closest_lines_no_match_empty():
    doc = _doc("가나다라마바사.")
    assert closest_lines(doc, "xyzw qwerty", k=3) == []


def test_closest_lines_respects_k():
    doc = _doc("\n".join(f"공통 낱말 시험 문장 {i}" for i in range(10)))
    assert len(closest_lines(doc, "공통 낱말 시험", k=5)) == 5


# rescue_round 테스트들

REAL = "시스템은 데이터를구현하여 저장한다."
# 모델이 "고쳐 쓴" 실패 인용 — 원문과 낱말은 겹치므로 closest_lines 가 원문을
# 찾아 보여줄 수 있지만, 띄어쓰기를 고쳐 써서 verify_quotes 는 통과하지 못한다.
PARA = "시스템은 데이터를 구현하여 저장한다"


def _cand(quotes=None) -> RescueCandidate:
    return RescueCandidate(no="1", message="띄어쓰기 오류가 있다", kind="표기",
                           quotes=quotes or [PARA],
                           anchor=Anchor(page=1, section="절0"))


def test_rescue_revives_on_valid_requote():
    doc = _doc(REAL)
    llm = ScriptedLLM([json.dumps({"quotes": [REAL]}, ensure_ascii=False)])
    out = rescue_round([_cand()], doc, llm)
    assert len(out) == 1 and out[0].evidence is not None
    assert out[0].evidence[0].quote == REAL
    assert not out[0].errored and out[0].searched == []
    assert llm.calls == 1


def test_rescue_withdrawal_drops():
    doc = _doc(REAL)
    llm = ScriptedLLM([json.dumps({"verdict": "철회"}, ensure_ascii=False)])
    out = rescue_round([_cand()], doc, llm)
    assert out[0].evidence is None and not out[0].errored


def test_rescue_broken_format_drops():
    doc = _doc(REAL)
    llm = ScriptedLLM(["설명만 늘어놓는 응답이다. JSON 이 없다."])
    assert rescue_round([_cand()], doc, llm)[0].evidence is None


def test_rescue_requote_still_missing_drops():
    # 재인용도 문서에 없으면 폐기 — 환각이 부활할 길은 없다.
    doc = _doc(REAL)
    llm = ScriptedLLM([json.dumps({"quotes": ["여전히 없는 문장 qqq"]},
                                  ensure_ascii=False)])
    assert rescue_round([_cand()], doc, llm)[0].evidence is None


def test_rescue_tool_then_requote():
    doc = _doc(REAL)
    llm = ScriptedLLM([
        json.dumps({"tool": "find_term", "args": {"term": "데이터를구현하여"}},
                   ensure_ascii=False),
        json.dumps({"quotes": [REAL]}, ensure_ascii=False),
    ])
    out = rescue_round([_cand()], doc, llm)
    assert out[0].evidence is not None
    # 여정에 모델이 쓴 검색어가 남는다 — 화면의 "재확인 여정"이 이걸 그린다.
    assert out[0].searched == ["데이터를구현하여"]
    assert llm.calls == 2      # 후보당 상한이 정확히 2회


def test_rescue_tool_twice_hits_call_cap():
    # 도구만 두 번 부르면 재인용 없이 상한 도달 → 폐기.
    doc = _doc(REAL)
    tool = json.dumps({"tool": "find_term", "args": {"term": "데이터"}},
                      ensure_ascii=False)
    llm = ScriptedLLM([tool, tool])
    assert rescue_round([_cand()], doc, llm)[0].evidence is None
    assert llm.calls == 2


def test_rescue_llm_error_drops():
    doc = _doc(REAL)

    class ErrLLM:
        def chat(self, messages, **opts):
            return Response(text="", error="연결할 수 없음")

    # LLM 오류는 근거를 못 댄 것과 다른 상태(errored)다 — 폐기라는 결과는
    # 같지만, INFO 가 "0건 통과"와 "검토를 못 했다"를 섞지 않으려면 구분해야
    # 한다(루트 CLAUDE.md).
    out = rescue_round([_cand()], doc, ErrLLM())
    assert out[0].evidence is None and out[0].errored


def test_rescue_disallowed_tool_drops():
    # 노출한 도구는 find_term 하나다 — 다른 DocTools 도구를 부르면 폐기.
    doc = _doc(REAL)
    llm = ScriptedLLM([json.dumps(
        {"tool": "get_section", "args": {"section_id": "s0"}},
        ensure_ascii=False)])
    assert rescue_round([_cand()], doc, llm)[0].evidence is None
    assert llm.calls == 1


def test_rescue_real_but_unshown_quote_drops():
    # 핵심 방어: 문서에 실재하지만 이 라운드에서 모델에게 보여주지 않은 문장은
    # 근거로 인정하지 않는다 — "아무 실문장이나 주워 와 통과"하는 경로 차단.
    other = "관제 화면에 상태가 표시되어야 한다."
    doc = _doc(REAL, other)
    llm = ScriptedLLM([json.dumps({"quotes": [other]}, ensure_ascii=False)])
    assert rescue_round([_cand()], doc, llm)[0].evidence is None


def test_rescue_round_reports_lane_plan_and_steps():
    # 재확인은 정식 레인이다 — plan(작업량 신고) 뒤 step(진척)이 와야 화면이
    # 레인을 그린다. 문구 한 줄(detail)만으로는 사실상 보이지 않았다.
    doc = _doc(REAL)
    llm = ScriptedLLM([json.dumps({"quotes": [REAL]}, ensure_ascii=False)])
    events: list[dict] = []
    rescue_round([_cand()], doc, llm, on_progress=events.append,
                 label="표현 점검")
    plans = [e for e in events if "plan" in e]
    steps = [e for e in events if "step" in e]
    assert plans and plans[0]["plan"] == [
        {"kind": "rescue", "total": 1, "label": "표현 점검 근거 재확인",
         "description": "원문에서 인용 근거를 다시 찾는 중", "scope": "후보 1건"}]
    assert steps and steps[-1]["step"] == {
        "kind": "rescue", "i": 1, "total": 1, "label": "표현 점검 근거 재확인"}


def test_rescue_max_caps_attempts():
    doc = _doc(REAL)
    ok = json.dumps({"quotes": [REAL]}, ensure_ascii=False)
    llm = ScriptedLLM([ok, ok, ok])
    out = rescue_round([_cand(), _cand(), _cand()], doc, llm, max_rescues=1)
    assert len(out) == 1       # 시도한 것만 돌려준다 — 초과분은 호출부가 센다
    assert llm.calls == 1


# 동시성 아래에서도 순서-근거 짝이 맞는지: pool.map 은 입력 순서대로 결과를 낸다는
# 성질에 zip(cands, outcomes) 의 정확성이 통째로 달려 있다. workers=1 이면 이
# 성질이 시험되지 않는다(순차 실행이라 순서가 섞일 여지가 없다).
_REAL2 = "화면은 정상 상태를 5초마다 갱신한다."
_PARA2 = "화면은 정상상태를 5초마다 갱신한다"
_REAL3 = "로그는 자정마다 자동으로 삭제된다."
_PARA3 = "로그는 자정마다 자동으로삭제된다"


class _EchoRealLLM:
    """이 라운드에서 보여준 원문 줄을 그대로 되돌려준다.

    어느 스레드가 어떤 후보를 처리하든 '방금 보인 원문'만 정확히 돌려주므로,
    출력이 cand 순서와 뒤바뀌면 즉시 드러난다(quotes 셋이 서로 다른 실문장을
    가리키기 때문).
    """

    def __init__(self):
        self.calls = 0
        self._lock = threading.Lock()

    def chat(self, messages, **opts) -> Response:
        with self._lock:
            self.calls += 1
        prompt = messages[0]["content"]
        for real in (REAL, _REAL2, _REAL3):
            if real in prompt:
                return Response(text=json.dumps({"quotes": [real]}, ensure_ascii=False))
        return Response(text=json.dumps({"verdict": "철회"}, ensure_ascii=False))


def test_rescue_round_pairs_order_with_evidence_under_workers():
    doc = _doc(REAL, _REAL2, _REAL3)
    cands = [
        RescueCandidate(no="1", message="M1", kind="표기", quotes=[PARA],
                        anchor=Anchor(page=1, section="절0")),
        RescueCandidate(no="2", message="M2", kind="표기", quotes=[_PARA2],
                        anchor=Anchor(page=1, section="절1")),
        RescueCandidate(no="3", message="M3", kind="표기", quotes=[_PARA3],
                        anchor=Anchor(page=1, section="절2")),
    ]
    out = rescue_round(cands, doc, _EchoRealLLM(), max_rescues=3, workers=2)
    assert [o.evidence[0].quote if o.evidence else None
            for o in out] == [REAL, _REAL2, _REAL3]


# ChunkCriteriaChecker 통합 테스트들


def _ctx(llm, rescue_max: int = 10) -> Context:
    chunk = Chunk(id="c0", text=REAL, anchor=Anchor(page=1, section="절0"),
                  section_id="s0")
    ctx = Context(review=SimpleNamespace(), llm=llm, chunks=[chunk])
    ctx.rescue_max = rescue_max    # Task 4 전에는 동적 속성, 후에는 필드
    return ctx


def _criterion():
    return SimpleNamespace(no="1", text="오탈자가 없어야 한다", note="")


def _first_pass(quotes: list[str]) -> str:
    return json.dumps({"results": [{
        "no": "1", "verdict": "위반", "kind": "표기",
        "issue": "띄어쓰기 오류", "quotes": quotes}]}, ensure_ascii=False)


def test_checker_revives_dropped_finding():
    # 1차: 고쳐 쓴 인용(PARA) → 대조 실패. 구조: 실재 원문 재인용 → 부활.
    llm = ScriptedLLM([
        _first_pass([PARA]),
        json.dumps({"quotes": [REAL]}, ensure_ascii=False),
    ])
    checker = ChunkCriteriaChecker(criteria=[_criterion()])
    doc = _doc(REAL)
    findings = checker.check(doc, _ctx(llm))
    real = [f for f in findings if not f.unreviewed and f.severity.value != "info"]
    assert len(real) == 1
    assert real[0].evidence[0].quote == REAL
    assert real[0].rule_id == "1"
    # 재질의 끝에 살아난 지적은 출처 표시를 단다 — 화면 뱃지·실측 검수가 읽는다.
    assert real[0].rescued is True
    # 여정도 함께 — 처음 인용(실패)과 검색어. 확정 근거는 evidence 가 담는다.
    assert real[0].rescue_trace == {"failed_quotes": [PARA], "searched": []}
    assert checker.verdicts["1"] == "위반"
    info = [f for f in findings if f.severity.value == "info"]
    assert any("복원" in f.message for f in info)


def test_checker_failed_rescue_drops_with_info():
    llm = ScriptedLLM([
        _first_pass([PARA]),
        json.dumps({"verdict": "철회"}, ensure_ascii=False),
    ])
    checker = ChunkCriteriaChecker(criteria=[_criterion()])
    findings = checker.check(_doc(REAL), _ctx(llm))
    assert not [f for f in findings if not f.unreviewed
                and f.severity.value != "info"]
    assert checker.verdicts["1"] == "미판정"    # 근거 없는 위반을 통과로 뒤집지 않는다
    assert any("제외" in f.message for f in findings)


def test_checker_rescue_off_keeps_old_behavior():
    # rescue_max=0 이면 구조 호출 자체가 없다 — 기존 동작·기존 문구.
    llm = ScriptedLLM([_first_pass([PARA])])
    checker = ChunkCriteriaChecker(criteria=[_criterion()])
    findings = checker.check(_doc(REAL), _ctx(llm, rescue_max=0))
    assert llm.calls == 1
    assert any("원문 대조를 통과하지 못해 제외" in f.message for f in findings)


def test_rescue_skips_candidate_without_substantive_quote():
    # 1차에서 실질적 근거를 하나도 대지 않은 위반은 구조 대기열에 들어가지 않고
    # 그 자리에서 버려진다 — 짧은 조각을 검색 키로 쓰면 문턱 역전이 된다.
    two = json.dumps({"results": [
        {"no": "1", "verdict": "위반", "kind": "표기",
         "issue": "인용 없음", "quotes": []},
        {"no": "1", "verdict": "위반", "kind": "표기",
         "issue": "인용이 너무 짧음", "quotes": ["상태"]},
    ]}, ensure_ascii=False)
    llm = ScriptedLLM([two])
    checker = ChunkCriteriaChecker(criteria=[_criterion()])
    findings = checker.check(_doc(REAL), _ctx(llm))
    assert llm.calls == 1              # 구조 호출이 없다 — 즉시 폐기
    assert not [f for f in findings if not f.unreviewed
                and f.severity.value != "info"]
    assert any("실질적" in f.message and "2건" in f.message for f in findings)


def test_checker_over_cap_reported():
    # 후보 2건, 상한 1 → 1건 시도(성공), 1건은 상한 초과로 제외 + 문구에 드러남.
    two = json.dumps({"results": [
        {"no": "1", "verdict": "위반", "kind": "표기",
         "issue": "오류 A", "quotes": [PARA]},
        {"no": "1", "verdict": "위반", "kind": "표기",
         "issue": "오류 B", "quotes": [PARA + " 그리고"]},
    ]}, ensure_ascii=False)
    llm = ScriptedLLM([two, json.dumps({"quotes": [REAL]}, ensure_ascii=False)])
    checker = ChunkCriteriaChecker(criteria=[_criterion()])
    findings = checker.check(_doc(REAL), _ctx(llm, rescue_max=1))
    assert llm.calls == 2
    assert any("상한" in f.message for f in findings)


def test_checker_rescue_skips_fabricated_rule_id():
    # 구조 성공 응답이라도 rule_id 가 애초에 물은 기준 목록에 없으면(모델이
    # 지어낸 번호) 지적째 버린다 — 1차 관문과 같은 규칙이다.
    first_pass = json.dumps({"results": [{
        "no": "99", "verdict": "위반", "kind": "표기",
        "issue": "지어낸 번호", "quotes": [PARA]}]}, ensure_ascii=False)
    llm = ScriptedLLM([first_pass, json.dumps({"quotes": [REAL]}, ensure_ascii=False)])
    checker = ChunkCriteriaChecker(criteria=[_criterion()])
    findings = checker.check(_doc(REAL), _ctx(llm))
    real = [f for f in findings if not f.unreviewed and f.severity.value != "info"]
    assert real == []
    assert checker.verdicts["1"] == "미판정"


def test_checker_rescue_error_reported_separately():
    # LLM 오류로 재확인 자체를 못 한 것은 "근거를 대지 못해 제외"와 다른
    # 절로 드러나야 한다 — 섞으면 '검토를 못 했다'가 '0건 통과'로 읽힌다.
    class ErrLLM:
        def __init__(self):
            self.calls = 0

        def complete(self, prompt: str, **opts) -> Response:
            self.calls += 1
            return Response(text=_first_pass([PARA]))

        def chat(self, messages, **opts) -> Response:
            return Response(text="", error="연결할 수 없음")

    checker = ChunkCriteriaChecker(criteria=[_criterion()])
    findings = checker.check(_doc(REAL), _ctx(ErrLLM()))
    infos = [f.message for f in findings if f.severity.value == "info"]
    assert any("응답을 받지 못해" in m for m in infos)
    assert not any("근거를 대지 못해" in m for m in infos)
