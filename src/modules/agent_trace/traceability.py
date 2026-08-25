"""규칙기반 체커: 두 문서 간 ID 추적성 검사.

doc=상위문서(parent), ctx.other=하위문서(child).
- 상위 ID가 하위에 없음 → 누락 (document="parent")
- 하위 ID가 상위에 없음 → 근거없음/orphan (document="child")
LLM 없이 결정적으로 동작한다(환각 방지).
"""
from __future__ import annotations

from modules.shared import Anchor, Document, Finding, Severity
from modules.shared import Context
from .idref import extract_id_anchors
from .rtm import in_scope, rollup_parent


class TraceabilityChecker:
    name = "traceability"
    label = "요건 ID 추적"

    def check(self, doc: Document, ctx: Context) -> list[Finding]:
        pattern = getattr(ctx.review, "id_pattern", "")
        scope = getattr(ctx.review, "scope_pattern", "")
        child = ctx.other
        if child is None:
            return []
        if not pattern:
            # 두 문서를 받았는데 잴 자가 없다. 여기서 조용히 0건을 내면 "대조해
            # 봤더니 다 맞더라"로 읽힌다 — 아래 "ID를 한 건도 못 찾음"과 같은 처방.
            return [Finding(
                checker=self.name,
                severity=Severity.INFO,
                message=("요건 ID 형식이 검토 기준에 없어 추적성 검사를 "
                         "수행하지 않았습니다."),
                anchor=Anchor(page=None, section=None),
                suggestion=("검토자가 할 일은 아닙니다 — 기준 관리자에게 이 문서의 "
                            "요건 ID 형식을 기준에 넣어 달라고 알려주세요"
                            "(항목의 params.id_pattern)."),
                unreviewed=True,
            )]
        parent_ids = extract_id_anchors(doc, pattern)
        child_ids = extract_id_anchors(child, pattern)

        if not parent_ids or not child_ids:
            # 한쪽이라도 ID가 0건이면 대조 자체가 성립하지 않는다. "지적사항 없음"이
            # 아니라 "검토를 못 했음"이다. 수정 2026-08-06: 예전엔 양쪽 다 0건일 때만
            # 여기로 빠져서, 하위문서만 0건이면(책갈피 없는 PDF·패턴 불일치) 상위 ID
            # 전부가 MAJOR "누락"으로 쏟아지는 오탐 폭주가 있었다 — RefListChecker 의
            # _MIN_ENTRIES 가드와 같은 처방을 여기도 적용한다.
            side = ("양쪽 문서" if not parent_ids and not child_ids
                    else "하위문서" if not child_ids else "상위문서")
            return [Finding(
                checker=self.name,
                severity=Severity.INFO,
                message=(f"{side}에서 요건 ID를 한 건도 찾지 못했습니다 "
                         f"(패턴: {pattern}). 추적성 검사가 수행되지 않았습니다."),
                anchor=Anchor(page=None, section=None),
                suggestion="체크리스트의 id_pattern이 이 문서의 ID 형식과 맞는지 확인하세요.",
                unreviewed=True,
            )]

        rollup = getattr(ctx.review, "id_rollup_separator", "")
        # 접힌 상대(하위문서의 부모 ID)는 근거없음이 아니다. 아래 orphan 루프가
        # 참조한다 — 안 그러면 오탐이 누락에서 근거없음으로 옮겨갈 뿐이다.
        rolled: set[str] = set()

        findings: list[Finding] = []
        for _id, anchor in parent_ids.items():
            if _id in child_ids:
                continue
            up = rollup_parent(_id, rollup)
            if up and up in child_ids:
                # 하위문서가 부모 수준에서 검증했다. 누락이 아니다.
                # (사라지지는 않는다 — RTM에 rolled_up으로 남아 개수가 보인다)
                rolled.add(up)
                continue
            # 범위 밖 요건은 하위문서의 책임이 아니다. 지적하면 소음이 된다.
            # (그래도 사라지지는 않는다 — RTM에 out_of_scope로 남아 개수가 보인다)
            if in_scope(_id, scope):
                findings.append(Finding(
                    checker=self.name,
                    severity=Severity.MAJOR,
                    message=f"하위문서에 누락된 ID: {_id}",
                    anchor=anchor,
                    suggestion=(f"'{_id}'를 하위문서에 반영하거나, "
                                "논의로 삭제된 항목이면 상위문서에서 제거하세요."),
                    document="parent",
                ))
        for _id, anchor in child_ids.items():
            if _id not in parent_ids and _id not in rolled:
                findings.append(Finding(
                    checker=self.name,
                    severity=Severity.MAJOR,
                    message=f"상위문서에 근거 없는 ID: {_id}",
                    anchor=anchor,
                    suggestion=(f"'{_id}'의 근거를 상위문서에 추가하거나, "
                                "오타/삭제잔재면 하위문서에서 정리하세요."),
                    document="child",
                ))
        return findings
