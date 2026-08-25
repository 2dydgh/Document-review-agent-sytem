"""규칙기반 체커: 본문 표기 규칙을 정규식으로 검사한다.

팀 기준에는 "날짜는 `YYYY. MM. DD.`", "`%` 앞에 공백", "천 단위 쉼표 금지" 처럼
**글자 모양만 보면 판정되는** 항목이 많다. AI시험인증1팀 단일문서 md §1.3(표기)이
통째로 그렇고, §1.5(시험 환경)에도 섞여 있다.

이런 것을 검사기 하나씩 만들면 아홉 개가 된다. 모양이 다 같기 때문에 하나로 묶고
**규칙값은 기준의 `params` 가 준다** — 팀마다 날짜 형식이 다르고, 엔진에 팀 규칙을
박지 않는다는 원칙 그대로다.

## 두 가지 모양뿐이다

    find + must   "이렇게 생긴 것을 찾아, 그것이 이 형식인지 본다"
                  날짜처럼 보이는 것을 찾아 `YYYY. MM. DD.` 인지

    forbid        "이건 나오면 안 된다"
                  천 단위 쉼표 `10,000` · 곱셈 기호로 쓴 `x`

`find` 없이 `must` 만 주면 아무것도 안 한다 — 무엇을 찾을지 모르면 "형식이 맞다"고
말할 수 없다. 그때는 미검토로 알린다.

## 인용은 코드가 문서에서 꺼낸다

LLM 검사와 달리 **환각 관문이 필요 없다.** 지적의 근거가 정규식이 매치한 그 자리라
문서에 실재하는 것이 보장된다.

## 왜 MINOR 인가

표기 규칙은 "고쳐야 하지만 이대로도 낼 수는 있는" 것이다(CLAUDE.md 심각도 기준).
날짜 표기가 틀렸다고 문서를 못 내지는 않는다. 기준이 `severity: major` 를 적으면
그쪽이 이긴다 — 팀이 "우리는 이게 반려 사유다" 라고 하면 그게 맞다.
"""
from __future__ import annotations

import re

from modules.shared import Anchor, Context, Document, Evidence, Finding, Severity

#: 한 기준이 낼 지적 수의 상한. 같은 표기 실수가 문서 전체에 퍼져 있으면 수백 건이
#: 나와 화면이 그것만으로 덮인다. 넘치면 잘랐다는 사실을 INFO 로 밝힌다 —
#: 조용히 자르면 "이만큼만 있다"가 거짓이 된다.
_MAX_HITS = 30

#: 인용에 함께 실을 앞뒤 글자 수. 값만 실으면(`10,000`) 화면이 그것을 문서에서
#: 못 찾는다 — 같은 값이 여러 번 나오기 때문이다.
_CONTEXT = 24


class TextPatternChecker:
    """본문 표기 규칙 검사.

    name 은 `PlaceholderChecker` 와 같은 `completeness` 다 — 리포트에서 형식·완전성
    묶음으로 모인다.
    """

    name = "completeness"
    label = "표기 규칙 검사"

    def __init__(self, find: str = "", must: str = "", forbid: str = "",
                 message: str = "", rule_id: str = "") -> None:
        self.find = find
        self.must = must
        self.forbid = forbid
        self.message = message
        self.rule_id = rule_id

    # ── 판정 ─────────────────────────────────────────────────────────

    def check(self, doc: Document, ctx: Context | None = None) -> list[Finding]:
        if not (self.forbid or (self.find and self.must)):
            return [self._unreviewed(
                "표기 규칙이 검토 기준에 없어 표기 검사를 수행하지 않았습니다.",
                "검토 기준 항목의 params 에 forbid 또는 find+must 를 적으면 이 검사가 됩니다.")]
        try:
            forbid = re.compile(self.forbid) if self.forbid else None
            find = re.compile(self.find) if self.find else None
            must = re.compile(self.must) if self.must else None
        except re.error as exc:
            # 정규식이 깨졌으면 "규칙에 맞지 않는다"가 아니라 "재지 못했다"다.
            # 지적으로 내면 멀쩡한 문서가 전부 틀린 것으로 뜬다.
            return [self._unreviewed(
                f"표기 규칙의 정규식이 올바르지 않아 검사하지 못했습니다: {exc}",
                "검토 기준의 forbid·find·must 를 고치세요.")]

        out: list[Finding] = []
        hits = 0
        cut = False
        for section in doc.iter_sections():
            text = section.text or ""
            if not text:
                continue
            for at, bad in self._violations(text, forbid, find, must):
                if hits >= _MAX_HITS:
                    cut = True
                    break
                hits += 1
                out.append(self._flag(text, at, bad, section.anchor))
            if cut:
                break

        if cut:
            out.append(self._unreviewed(
                f"표기 지적이 {_MAX_HITS}건을 넘어 나머지는 싣지 않았습니다 — "
                "같은 실수가 문서 전체에 퍼져 있습니다.",
                "먼저 한 곳을 고치는 방법을 정하고 문서 전체에 같이 적용하세요."))
        return out

    def _violations(self, text: str, forbid, find, must):
        """(위치, 걸린 문자열) 목록.

        forbid 는 매치 자체가 위반이고, find+must 는 **찾은 것이 must 에 안 맞을 때**
        위반이다. must 를 fullmatch 로 재는 이유: `2026.1.1` 이 `\\d{4}\\. \\d{2}\\. \\d{2}\\.`
        의 일부와 겹칠 수 있어 search 로 재면 틀린 표기가 통과한다.
        """
        if forbid is not None:
            for m in forbid.finditer(text):
                yield m.start(), m.group(0)
            return
        for m in find.finditer(text):
            got = m.group(0)
            if not must.fullmatch(got):
                yield m.start(), got

    # ── Finding 만들기 ───────────────────────────────────────────────

    def _flag(self, text: str, at: int, bad: str, anchor: Anchor) -> Finding:
        left = max(0, at - _CONTEXT)
        quote = " ".join(text[left:at + len(bad) + _CONTEXT].split())
        return Finding(
            checker=self.name,
            severity=Severity.MINOR,
            message=f"{self.message or '표기 규칙에 맞지 않습니다'} — {bad!r}",
            anchor=anchor,
            suggestion="문서 전체에서 같은 표기를 함께 고치세요.",
            rule_id=self.rule_id,
            evidence=[Evidence(anchor=anchor, quote=quote)])

    def _unreviewed(self, message: str, suggestion: str) -> Finding:
        return Finding(
            checker=self.name, severity=Severity.INFO, unreviewed=True,
            message=message, anchor=Anchor(page=None, section=None),
            suggestion=suggestion, rule_id=self.rule_id)
