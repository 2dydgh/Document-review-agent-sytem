"""규칙기반 체커: 머릿말·꼬리말에 있어야 할 것이 있는가.

팀 기준이 이것을 요구한다:

    [AI시험인증1팀] 머릿말에 의뢰번호·성적서번호 · 꼬리말에 페이지·양식 번호
    [AX품질팀]      머릿말/꼬리말의 문서번호·버전이 파일명과 일치

그런데 **머릿말은 본문에 안 실린다.** 쪽마다 반복돼 일관성·중복 검사를 오염시키기
때문이다(app/parser_bridge.py). 본문에서 빼는 것은 맞지만 통째로 버리면 이 기준을
볼 데이터가 없어진다 — 그래서 파서가 `meta["headers"]`·`["footers"]` 로 옮긴다.

## 무엇을 보나

기준이 `params` 로 **찾을 것**을 준다. 두 가지 모양이다:

    contains: ["의뢰번호", "성적서번호"]     이 말들이 머릿말에 있어야 한다
    pattern:  '페이지 \\( \\d+ \\)'          이 형식이 있어야 한다

`where: header | footer` 로 어느 쪽을 볼지 고른다(기본 header).

## 없을 때와 못 읽을 때를 가른다

머릿말이 **아예 없는 문서**와 **파서가 못 읽은 문서**는 다르다. 앞은 지적이고 뒤는
미검토다. 지금은 그 둘을 가를 방법이 없어(파서가 "머릿말이 없다"와 "못 읽었다"를
구별해 주지 않는다) **미검토로 둔다** — 없는 것을 있다고 하는 것보다, 못 봤다고
말하는 쪽이 안전하다. 파서가 그 구분을 주면 그때 지적으로 올린다.
"""
from __future__ import annotations

import re

from modules.shared import Anchor, Context, Document, Evidence, Finding, Severity


def _squash(text: str) -> str:
    """공백을 전부 지운 글자열. 띄어쓰기 차이로 대조가 어긋나는 것을 막는다."""
    return "".join(text.split())


class HeaderFooterChecker:
    """머릿말·꼬리말 내용 검사.

    name 은 `PlaceholderChecker` 와 같은 `completeness` 다 — 리포트에서 형식·완전성
    묶음으로 모인다.
    """

    name = "completeness"
    label = "머릿말·꼬리말 검사"

    def __init__(self, where: str = "header", contains: tuple[str, ...] = (),
                 pattern: str = "", message: str = "", rule_id: str = "") -> None:
        self.where = "footers" if str(where).startswith("foot") else "headers"
        self.contains = tuple(contains)
        self.pattern = pattern
        self.message = message
        self.rule_id = rule_id

    def check(self, doc: Document, ctx: Context | None = None) -> list[Finding]:
        label = "꼬리말" if self.where == "footers" else "머릿말"
        if not (self.contains or self.pattern):
            return [self._unreviewed(
                f"{label}에서 찾을 것이 검토 기준에 없어 검사를 수행하지 않았습니다.",
                "검토 기준 항목의 params 에 contains 또는 pattern 을 적으면 이 검사가 됩니다.")]

        lines = list(getattr(doc, "meta", {}).get(self.where) or ())
        if not lines:
            # 없는 것과 못 읽은 것을 가를 수 없다 — 모듈 머리말 참고.
            return [self._unreviewed(
                f"{label}을 읽지 못해 검사를 수행하지 않았습니다 "
                f"(파서가 {label} 을 싣지 못했거나 문서에 {label}이 없습니다).",
                f"문서에 {label}이 있는지 직접 확인하세요.")]

        joined = " ".join(lines)
        # **공백은 지우고 맞춘다.** 실측(제출물 확인증): 머릿말이 `의뢰 번호: SST-26-999`
        # 인데 기준은 `의뢰번호` 라고 적혀 있어 "없습니다"로 떴다 — 있는데 없다고 한
        # 것이다. 한국어 라벨은 문서마다 띄어쓰기가 갈리고(`의뢰번호`/`의뢰 번호`),
        # 그 차이는 이 검사가 볼 것이 아니다. 맞춤법은 공통 기준이 따로 본다.
        squashed = _squash(joined)
        out: list[Finding] = []
        # **라벨마다 카드를 내지 않는다.** 같은 머릿말을 보고 내린 판정이라 근거도
        # 똑같다 — 둘로 나누면 같은 머릿말 세 줄이 두 번 실려 인용 칩이 배로 는다
        # (실측: 제출물 확인증에서 칩이 1·2·3·4 로 떴다). 한 장에 모아 적는다.
        missing = [w for w in self.contains if _squash(w) not in squashed]
        if missing:
            out.append(self._missing(
                f"{label}에 {' · '.join(repr(w) for w in missing)} 이(가) 없습니다",
                lines))
        if self.pattern:
            try:
                rx = re.compile(self.pattern)
            except re.error as exc:
                return [self._unreviewed(
                    f"{label} 규칙의 정규식이 올바르지 않아 검사하지 못했습니다: {exc}",
                    "검토 기준의 pattern 을 고치세요.")]
            if not rx.search(joined):
                out.append(self._missing(
                    self.message or f"{label}이 요구된 형식과 다릅니다", lines))
        return out

    # ── Finding 만들기 ───────────────────────────────────────────────

    def _missing(self, message: str, lines: list[str]) -> Finding:
        anchor = Anchor(page=None, section=None)
        # 인용은 실제로 읽은 머릿말이다. "없다"는 지적이라 그 자리를 가리킬 수는
        # 없지만, **무엇을 보고 그렇게 판정했는지**는 보여줘야 검토자가 확인한다.
        #
        # `source` 를 적는 이유: 이 인용은 **본문에 없다**(파서가 meta 로 옮긴다).
        # 안 적으면 뷰어가 본문에서 같은 글자를 찾아 형광펜을 얹는다 — 실측에서
        # 머릿말의 `제출물 확인증` 이 본문 표의 같은 글자를 짚어, 문서 제목이
        # 지적받은 것처럼 보였다.
        where = "꼬리말" if self.where == "footers" else "머릿말"
        return Finding(
            checker=self.name, severity=Severity.MAJOR, message=message,
            anchor=anchor, rule_id=self.rule_id,
            suggestion="문서 서식의 머릿말·꼬리말을 팀 양식대로 채우세요.",
            evidence=[Evidence(anchor=anchor, quote=q, source=where)
                      for q in lines[:3]])

    def _unreviewed(self, message: str, suggestion: str) -> Finding:
        return Finding(
            checker=self.name, severity=Severity.INFO, unreviewed=True,
            message=message, anchor=Anchor(page=None, section=None),
            suggestion=suggestion, rule_id=self.rule_id)
