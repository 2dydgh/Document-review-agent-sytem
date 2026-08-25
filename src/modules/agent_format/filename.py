"""규칙기반 체커: 제출 파일명 검사.

두 팀이 같은 것을 요구했다(EV2 19 · EV3 13). 파일명 규칙은 팀마다 다르므로
**코드가 형식을 정하지 않는다** — 기준이 정규식으로 적어 주면 그것으로 잰다.

EV3 는 규칙을 예시까지 적어 두었다:

    Z11008-940VD-011C_Rev.08_RVVR for ESF-CCS for SKN56
    계통문서번호_버전_문서명

EV2 는 "내부 규칙에 맞게"까지만 적혀 있고 그 규칙이 문서에 없다. 그런 팀에서는
검사가 돌지 않고 **그 사실을 남긴다** — 조용히 0건을 내면 파일명을 검사해 봤더니
이상이 없는 것으로 읽힌다.

확장자는 빼고 잰다. 규칙을 적는 사람은 이름을 말하지 확장자를 말하지 않고,
실제로 EV3 의 예시에도 확장자가 없다.
"""
from __future__ import annotations

import re
from pathlib import Path

from modules.shared import Anchor, Context, Document, Finding, Severity


class FilenameChecker:
    """파일명이 팀 규칙에 맞는가.

    name 은 `PlaceholderChecker` 와 같은 `completeness` 다 — 리포트에서 형식·완전성
    묶음으로 모인다.
    """

    name = "completeness"
    label = "파일명 규칙 검사"

    def __init__(self, pattern: str = "", example: str = "",
                 forbidden: tuple[str, ...] = ()) -> None:
        self.pattern = pattern
        self.example = example
        self.forbidden = tuple(forbidden)

    def check(self, doc: Document, ctx: Context | None = None) -> list[Finding]:
        stem = Path(doc.source_path).stem
        if not (self.pattern or self.forbidden):
            return [self._unreviewed(
                "파일명 규칙이 검토 기준에 없어 파일명 검사를 수행하지 않았습니다.",
                "검토자가 할 일은 아닙니다 — 기준 관리자에게 이 팀의 파일명 규칙을 "
                "기준에 넣어 달라고 알려주세요(항목의 params.filename_pattern).")]

        try:
            compiled = re.compile(self.pattern) if self.pattern else None
        except re.error as exc:
            # 정규식이 깨졌으면 "맞지 않는다"가 아니라 "재지 못했다"다. 지적으로
            # 내면 멀쩡한 파일명이 전부 틀린 것으로 뜬다.
            return [self._unreviewed(
                f"파일명 규칙의 정규식이 올바르지 않아 검사하지 못했습니다: {exc}",
                "검토 기준의 filename_pattern 을 고치세요.")]

        findings: list[Finding] = []
        if compiled is not None and not compiled.fullmatch(stem):
            want = f" (예: {self.example})" if self.example else ""
            findings.append(Finding(
                checker=self.name,
                severity=Severity.MAJOR,
                message=f"파일명이 규칙과 다릅니다: '{stem}'{want}",
                anchor=Anchor(page=None, section=None),
                suggestion="파일명의 구성요소와 순서·구분자를 규칙에 맞추세요.",
            ))
        for marker in self.forbidden:
            if marker and marker.lower() in stem.lower():
                findings.append(Finding(
                    checker=self.name,
                    severity=Severity.MINOR,
                    message=f"파일명에 '{marker}' 가 남아 있습니다: '{stem}'",
                    anchor=Anchor(page=None, section=None),
                    suggestion="임시본·복사본 표시를 지우고 제출본 이름으로 바꾸세요.",
                ))
        return findings

    def _unreviewed(self, message: str, suggestion: str) -> Finding:
        return Finding(
            checker=self.name,
            severity=Severity.INFO,
            message=message,
            anchor=Anchor(page=None, section=None),
            suggestion=suggestion,
            unreviewed=True,
        )
