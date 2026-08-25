"""agent_history — 검토 의견·이력 관리. 문서 계보와 반영 확인 (순수 규칙)."""
from __future__ import annotations

from .lineage import (
    CARRIED,
    DEFAULT_VERDICT,
    KEY_SEP,
    LEGACY,
    OBSERVED,
    STATUSES,
    LineageItem,
    LineageReview,
    carry_verdicts,
    find_prior,
    guess_original_name,
    incomplete_checkers,
    is_process_report,
    match_findings,
    verdict_key,
)

__all__ = [
    "CARRIED",
    "KEY_SEP",
    # 기계가 본 것(OBSERVED)과 사람이 내린 판정(STATUSES)은 다른 축이다.
    "OBSERVED",
    "STATUSES",
    "DEFAULT_VERDICT",
    "LEGACY",
    "LineageItem",
    "LineageReview",
    "carry_verdicts",
    "find_prior",
    "guess_original_name",
    "incomplete_checkers",
    "is_process_report",
    "match_findings",
    "verdict_key",
]
