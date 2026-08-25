"""규칙기반 체커: 미완성 표시(TBD 등) 검사.

배포된 문서에 남은 자리표시자를 찾는다. LLM 없이 결정적으로 동작하고,
문자열 대조라 오탐이 없다.

기본 표시는 `TBD` 하나뿐이다. 실제 문서 세 개를 재보니 `미정`·`N/A`·`작성중`은
한 번도 안 나왔고, `추후`는 본문 산문("추후 경량화에 따라 변경될 수 있음")에
섞여 있어 넣으면 오탐이 된다. 필요하면 체크리스트에서 늘린다.
"""
from __future__ import annotations

import re
from collections import Counter

from modules.shared import Document, Finding, Severity
from modules.shared import Context

DEFAULT_MARKERS = ("TBD",)

_MAX_QUOTE = 80


def _as_pattern(marker: str) -> str:
    """마커 하나를 정규식 조각으로.

    영문 마커에만 단어 경계를 준다("TBDX-1"을 지적하지 않기 위함). 한글에는
    쓸 수 없다 — `\\b`는 \\w 사이에 경계를 만들지 않아 "미정이다"의 "미정"이
    매칭되지 않는다.
    """
    escaped = re.escape(marker)
    if marker.isascii():
        return rf"\b{escaped}\b"
    return escaped


def _compile(markers: list[str]) -> re.Pattern | None:
    if not markers:
        return None
    return re.compile("|".join(_as_pattern(m) for m in markers), re.IGNORECASE)


class PlaceholderChecker:
    name = "completeness"
    label = "미작성 표시 검사"

    def __init__(self, document: str | None = None) -> None:
        # 2문서 비교에서 어느 쪽 문서의 문제인지 표시할 때 쓴다.
        self.document = document

    def check(self, doc: Document, ctx: Context) -> list[Finding]:
        markers = list(getattr(ctx.review, "placeholder_markers", DEFAULT_MARKERS))
        rx = _compile(markers)
        if rx is None:
            return []

        findings: list[Finding] = []
        for section in doc.iter_sections():
            # 같은 절에 똑같은 줄이 여러 번 나온다(표에 빈 행이 반복되는 경우).
            # 그대로 두면 collect()가 중복으로 합쳐 개수가 조용히 줄어든다.
            # 하나로 묶되 몇 번인지 밝힌다.
            hits = Counter(
                line.strip() for line in section.text.splitlines()
                if line.strip() and rx.search(line))
            for line, count in hits.items():
                quote = line if len(line) <= _MAX_QUOTE else line[:_MAX_QUOTE] + "…"
                repeat = f" (이 절에 {count}회)" if count > 1 else ""
                findings.append(Finding(
                    checker=self.name,
                    severity=Severity.MAJOR,
                    message=f"미완성 표시가 남아 있습니다{repeat}: {quote}",
                    anchor=section.anchor,
                    suggestion="내용을 채우거나, 확정 전이면 언제까지 정할지 명시하세요.",
                    document=self.document,
                ))
        return findings
