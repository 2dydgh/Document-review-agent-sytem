"""2문서 내용 대조(triage): 같은 ID인데 서술이 어긋나는지 본다.

TraceabilityChecker가 "ID가 있냐 없냐"만 보는 데 반해, 여기서는 **연결된**
ID에 대해 상위/하위 서술을 나란히 놓고 LLM에게 묻는다. ID 조인으로 후보가
이미 정해지므로 벡터 검색이 필요 없다.

목표는 "전문가 정답 재현"이 아니라 **사람이 볼 것을 골라주는 triage**다.
그래서 응답이 'ISSUE:'로 시작할 때만 finding을 만든다. 기본 EchoLLM은 빈
응답이므로 LLM 백엔드가 붙기 전까지는 0건이다 — 지적사항을 지어내지 않는다.

ISSUE 응답의 인용은 `verify_quotes`로 양쪽 원문에 대조하며, 통과 근거가
없으면 폐기하고 건수를 INFO로 남긴다(CLAUDE.md 환각 방지 계약). 재확인
(rescue) 레인은 문서 쌍 지원이 필요해 아직 없다 — 파이프라인 통일 때 싣는다.
"""
from __future__ import annotations

import re

from modules.shared import Anchor, Document, Finding, Severity
from modules.shared import Context
from modules.shared import verify_quotes
from .idref import extract_id_statements

# 프롬프트 튜닝 이력 (측정: scripts/eval_triage.py):
#   초안 "어긋나거나 빠뜨렸으면"        → precision 57%. 모델이 "설계가 덜 상세하다"까지
#                                        불일치로 올렸다.
#   +모순의 정의를 좁히고 예외를 열거    → qwen3:8b 100%, 그러나 Qwen3.6-27B는 71%.
#                                        한 모델에서만 재면 이걸 못 본다.
#   +"같은 대상" 요건 명시              → 두 모델 모두 precision 100% / recall 100%.
#
# 27B의 오탐 2건은 이 프롬프트 자신이 원인이었다. 모순 예시로 넣었던
# '"보관하지 않는다" vs "저장한다"'가 애매한 케이스(원본 vs 토큰)라서, 대상이
# 다른데도 지적하게 만들었다. 예시에서 빼고 "같은 대상" 규칙으로 대체했다.
_PROMPT = (
    "같은 요구사항 ID '{id}'에 대한 상위문서(요구사항)와 하위문서(설계) 서술이다.\n\n"
    "[상위문서 / {parent_section}]\n{parent}\n\n"
    "[하위문서 / {child_section}]\n{child}\n\n"
    "두 서술이 서로 **모순**되는지만 판단하라.\n"
    "모순이란 **같은 대상**에 대해 서로 다른 값·방식·방향을 말하는 것이다.\n"
    '예: "3초 이내" vs "5초", "SHA-256" vs "MD5", "제외한다" vs "포함한다".\n\n'
    "다음은 모순이 **아니다**. 이런 경우 반드시 빈 문자열로 답하라:\n"
    "- 설계가 요구사항의 세부 조건(횟수·순서·수단)을 언급하지 않은 경우.\n"
    '  예: 요구 "3회까지 재시도한 뒤 알린다" vs 설계 "알림을 발송한다"'
    " → 모순 아님(생략일 뿐).\n"
    "- 설계가 요구사항보다 더 상세하거나 구현 수단을 덧붙인 경우.\n"
    "- 같은 대상을 다른 용어로 부른 경우.\n"
    "- 두 서술이 **서로 다른 대상**을 말하는 경우.\n"
    '  예: 요구 "원본 카드번호는 보관하지 않는다" vs 설계 "카드번호를 토큰화하여 저장한다"\n'
    '  → 모순 아님(원본과 토큰은 다른 대상). 설계가 "원본을 저장한다"고 해야 모순이다.\n\n'
    "답하는 방법:\n"
    '- 모순이 있으면 한 줄로: ISSUE: 상위 "<상위 원문 인용>" vs 하위 "<하위 원문 인용>"'
    " — <무엇이 충돌하는지>\n"
    "- 충돌하는 표현을 양쪽 원문에서 그대로 인용할 수 없으면 모순이 아니다. "
    "빈 문자열로 답하라.\n"
    "- 확실하지 않으면 빈 문자열로 답하라."
)

