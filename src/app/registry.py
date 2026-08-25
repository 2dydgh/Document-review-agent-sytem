"""기본 체커 등록."""
from __future__ import annotations

from collections.abc import Sequence

from modules.shared import Checker


def default_checkers(criteria: Sequence = (),
                     doc_max_chars: int = 120_000) -> list[Checker]:
    """체크리스트를 안 고른 일반 검토의 검사기.

    ChunkCriteriaChecker 는 기준을 받아야 무엇이든 검사한다 — 기준 없이 만들면
    조용히 0건을 내고, 그건 "검사했더니 이상 없음"과 구분되지 않는다. 그래서
    호출부가 공통 기준을 주입한다(주지 않으면 표현 점검이 아예 안 돈다).

    """
    from modules.agent_checklist import checkers_for  # noqa: PLC0415

    # 라우팅은 한 곳(checkers_for)에서만 한다 — 여기서 agent 라벨을 다시 보면
    # 체크리스트 경로와 규칙이 갈린다.
    return list(checkers_for(criteria, doc_max_chars=doc_max_chars))
