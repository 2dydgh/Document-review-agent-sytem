"""공통 문서 모델 (Common Document Model).

핵심 원칙: **하류(下流)는 이 블록이 어느 경로(pdf-inspector 직접추출 / PaddleOCR /
Docling / Qwen3-VL)에서 왔는지 몰라도 된다.** 소비자는 오직 `Block.type` 으로 처리한다.
`origin` 은 디버깅·품질추적용 메타데이터일 뿐, 하류 로직의 분기 근거가 되어선 안 된다.

PDF·Word·HWP 백엔드는 모두 이 DocumentModel 로 정규화되어 나온다.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# 블록 타입 (하류가 분기하는 유일한 키)
HEADING = "heading"
PARAGRAPH = "paragraph"
TABLE = "table"
FIGURE = "figure"
FORMULA = "formula"
CODE = "code"
FOOTNOTE = "footnote"  # 각주/미주 본문 — note_kind로 구분(HWP/HWPX 백엔드가 채움)

# 출처(provenance) — 메타데이터일 뿐, 하류 분기 금지
ORIGIN_TEXT = "text"      # pdf-inspector 직접추출 (또는 텍스트 엔진 폴백 게이트 시 pymupdf)
ORIGIN_OCR = "ocr"        # PaddleOCR
ORIGIN_DOCLING = "docling"
ORIGIN_VLM = "vlm"        # Qwen3-VL

# 문서 내 위치(본문/머리말/꼬리말) — origin 과 동일하게 메타데이터일 뿐, 하류 분기 금지.
# 소비자가 헤더·푸터를 본문과 분리해서 다루고 싶을 때 필터링 용도로만 쓴다.
# _FIRST/_EVEN 은 "첫 페이지 전용"/"짝수 페이지 전용" 정의가 실제로 켜져 있을 때만
# 쓰인다(문서/구역 설정이 꺼져 있으면 Word 가 그 정의를 무시하므로 애초에 안 만들어짐) —
# docx_backend.py 의 _header_footer_blocks 참조.
SECTION_BODY = "body"
SECTION_HEADER = "header"
SECTION_FOOTER = "footer"
SECTION_HEADER_FIRST = "header_first"
SECTION_FOOTER_FIRST = "footer_first"
SECTION_HEADER_EVEN = "header_even"
SECTION_FOOTER_EVEN = "footer_even"


@dataclass
class TableData:
    """표 블록의 구조 데이터.

    Docling 훅(docling_adapter.py)이 연결되면 여기 값들이 실제 표 구조(행/열/셀/중첩)로
    채워지고, 훅이 없으면 pdf_backend._markdown_to_blocks 가 pdf-inspector 마크다운
    파이프표(|a|b|)만 파싱해 detected_only=True 로 "구조 미확정" 신호를 남긴다.

    merges/nested_tables 는 docx_backend.py 가 python-docx 의 정확한 그리드 정보로부터
    직접 채우는 필드(Docling 은 span 불규칙성으로 nested 여부만 근사 추정하므로 비워둠).
    """
    rows: int
    cols: int
    # 정규화 격자 텍스트(병합 영역은 앵커 셀에만 값, 나머지는 "")
    cells: list[list[str]] = field(default_factory=list)
    nested: bool = False                                   # 셀 안에 표 존재
    detected_only: bool = False  # 구조 미복원(검출만) — Docling 필요 신호
    merges: list[dict[str, int]] = field(default_factory=list)
    # 1x1 초과 병합 영역만: [{"row","col","row_span","col_span"}] (row/col 은 앵커=좌상단 위치)
    nested_tables: list[dict[str, Any]] = field(default_factory=list)
    # 셀 안에 실제로 중첩된 표: [{"row","col","table": TableData}]
    # (row/col 은 호스트 셀의 앵커 위치)
    images: list[dict[str, Any]] = field(default_factory=list)
    # 셀 안에 실제로 존재하는 이미지: [{"row","col","figure": Block}]
    # (row/col 은 호스트 셀의 앵커 위치)


@dataclass
class Block:
    """공통 문서 모델의 최소 단위. pdf_backend.parse_pdf 가 pdf-inspector 마크다운·
    OCR 결과·Docling 구조를 전부 이 타입으로 정규화해 DocumentModel.blocks 에 쌓는다.
    하류 소비자는 origin(어디서 왔는지)이 아니라 type 으로만 분기해야 한다."""
    type: str                              # HEADING/PARAGRAPH/TABLE/FIGURE/FORMULA/CODE
    page: int                              # 0-indexed
    text: str | None = None
    bbox: list[float] | None = None     # [x0,y0,x1,y1] PDF pt, 없으면 None
    level: int | None = None            # heading 레벨
    table: TableData | None = None
    origin: str = ORIGIN_TEXT              # 메타데이터(하류 분기 금지)
    needs_semantic: bool = False           # 그림/다이어그램 의미해석(VLM) 대기 표시
    section: str = SECTION_BODY            # 메타데이터(하류 분기 금지) — body/header/footer
    note_kind: str | None = None        # type==FOOTNOTE일 때만: "footnote"/"endnote"

    def to_dict(self) -> dict[str, Any]:
        """report.py 가 채점용 JSON(data/out/*.json)으로 직렬화할 때 호출.
        값이 None 인 필드는 출력에서 빼서 결과 JSON을 간결하게 유지."""
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}


@dataclass
class DocumentModel:
    source: str                            # 파일명
    meta: dict[str, Any] = field(default_factory=dict)
    blocks: list[Block] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    # ---- 편의 접근자 (하류에서 타입별로만 소비) ----
    def by_type(self, t: str) -> list[Block]:
        """블록 타입(HEADING/PARAGRAPH/TABLE/...)으로 필터링. tables/figures 프로퍼티의 기반."""
        return [b for b in self.blocks if b.type == t]

    @property
    def tables(self) -> list[Block]:
        return self.by_type(TABLE)

    @property
    def figures(self) -> list[Block]:
        return self.by_type(FIGURE)

    @property
    def text(self) -> str:
        """읽기 순서대로 이어붙인 평문(표/그림 제외)."""
        out = []
        for b in self.blocks:
            if b.type in (HEADING, PARAGRAPH, CODE) and b.text:
                out.append(b.text)
        return "\n".join(out)

    def to_dict(self) -> dict[str, Any]:
        """report.py 가 이 문서 전체를 data/out/<파일명>.json 으로 저장할 때 호출."""
        return {
            "source": self.source,
            "meta": self.meta,
            "blocks": [b.to_dict() for b in self.blocks],
            "warnings": self.warnings,
        }
