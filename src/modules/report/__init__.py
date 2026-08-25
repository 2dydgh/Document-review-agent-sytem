"""report — Finding → 렌더(md/json)·엑셀·형광펜 PDF·통계·진행단계.

다른 모듈은 이 공개 인터페이스만 쓴다.
"""
from __future__ import annotations

from .annotate_pdf import Marked, annotate, locate
from .collector import collect, merge_duplicates, stamp
from .pdf_summary import FontMissing, find_font, number_overlay, summary_pdf
from .renderers import (
    render_json,
    render_markdown,
    render_rtm_json,
    render_rtm_markdown,
)
from .stages import (
    REVIEW_DETAIL,
    REVIEW_STAGES,
    fmt_chars,
    fmt_chunks,
    fmt_findings,
    fmt_sections,
    review_stages,
)
from .ui_export import (
    render_review_ui_js,
    render_ui_js,
    to_ui_checklist_review_payload,
    to_ui_criteria_review_payload,
    to_ui_payload,
    to_ui_review_payload,
)

__all__ = [
    "collect",
    "merge_duplicates",
    "stamp",
    "render_markdown",
    "render_json",
    "render_rtm_markdown",
    "render_rtm_json",
    "to_ui_payload",
    "to_ui_review_payload",
    "to_ui_checklist_review_payload",
    "to_ui_criteria_review_payload",
    "render_ui_js",
    "render_review_ui_js",
    "REVIEW_DETAIL",
    "REVIEW_STAGES",
    "review_stages",
    "fmt_chars",
    "fmt_chunks",
    "fmt_findings",
    "fmt_sections",
    "annotate",
    "locate",
    "Marked",
    "FontMissing",
    "find_font",
    "number_overlay",
    "summary_pdf",
]
