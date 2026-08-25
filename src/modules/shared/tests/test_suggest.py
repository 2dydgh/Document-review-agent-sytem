"""수정안 생성. 핵심은 '못 만들면 못 만들었다고 말한다'는 것.

검토 도구가 그럴듯한 문장을 지어내면 검토자가 원문을 안 보고 갈아끼운다.
그래서 실패·빈 응답·형식 위반은 전부 revised를 비우고 이유를 남겨야 한다.
"""
from __future__ import annotations

from modules.llm_client import EchoLLM, Response
from modules.shared import suggest_revision

QUOTE = "제정일자: 2025.00.00."
MESSAGE = "존재하지 않는 날짜다."


class _Fixed:
    """정해진 문자열을 돌려주는 LLM."""

    def __init__(self, text="", error=None):
        self.text, self.error = text, error
        self.prompts: list[str] = []

    def complete(self, prompt, **opts):
        self.prompts.append(prompt)
        return Response(text=self.text, error=self.error)

    def chat(self, messages, **opts):
        return Response(text=self.text, error=self.error)


def test_returns_the_revised_sentence():
    llm = _Fixed("수정안: 제정일자: 2025.03.14.")
    out = suggest_revision(llm, MESSAGE, QUOTE)
    assert out.ok
    assert out.revised == "제정일자: 2025.03.14."
    assert out.original == QUOTE


def test_prompt_carries_the_finding_and_the_quote():
    """둘 중 하나라도 빠지면 LLM은 무엇을 왜 고치는지 모른다."""
    llm = _Fixed("수정안: x")
    suggest_revision(llm, MESSAGE, QUOTE)
    assert MESSAGE in llm.prompts[0]
    assert QUOTE in llm.prompts[0]


def test_llm_failure_is_not_reported_as_no_change_needed():
    llm = _Fixed(error="429 rate limited")
    out = suggest_revision(llm, MESSAGE, QUOTE)
    assert not out.ok
    assert "429" in out.reason


def test_empty_response_is_not_treated_as_success():
    """EchoLLM(=llm 꺼짐)이 여기로 온다. 빈 응답은 '고칠 게 없다'가 아니다."""
    out = suggest_revision(EchoLLM(), MESSAGE, QUOTE)
    assert not out.ok
    assert out.reason


def test_model_can_say_it_cannot_fix_it():
    """값을 정해야 풀리는 지적은 지어내지 말고 그렇다고 말해야 한다."""
    llm = _Fixed("수정불가: 실제 제정일자를 알아야 합니다.")
    out = suggest_revision(llm, MESSAGE, QUOTE)
    assert not out.ok
    assert "제정일자" in out.reason


def test_offformat_answer_is_refused_not_pasted_into_the_document():
    """설명문을 수정안으로 넘기면 그 설명이 문서에 들어간다."""
    llm = _Fixed("이 날짜는 잘못되었으므로 고쳐야 합니다.")
    out = suggest_revision(llm, MESSAGE, QUOTE)
    assert not out.ok
    assert out.revised == ""


def test_finding_without_a_quote_needs_no_llm_call():
    llm = _Fixed("수정안: 지어낸 문장")
    out = suggest_revision(llm, "TBD가 남아 있다", "")
    assert not out.ok
    assert llm.prompts == [], "고쳐 쓸 원문이 없는데 LLM을 부르면 문장을 지어낸다"


# ── 기준을 알아야 어느 방향으로 고칠지 정할 수 있다 ──────────────────────

def test_criterion_text_reaches_the_prompt():
    """기준을 모르면 모델이 반대로 고쳐놓고도 그럴듯한 문장을 낸다.

    SI 단위계는 수치와 단위 사이를 띄우는 것이 규칙이라 "5 kg" 가 맞는데,
    "띄어쓰기 오류"만 주면 "5kg" 로 붙여 놓을 수도 있다. 둘 다 문장으로는
    자연스러워서 검토자가 원문을 안 보고 갈아끼우면 규칙을 어긴 채로 남는다.
    """
    llm = _Fixed("수정안: 시험 대상 장비는 5 kg 이다.")
    suggest_revision(llm, message="띄어쓰기 오류", quote="시험 대상 장비 는 5kg 이다.",
                     criterion="SI 단위계 표기: 수치와 단위 사이를 띄운다")

    assert "SI 단위계" in llm.prompts[0]
    assert "[검토 기준]" in llm.prompts[0]


def test_works_without_criterion():
    # 기준 없는 일반 검토는 지금처럼 동작해야 한다.
    llm = _Fixed("수정안: 고친 문장")
    out = suggest_revision(llm, message="오류", quote="원문")

    assert out.ok
    assert out.revised == "고친 문장"
    assert "[검토 기준]" not in llm.prompts[0], "기준이 없으면 빈 절을 넣지 않는다"


def test_blank_criterion_is_treated_as_absent():
    # 프론트가 역맵에서 못 찾으면 빈 문자열을 보낸다 — 공백만 와도 절을 안 만든다.
    llm = _Fixed("수정안: 고친 문장")
    suggest_revision(llm, message="오류", quote="원문", criterion="   ")

    assert "[검토 기준]" not in llm.prompts[0]


def test_unchanged_revision_is_not_a_suggestion():
    """원문을 그대로 돌려주면 수정안이 아니다.

    같은 문장을 '수정안'이라 내놓으면 검토자가 그걸 복사해 붙여넣는다. 더 중요한 건
    이게 **그 인용에 지적이 안 맞는다는 신호**라는 점이다 — 지적 하나가 같은 표의
    이웃 줄까지 통째로 인용할 때, 어느 문장이 진짜인지 가릴 자리가 여기뿐이다.
    """
    llm = _Fixed("수정안:  제정일자:  2025.00.00.  ")   # 공백만 다른 원문
    out = suggest_revision(llm, MESSAGE, QUOTE)
    assert not out.ok
    assert "고칠 곳" in out.reason


def test_mismatch_between_two_places_shows_the_other_side():
    """모순 지적은 두 곳이 어긋나 나온다 — 다른 쪽을 안 보여주면 모델이 한쪽을
    정답으로 삼아 이쪽을 거기 맞춰 고쳐 쓴다.

    실측: 개요의 "기능 및 성능 시험" 이 표 제목의 "기능 및 성능 및 기타 시험" 으로
    바뀌어 나왔다. 그대로 붙여넣으면 문서가 하지도 않은 시험을 했다고 말한다.
    어느 쪽이 사실인지는 사람이 확인해야 한다.
    """
    llm = _Fixed("수정불가: 기타 시험을 실제로 수행했는지 확인해야 합니다.")
    out = suggest_revision(llm, "개요와 표 제목이 일치하지 않는다",
                           "기능 및 성능 시험을 절차에 따라 수행했다.",
                           others=["기능 및 성능 및 기타 시험"])
    prompt = llm.prompts[0]
    assert "기능 및 성능 및 기타 시험" in prompt, "다른 쪽 인용이 프롬프트에 없다"
    assert "다른 위치" in prompt
    assert not out.ok and "확인" in out.reason
