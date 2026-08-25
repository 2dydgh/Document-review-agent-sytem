"""규칙기반 체커: 참조문서 목록과 본문 인용 대조 (EV2 25).

약어 대조와 같은 모양의 양방향이다:

  · 본문이 인용했는데 목록에 없다  → 목록에 없는 문서를 참조했다
  · 목록에 있는데 본문이 안 쓴다   → 지워야 한다

**목록은 번호 붙은 하위 절이다.** 실측(SHN34 ESF-CCS RVVR·SRS, SKN56 CPS RVVR):

    3.0 References
      3.1 Regulations
        3.1.1 NUREG-0800, BTP 7-14, Rev.06, "Guidance on Software Reviews..."
        3.1.2 NUREG/CR-6430, "Software Safety Hazard Analysis", 1996
      3.2 Codes and Standards
        3.2.1 IEEE Std. 610.12-1990, ...

본문은 번호로 인용한다 — `refer to IEEE Std. 610.12-1990 (reference 3.2.1)`.
그래서 대조 단위가 문서명이 아니라 **절 번호**다. 문서명으로 맞추려 들면 같은
문서를 부르는 이름이 문서마다 달라 대조가 안 된다.

**목록을 제대로 못 읽었으면 지적하지 않는다.** 실측에서 책갈피가 얕은 PDF 하나가
목록 항목을 1개만 내놨고(SKN56 CDMS Rev05), 그 상태로 대조하면 멀쩡한 인용
일곱 건이 전부 "목록에 없는 문서"로 뜬다 — 잴 자를 못 읽고 재는 꼴이다.
"""
from __future__ import annotations

import re

from modules.shared import Anchor, Context, Document, Evidence, Finding, Severity

#: 참조 절 제목. `References` 로 끝나거나 `참조문서` 를 담은 절.
#: `Reference Manual` 같은 문서 제목이 걸리지 않게 끝을 묶는다.
_REF_TITLE = re.compile(r"(references?|참조\s*문헌|참조\s*문서)\s*$", re.IGNORECASE)

#: 절 번호. `3.1.1 NUREG-0800, ...` → `3.1.1`
_SECTION_NO = re.compile(r"^(\d+(?:\.\d+)*)\s")

#: 본문 인용. `(reference 3.2.1)` · `references 3.3.4` · `참조 3.1.2`
_CITATION = re.compile(r"(?:references?|참조)\s*(\d+(?:\.\d+)+)", re.IGNORECASE)

#: 이보다 항목이 적으면 목록을 못 읽은 것으로 본다. 실측에서 책갈피가 얕은 PDF 가
#: 1개를 냈고, 정상 문서는 19~30개였다. 둘 사이에 실제 값이 없어 2 로 둔다.
_MIN_ENTRIES = 2

_MAX_LISTED = 20


def _head(number: str) -> str:
    """`3.0` → `3` · `1.4` → `1.4`. 하위 절을 찾을 때 쓸 앞자리."""
    parts = number.split(".")
    while len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return ".".join(parts)


