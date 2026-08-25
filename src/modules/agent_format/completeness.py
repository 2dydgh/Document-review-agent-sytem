"""규칙기반 체커: 필수 절 검사.

번호가 붙은 항목("1.0 Purpose")은 **번호로 절을 찾고 제목을 대조한다.**
실문서를 재보니 번호는 안정적인데 제목 표현이 흔들렸다 — 두 RVVR 이 4.0 을
각각 "Definitions and Abbreviations" 와 "Definition of Terms" 로 적었다.
정확 일치로 대조하면 후자가 "누락"으로 뜨는데 절은 분명히 있다.

그래서 둘을 나눈다:
  · 절이 없다              → MAJOR (문자열 대조로 확실하다)
  · 절은 있는데 제목이 다르다 → MINOR (의도적 변형일 수 있어 사람이 볼 일이다)

번호가 없는 항목("개요")은 예전처럼 정확 일치다. 번호를 안 쓰는 문서
(한국어 docx 의 "목적"·"범위")가 실재하므로 그 경로를 유지한다.
"""
from __future__ import annotations

import re

from modules.shared import Anchor, Document, Evidence, Finding, Section, Severity
from modules.shared import Context

# "1.0 Purpose" -> ("1.0", "Purpose"). 번호는 1.0 / 3.2 / 3.1.1 형태를 받는다.
_NUMBERED = re.compile(r"^\s*(\d+(?:\.\d+)*)\s+(.*\S)\s*$")


def _split(entry: str) -> tuple[str, str] | None:
    """required 항목을 (번호, 제목)으로. 번호가 없으면 None."""
    m = _NUMBERED.match(entry or "")
    return (m.group(1), m.group(2)) if m else None


def _norm(text: str) -> str:
    """공백만 누른다. 대소문자는 구분한다 — 표기 통일이 검사 목적이다.

    PDF 추출은 자간 때문에 공백을 흘리므로("Definitions  and") 공백 차이로
    지적하면 소음이 된다. verify_quotes 와 같은 규칙이다.
    """
    return " ".join(str(text or "").split())


def _find(number: str, sections: list[Section]) -> Section | None:
    """그 번호로 시작하는 절. 번호 뒤에 공백을 요구해 3.1 이 3.1.1 을 집지 않게 한다."""
    rx = re.compile(rf"^\s*{re.escape(number)}\s+")
    for s in sections:
        if rx.match(s.title or ""):
            return s
    return None


# 문서에 번호가 붙은 절이 하나라도 있는가. "1쪽"·"2쪽"은 여기 걸리지 않는다.
_ANY_NUMBER = re.compile(r"^\s*\d+(?:\.\d+)*\s+\S")


def _has_numbered(sections: list[Section]) -> bool:
    return any(_ANY_NUMBER.match(s.title or "") for s in sections)


class CompletenessChecker:
    name = "completeness"
    label = "필수 항목 확인"

    def check(self, doc: Document, ctx: Context) -> list[Finding]:
        required = list(getattr(ctx.review, "required_sections", []))
        if not required:
            # 필수 절 목록을 아무 기준도 안 적어줬다. 조용한 0건은 "필수 절이 다
            # 있더라"로 읽힌다 — 아래 blind 처방과 같은 이유로 못 했다고 말한다.
            return [Finding(
                checker=self.name,
                severity=Severity.INFO,
                message=("필수 절 목록이 검토 기준에 없어 필수 절 검사를 "
                         "수행하지 않았습니다."),
                anchor=Anchor(page=None, section=None),
                # 검토자가 화면에서 읽는 줄이다 — 문서를 보러 온 사람에게
                # yaml 편집을 시키면 안 된다. 할 사람을 먼저 말하고, 무엇을
                # 고치는지는 그 사람이 알아볼 만큼만 남긴다.
                suggestion=("검토자가 할 일은 아닙니다 — 기준 관리자에게 이 문서에 "
                            "반드시 있어야 할 절 목록을 기준에 넣어 달라고 알려주세요"
                            "(항목의 params.required_sections)."),
                unreviewed=True,
            )]

        sections = list(doc.iter_sections())
        titles = {_norm(s.title) for s in sections}
        findings: list[Finding] = []

        # 번호 요건이 있는데 문서에 번호 절이 하나도 없으면, 그 요건들은 잴 수가
        # 없다. 전부 "누락"으로 내면 검토를 못 한 것을 결함으로 위장하게 된다.
        # TraceabilityChecker 가 요건 ID 를 못 찾았을 때와 같은 처방이다.
        numbered = [e for e in required if _split(e) is not None]
        blind = bool(numbered) and not _has_numbered(sections)
        if blind:
            findings.append(Finding(
                checker=self.name,
                severity=Severity.INFO,
                message=("이 문서에서 번호가 붙은 절을 찾지 못해 필수 절 검사를 "
                         "수행하지 않았습니다. PDF 라면 책갈피가 없는 문서일 수 "
                         "있습니다."),
                anchor=Anchor(page=None, section=None),
                suggestion="원본에 책갈피가 있는지 확인하세요.",
            ))

        for entry in required:
            parts = _split(entry)

            if parts is None:
                # 번호 없는 항목 — 예전 그대로 정확 일치.
                if _norm(entry) not in titles:
                    findings.append(self._missing(entry))
                continue

            if blind:
                continue  # 위에서 한 번 알렸다. 요건 수만큼 반복하지 않는다.

            number, want = parts
            found = _find(number, sections)
            if found is None:
                findings.append(self._missing(entry))
                continue

            # 번호는 이미 _find 가 맞췄다. 제목 부분만 떼어 비교하고 보여준다 —
            # 통째로 쓰면 "4.0 '4.0 Definition of Terms'" 로 번호가 겹쳐 보인다.
            found_parts = _split(found.title)
            got = _norm(found_parts[1]) if found_parts else _norm(found.title)
            if got == _norm(want):
                continue

            # 절은 있는데 제목이 다르다. 누락이 아니다.
            findings.append(Finding(
                checker=self.name,
                severity=Severity.MINOR,
                message=(f"절 제목이 표준과 다릅니다: {number} "
                         f"'{got}' (표준: '{want}')"),
                anchor=found.anchor,
                # 실제 제목 줄을 근거로 단다 — 근거 없는 지적은 형광펜·번호가 안
                # 붙어 카드에서 그 자리로 갈 수 없었다(사용자 보고 2026-08-14).
                # 제목은 문서에서 읽은 값이라 인용 계약(원문 실재)을 그대로 지킨다.
                evidence=[Evidence(anchor=found.anchor, quote=found.title)],
                suggestion=f"제목을 '{entry}' 로 맞추거나, 의도한 변경이면 그대로 두세요.",
            ))

        return findings

    def _missing(self, entry: str) -> Finding:
        return Finding(
            checker=self.name,
            severity=Severity.MAJOR,
            message=f"필수 항목 누락: {entry}",
            anchor=Anchor(page=None, section=None),
            suggestion=f"'{entry}' 섹션을 추가하세요.",
        )
