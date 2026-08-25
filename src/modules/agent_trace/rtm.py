"""추적성 매트릭스(RTM) 빌더.

TraceabilityChecker가 "예외(누락/근거없음)"만 내는 데 반해, 여기서는
연결된 항목까지 포함한 전체 대조표를 만든다. LLM 없이 결정적으로 동작한다.
"""
from __future__ import annotations

import re

from modules.shared import Document, RtmRow
from .idref import extract_id_anchors


def in_scope(_id: str, scope_pattern: str) -> bool:
    """이 상위 요건이 하위문서의 책임 범위에 드는가.

    scope_pattern이 비면 전부 범위 안이다(기존 동작).
    """
    if not scope_pattern:
        return True
    return re.search(scope_pattern, _id) is not None


def rollup_parent(_id: str, separator: str) -> str | None:
    """하위요건 ID의 부모 ID. 한 단계만 접는다.

    상위문서가 요건을 더 잘게 쪼개 쓰고(FR-CCG_01_01) 하위문서는 부모 수준
    (FR-CCG_01)에서만 검증하는 문서쌍이 있다. 실측(SHN34 SRS↔RVVR): 누락
    54건 중 46건이 이것이었고 46건 **전부** 부모 ID가 하위문서에 있었다.

    끝까지 접지 않는 이유: FR-CCG_01 을 또 접으면 FR-CCG 가 되는데 이건 ID가
    아니다. 한 단계만 접고, 그 결과가 하위문서에 실재할 때만 연결로 본다 —
    그래서 없는 부모를 지어내 진짜 누락을 덮는 일이 없다.

    separator 가 비면 끈다. 접는 규칙은 문서마다 다르므로 체크리스트가 정한다.
    """
    if not separator or separator not in _id:
        return None
    return _id.rsplit(separator, 1)[0] or None


def build_rtm(parent: Document, child: Document, pattern: str,
              scope_pattern: str = "",
              rollup_separator: str = "") -> list[RtmRow]:
    """상위·하위 문서를 ID로 대조해 전체 RTM 행 목록을 만든다.

    상위 문서 순서대로 linked/missing/out_of_scope 행을 만들고, 하위에만 있는
    ID를 orphan 행으로 뒤에 붙인다.

    범위 밖 요건은 "누락"이 아니다. 부분 설계서는 원래 남의 요건을 다루지
    않는다. 그렇다고 지우지도 않는다 — 진짜 누락이 거기 묻힐 수 있으므로
    out_of_scope로 남겨 세어 보여준다.
    """
    if not pattern:
        return []
    parent_ids = extract_id_anchors(parent, pattern)
    child_ids = extract_id_anchors(child, pattern)

    # 접힌 상대(하위문서의 부모 ID). 이걸 기억하지 않으면 아래 orphan 루프가
    # 그 부모 ID를 "근거없음"이라 부른다 — 오탐을 반대편으로 옮길 뿐이다.
    rolled: set[str] = set()

    rows: list[RtmRow] = []
    for _id, anchor in parent_ids.items():
        up = rollup_parent(_id, rollup_separator)
        if _id in child_ids:
            status, lower = "linked", [_id]
        elif up and up in child_ids:
            # 하위문서가 부모 수준에서 검증했다. 누락이 아니지만 연결도 아니다 —
            # 세부 요건이 개별로 검증됐는지는 사람이 봐야 한다. 그래서 따로 센다.
            status, lower = "rolled_up", [up]
            rolled.add(up)
        elif not in_scope(_id, scope_pattern):
            status, lower = "out_of_scope", []
        else:
            status, lower = "missing", []
        rows.append(RtmRow(upper_id=_id, lower_ids=lower,
                           status=status, anchor=anchor))
    for _id, anchor in child_ids.items():
        if _id not in parent_ids and _id not in rolled:
            rows.append(RtmRow(upper_id=None, lower_ids=[_id],
                               status="orphan", anchor=anchor))
    return rows
