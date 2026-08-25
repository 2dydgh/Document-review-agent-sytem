"""지적 하나에 대한 구체적 수정안을 LLM에게 받는다.

검토는 "무엇이 잘못됐나"까지만 말한다. 이 모듈은 그 다음 한 걸음 —
"그래서 이 문장을 어떻게 고치나" — 를 사용자가 눌렀을 때만 묻는다.
검토 전체에 걸어두지 않는 이유는 지적 대부분이 읽고 넘기는 것이라
매번 문장을 새로 짓게 하면 검토가 느려지고 비싸지기 때문이다.

원칙은 검토 쪽과 같다: **못 만들면 못 만들었다고 말한다.** 그럴듯한 문장을
지어내면 검토자가 원문을 안 보고 갈아끼운다 — 검토 도구에서 이건 최악이다.
그래서 LLM이 없거나(echo) 실패하면 revised를 비우고 reason을 채운다.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from modules.llm_client import LLMClient

from .agent.verify import _norm

# 원문을 그대로 돌려주는 것도, 설명만 늘어놓는 것도 쓸모가 없다. 그래서
# 출력 형식을 못 박고, 고칠 수 없으면 고칠 수 없다고 말할 길을 열어둔다.
_MARKER_OK = "수정안:"
_MARKER_NO = "수정불가:"

_PROMPT = """당신은 기술 문서 검토자다. 아래 지적을 받은 원문을 고쳐 쓴다.
{criterion}[지적]
{message}

[원문]
{quote}
{others}
규칙:
- 원문과 같은 문체·형식을 유지하고, 지적된 부분만 최소한으로 고친다.
- 원문에 없는 사실(날짜, 수치, 고유명사)을 새로 지어내지 않는다.
  값을 정해야 풀리는 지적이면 자리를 `[확인 필요]`로 남긴다.
- **두 곳이 서로 어긋나 나온 지적이면 어느 쪽이 옳은지 원문만으로는 알 수 없다.**
  한쪽을 다른 쪽에 맞춰 고쳐 쓰지 마라 — 어느 쪽이 사실인지 확인해야 한다고
  수정불가로 답하라. 한쪽이 명백한 오타·탈자일 때만 고친다.
- 설명하지 말고 고쳐 쓴 문장만 낸다.

출력은 정확히 한 줄로 시작한다:
{ok} <고쳐 쓴 문장>
원문만으로 고칠 수 없으면:
{no} <무엇을 알아야 고칠 수 있는지 한 문장>
"""


@dataclass
class Suggestion:
    original: str
    # 고쳐 쓴 문장. 만들지 못했으면 빈 문자열 — 이 경우 reason이 왜인지 말한다.
    revised: str = ""
    # revised가 비었을 때만 채워진다. 화면은 이걸 그대로 보여준다.
    reason: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.revised)


def suggest_revision(llm: LLMClient, message: str, quote: str,
                     criterion: str = "",
                     others: Sequence[str] = ()) -> Suggestion:
    """지적 + 원문 (+ 검토 기준) → 수정안. 실패는 실패라고 말한다(빈 revised).

    기준을 함께 주는 이유: 기준을 모르면 어느 방향으로 고칠지 알 수 없다.
    SI 단위계는 수치와 단위를 띄우는 것이 규칙이라 "5 kg" 가 맞는데, "띄어쓰기
    오류"만 주면 모델이 반대로 붙여놓고도 그럴듯한 문장을 낸다 — 둘 다 문장으로는
    자연스러워서 검토자가 원문을 안 보고 갈아끼우면 규칙을 어긴 채로 남는다.

    기준이 없으면(일반 검토) 절을 만들지 않는다 — 빈 제목만 있는 절은 모델에게
    "기준이 없다"가 아니라 "기준을 못 읽었다"로 읽힌다.

    others 는 **같은 지적이 함께 든 다른 위치**다. 모순 지적은 두 곳이 어긋나
    나오는데, 한 곳만 주면 모델은 지적 문장에 적힌 다른 쪽 표현을 정답으로 삼아
    이쪽을 거기 맞춰 고쳐 쓴다 — 어느 쪽이 사실인지 아무도 확인하지 않았는데도.
    실측: 개요의 "기능 및 성능 시험" 을 표 제목의 "기능 및 성능 및 기타 시험" 으로
    바꿔 놓았다. 그대로 붙여넣으면 문서가 하지도 않은 시험을 했다고 말한다.
    """
    quote = (quote or "").strip()
    if not quote:
        # 근거 인용이 없는 지적(예: 규칙 체커의 TBD)은 고쳐 쓸 대상이 없다.
        return Suggestion(original="", reason="이 지적에는 고쳐 쓸 원문 인용이 없습니다.")

    crit = (criterion or "").strip()
    block = f"\n[검토 기준]\n{crit}\n\n" if crit else "\n"
    rest = [o.strip() for o in others if (o or "").strip()
            and _norm(o) != _norm(quote)]
    others_block = ("\n[같은 지적이 함께 든 다른 위치]\n"
                    + "\n".join(f"- {o}" for o in rest) + "\n") if rest else ""

    resp = llm.complete(_PROMPT.format(
        criterion=block, message=(message or "").strip(), quote=quote,
        others=others_block, ok=_MARKER_OK, no=_MARKER_NO))

    if resp.error:
        return Suggestion(original=quote,
                          reason=f"LLM 호출에 실패했습니다: {resp.error}")

    text = (resp.text or "").strip()
    if not text:
        # EchoLLM(=llm 꺼짐)이 여기로 온다. 빈 응답을 "고칠 게 없다"로 읽으면 안 된다.
        return Suggestion(original=quote,
                          reason="LLM이 응답하지 않았습니다(검토를 LLM 켜고 다시 실행하거나 설정을 확인하세요).")

    if text.startswith(_MARKER_NO):
        return Suggestion(original=quote, reason=text[len(_MARKER_NO):].strip()
                          or "원문만으로는 고칠 수 없다고 판단했습니다.")

    if text.startswith(_MARKER_OK):
        revised = text[len(_MARKER_OK):].strip()
        if not revised:
            return Suggestion(original=quote, reason="수정안이 비어 있습니다.")
        if _norm(revised) == _norm(quote):
            # 고칠 것이 없어 원문을 그대로 돌려줬다. 이걸 수정안이라고 내놓으면
            # 검토자가 같은 문장을 복사해 붙여넣는다. 더 중요한 건 **이 인용이
            # 지적에 안 맞는다는 신호**라는 점이다 — 지적 하나가 같은 표의 이웃
            # 줄까지 통째로 인용할 때(실측: 수일치 오류 지적에 문장 18개), 어느
            # 문장이 진짜인지 가릴 수 있는 자리가 여기뿐이다. 코드가 판정하지
            # 않고 모델이 고칠 게 없다고 한 사실만 그대로 말한다.
            return Suggestion(
                original=quote,
                reason="이 문장에서는 고칠 곳을 찾지 못했습니다 — "
                       "지적이 이 인용에는 해당하지 않을 수 있습니다.")
        return Suggestion(original=quote, revised=revised)

    # 형식을 안 지킨 응답. 본문으로 삼아 갈아끼우게 두면 설명문이 문서에 들어간다.
    return Suggestion(
        original=quote,
        reason="LLM이 정해진 형식으로 답하지 않아 수정안으로 쓸 수 없습니다.")
