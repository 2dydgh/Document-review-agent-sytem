"""공통 타입·계약 — 모든 모듈이 여기서 Finding·Document·Checker 등을 가져온다.

다른 모듈은 이 공개 인터페이스만 쓴다(내부 파일 직접 import 금지).
"""
from __future__ import annotations  # noqa: I001

# 도메인 모델 (먼저 바인딩 — 하위 agent가 config 경유로 이 이름들을 참조할 수 있어 순서 유지)
from .models import (
    Anchor,
    Chunk,
    Document,
    Evidence,
    Finding,
    RtmRow,
    Section,
    Severity,
)
from .config import Config, ReviewConfig
from .checker import Checker, Context
from .suggest import Suggestion, suggest_revision
# LLM 응답 파서와 근거 재확인용 문서 조회 도구.
from .agent.parsing import _parse
from .agent.tools import DocTools
from .agent.verify import _is_substantive, _norm, verify_quotes

__all__ = [
    "Anchor",
    "Checker",
    "Chunk",
    "Config",
    "Context",
    "DocTools",
    "Document",
    "Evidence",
    "Finding",
    "ReviewConfig",
    "RtmRow",
    "Section",
    "Severity",
    "Suggestion",
    "_is_substantive",
    "_norm",
    "_parse",
    "suggest_revision",
    "verify_quotes",
]
