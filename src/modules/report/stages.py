"""파이프라인 단계 정의와 detail 문구.

진행 이벤트(SSE)와 최종 UI payload가 같은 값을 다르게 적으면("6,180 chars" vs
"6180 chars") 화면이 스스로 모순된다. 문구를 만드는 곳은 여기 하나뿐이다.
"""
from __future__ import annotations

REVIEW_STAGES: list[dict] = [
    {"key": "ingestion", "label": "Ingestion", "desc": "원문 적재"},
    {"key": "normalize", "label": "Normalize", "desc": "heading을 섹션 트리로 정규화"},
    {"key": "chunking", "label": "Chunking", "desc": "섹션을 검토 단위로 분할"},
    {"key": "review", "label": "Review", "desc": "규칙기반 + LLM 체커 실행"},
    {"key": "report", "label": "Report", "desc": "중복 제거 · 심각도 정렬"},
]

# Review 단계는 셀 것이 없다. 무엇을 돌리는지만 말한다.
REVIEW_DETAIL = "completeness · consistency"


def fmt_chars(n: int) -> str:
    return f"{n:,} chars"


def fmt_sections(n: int) -> str:
    return f"{n} sections"


def fmt_chunks(n: int) -> str:
    return f"{n} chunks"


def fmt_findings(n: int) -> str:
    return f"{n} findings"


def review_stages(chars: int, sections: int, chunks: int,
                  n_findings: int) -> list[dict]:
    """검토가 끝난 뒤의 단계 목록. UI payload가 그대로 쓴다."""
    detail = {
        "ingestion": fmt_chars(chars),
        "normalize": fmt_sections(sections),
        "chunking": fmt_chunks(chunks),
        "review": REVIEW_DETAIL,
        "report": fmt_findings(n_findings),
    }
    return [{**s, "detail": detail[s["key"]]} for s in REVIEW_STAGES]