class RefListChecker:
    """참조문서 목록 ↔ 본문 인용 대조.

    name 은 `PlaceholderChecker` 와 같은 `completeness` 다 — 리포트에서 형식·완전성
    묶음으로 모인다.
    """

    name = "completeness"
    label = "참조문서 목록 대조"

    def __init__(self, sections: tuple[str, ...] = ()) -> None:
        # 제목이 위 기본형과 다른 팀을 위한 구멍. 비면 기본형을 쓴다.
        self.sections = tuple(sections)

    def _is_ref_title(self, title: str) -> bool:
        text = (title or "").strip()
        if self.sections:
            return any(k.lower() in text.lower() for k in self.sections)
        return bool(_REF_TITLE.search(text))

    def check(self, doc: Document, ctx: Context | None = None) -> list[Finding]:
        sections = list(doc.iter_sections())
        ref_secs = [s for s in sections if self._is_ref_title(s.title or "")]
        if not ref_secs:
            return [self._unreviewed(
                "참조문서 절을 찾지 못해 참조문서 대조를 수행하지 않았습니다.",
                "이 문서에 참조문서 절이 정말 없으면 그대로 두세요. 있는데 못 찾은 "
                "것이면 기준 관리자에게 그 절 제목을 기준에 넣어 달라고 알려주세요"
                "(항목의 params.ref_sections).")]

        # 참조 절 아래에서 **더 깊은 절을 거느리지 않은** 번호만 항목으로 센다.
        # `3.0 References` · `3.1 Regulations` · `3.2 Codes and Standards` 는
        # 묶음이지 참조문서가 아니다 — 세면 아무도 인용하지 않으므로 늘 "미인용"
        # 으로 뜬다(실측에서 지적 17건 중 넷이 이 묶음 절이었다).
        #
        # 트리(section.children)가 아니라 **번호**로 가린다. PDF 는 책갈피 깊이가
        # 문서마다 들쭉날쭉해서, 같은 구조가 어디서는 부모-자식이고 어디서는
        # 형제로 들어온다. 번호는 그 영향을 안 받는다.
        numbered: dict[str, object] = {}
        for s in sections:
            sm = _SECTION_NO.match((s.title or "").strip() + " ")
            if sm is not None:
                numbered.setdefault(sm.group(1), s)

        def _is_container(number: str) -> bool:
            return any(other.startswith(number + ".") for other in numbered)

        entries: dict[str, Anchor] = {}
        for ref in ref_secs:
            m = _SECTION_NO.match((ref.title or "").strip() + " ")
            if m is None:
                continue
            base = _head(m.group(1)) + "."
            for number, s in numbered.items():
                if number.startswith(base) and not _is_container(number):
                    entries.setdefault(number, s.anchor)
        # 참조 절 자체는 언제나 묶음이다 — `3.0` 은 `3.` 으로 시작하므로 위
        # 반복에 걸린다. 번호가 `3` 처럼 하위를 안 거느린 모양이면 걸러지지 않는다.
        for ref in ref_secs:
            m = _SECTION_NO.match((ref.title or "").strip() + " ")
            if m is not None:
                entries.pop(m.group(1), None)

        if len(entries) < _MIN_ENTRIES:
            return [self._unreviewed(
                f"참조문서 목록을 {len(entries)}건밖에 읽지 못해 대조하지 않았습니다.",
                "PDF 라면 책갈피가 참조 절 아래까지 있는지 확인하세요.")]

        cited: dict[str, Anchor] = {}
        for s in sections:
            for number in _CITATION.findall(s.text or ""):
                cited.setdefault(number, s.anchor)

        findings: list[Finding] = []
        # 문서의 다른 절을 가리키는 상호참조는 참조문서 인용이 아니다. 실측(SHN34
        # RVVR)에서 `1.4.3.1` 을 가리키는 상호참조 네 건이 "목록에 없는 문서" 로 떴다.
        unknown = {n: a for n, a in cited.items()
                   if n not in entries and n not in numbered}
        if unknown:
            findings.append(self._listed(
                unknown, Severity.MAJOR,
                f"본문이 참조문서 목록에 없는 항목 {len(unknown)}건을 인용합니다",
                "인용한 문서를 참조문서 목록에 추가하거나, 인용 번호를 고치세요."))
        unused = {n: a for n, a in entries.items() if n not in cited}
        if unused:
            findings.append(self._listed(
                unused, Severity.MINOR,
                f"참조문서 목록의 {len(unused)}건이 본문에서 인용되지 않습니다",
                "본문에서 쓰지 않는 참조문서는 목록에서 지웁니다."))
        return findings

    def _listed(self, items: dict, severity: Severity, message: str,
                suggestion: str) -> Finding:
        """번호 여럿을 한 건으로. 낱개로 내면 문서 하나에서 열일곱 건이 쏟아진다."""
        numbers = sorted(items, key=lambda n: [int(p) for p in n.split(".")])
        shown = ", ".join(numbers[:_MAX_LISTED])
        if len(numbers) > _MAX_LISTED:
            shown += f" 외 {len(numbers) - _MAX_LISTED}건"
        return Finding(
            checker=self.name,
            severity=severity,
            message=f"{message} — {shown}",
            anchor=items[numbers[0]],
            suggestion=suggestion,
            evidence=[Evidence(anchor=items[n], quote=n) for n in numbers],
        )

    def _unreviewed(self, message: str, suggestion: str) -> Finding:
        return Finding(
            checker=self.name,
            severity=Severity.INFO,
            message=message,
            anchor=Anchor(page=None, section=None),
            suggestion=suggestion,
            unreviewed=True,
        )