_MARKER = "ISSUE:"

# 프롬프트가 강제한 응답 형식에서 상·하위 인용을 뽑는다. 모델이 곧은따옴표
# 대신 굽은따옴표로 옮겨 적는 것까지는 형식 문제로 죽이지 않는다 — 인용
# "내용"의 실재 여부는 어차피 verify_quotes 가 가른다.
_QUOTES = re.compile(r'상위\s*["“]([^"”]+)["”]\s*vs\s*하위\s*["“]([^"”]+)["”]')


class ContentMatchChecker:
    """연결된 ID의 상위/하위 서술을 대조한다. document=None → UI의 '불일치'."""

    name = "consistency"
    label = "내용 일치 대조"

    def check(self, doc: Document, ctx: Context) -> list[Finding]:
        child = ctx.other
        pattern = getattr(ctx.review, "id_pattern", "")
        if child is None or not pattern:
            return []

        parent_stmts = extract_id_statements(doc, pattern)
        child_stmts = extract_id_statements(child, pattern)

        findings: list[Finding] = []
        dropped = 0
        for _id, p in parent_stmts.items():
            c = child_stmts.get(_id)
            if c is None:
                continue  # 누락은 TraceabilityChecker의 몫이다
            resp = ctx.llm.complete(_PROMPT.format(
                id=_id, parent=p.text, child=c.text,
                parent_section=p.section_title, child_section=c.section_title))

            if resp.error:
                # 호출이 실패했으면 "모순 없음"이 아니라 "모르는 상태"다.
                # 조용히 넘기면 사용자는 검토가 통과했다고 믿는다.
                findings.append(Finding(
                    checker=self.name,
                    severity=Severity.INFO,
                    message=f"[{_id}] LLM 판정 실패 — 이 항목은 검토되지 않았습니다 "
                            f"({resp.error})",
                    anchor=c.anchor,
                    suggestion="LLM 설정을 확인하고 다시 실행하세요.",
                    document=None,
                    unreviewed=True,
                ))
                continue

            text = (resp.text or "").strip()
            if not text.startswith(_MARKER):
                continue
            body = text[len(_MARKER):].strip()
            # CLAUDE.md 계약: 인용이 문서에 실재하는지 코드로 대조한다.
            # 상위 인용은 상위문서에, 하위 인용은 하위문서에 각각 물어야 한다 —
            # 한 문서에 합쳐 물으면 상위 문장을 하위 인용이라 우겨도 통과한다.
            m = _QUOTES.search(body)
            found_p, _ = verify_quotes(doc, [m.group(1)] if m else [])
            found_c, _ = verify_quotes(child, [m.group(2)] if m else [])
            evidence = [*found_p, *found_c]
            if not evidence:
                # 통과한 근거가 하나도 없다 — 지어낸 지적일 수 있다. 폐기하되
                # 건수는 아래에서 INFO 로 드러낸다(조용히 지우면 "지적 없음"이
                # 된다). 문턱은 지적 전체 단위다: 한쪽 인용만 통과해도 살린다.
                dropped += 1
                continue
            findings.append(Finding(
                checker=self.name,
                # triage는 "사람이 확인할 것" 표시다. 결정적 판정(누락/근거없음,
                # major)보다 낮게 두어 정렬에서 뒤로 간다.
                severity=Severity.MINOR,
                message=f"[{_id}] {body}",
                anchor=c.anchor,
                suggestion="상위/하위 서술을 대조해 확인하세요. (LLM 제안, 검증 필요)",
                # parent/child 어느 한쪽의 문제가 아니라 둘 사이의 문제다.
                document=None,
                evidence=evidence,
            ))
        if dropped:
            findings.append(Finding(
                checker=self.name,
                severity=Severity.INFO,
                message=(f"내용 일치 대조에서 지적 후보 {dropped}건이 원문 대조를 "
                         f"통과하지 못해 제외되었습니다 (인용한 문장을 양쪽 "
                         f"문서에서 찾지 못함)."),
                anchor=Anchor(page=None, section=None),
                suggestion=("제외된 지적은 모델이 실재 근거를 대지 못한 것입니다. "
                            "필요하면 해당 요건 ID의 상·하위 서술을 직접 확인하세요."),
                document=None,
            ))
        return findings
