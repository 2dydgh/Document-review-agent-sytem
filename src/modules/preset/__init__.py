"""preset — 팀 기준·체크리스트를 로드·파싱·저장·내보내기.

체크리스트 표(xlsx/csv/pdf) → Criterion, 검토 결과 저장, CSV 내보내기.
도메인 데이터는 presets/ 에 두고 주입한다. 다른 모듈은 이 공개 인터페이스만 쓴다.
"""
from __future__ import annotations

from .export import to_csv
from .classify import Classification, classify_output
from .library import (compose_review_preset, load_presets, resolve_criteria,
                      save_seed_items)
from .models import AGENTS, MODES, SCOPES, VERDICTS, Criterion, Preset
from .parse import (
    UnsupportedChecklistFormat,
    build_items,
    extract_tables,
    find_header,
    guess_columns,
)
from .store import ChecklistError, ChecklistStore

__all__ = [
    "Preset",
    "Criterion",
    "VERDICTS",
    "AGENTS",
    "MODES",
    "SCOPES",
    "Classification",
    "classify_output",
    "load_presets",
    "save_seed_items",
    "resolve_criteria",
    "compose_review_preset",
    "build_items",
    "find_header",
    "guess_columns",
    "extract_tables",
    "UnsupportedChecklistFormat",
    "ChecklistStore",
    "ChecklistError",
    "to_csv",
]
