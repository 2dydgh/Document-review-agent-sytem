"""agent_quality — 표현·내용 품질 검사 (LLM). 기준 본문을 프롬프트에 싣는다.

검사 단위가 둘이다. 조각(ChunkCriteriaChecker)은 문서를 청크로 잘라 조각마다
묻고, 문서 전체(WholeDocCriteriaChecker)는 통째로 한 번 묻는다 — 멀리 떨어진 두 곳을
맞대야 하는 기준은 조각으로는 원리상 못 잡는다.
"""
from __future__ import annotations

from .consistency import (
    ChunkCriteriaChecker,
    ConsistencyChecker,
    WholeDocChecker,
    WholeDocCriteriaChecker,
)

__all__ = [
    "ChunkCriteriaChecker",
    "WholeDocCriteriaChecker",
    # 하위 호환 별칭. 새 코드는 위 이름을 사용한다.
    "ConsistencyChecker",
    "WholeDocChecker",
]
