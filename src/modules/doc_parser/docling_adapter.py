"""Docling 어댑터 — pdf_backend.DOCLING_HOOK 에 연결할 구조 복원(표/그림/수식/코드/헤더·풋터).

pdf_backend.DOCLING_HOOK 시그니처: (clean_path: str) -> dict
    {"tables": [{page, rows, cols, cells, cell_bbox, merges, nested, bbox, cell_images}, ...],
     "figures": [{page, bbox}, ...],                      # 표에 속하지 않는 독립 그림만
     "formulas": [{page, bbox, text}, ...],                # text = LaTeX
     "code": [{page, bbox, text, language}, ...],
     "headers_footers": [{page, bbox, text, kind}, ...],   # kind = "header" | "footer"
     "body_texts": [{page, bbox, text}, ...]}   # 본문 TEXT 보충용(§4-0 이슈⑦, 표 내용 제외)

    cell_bbox 는 cells 와 같은 rows x cols 모양의 [l,t,r,b](BOTTOMLEFT, PDF pt) 그리드로,
    빈 셀(cells[r][c]=="")을 스캔 페이지의 PaddleOCR 결과로 채울 때 위치 매칭에 쓴다(§4-0 이슈③).
    merges 는 실제 병합 영역만 기계적으로 추출한 리스트(개선①, row_span/col_span 원본
    데이터 그대로 — 판단·추정 없음). cell_images 는 그림 bbox 가 이 표의 특정 셀 bbox 안에
    들어가면 그 자리로 옮겨 담은 것(개선③, 표에 속한 그림은 최상위 figures 에서는 빠짐).

역할 분담: 텍스트/스캔 라우팅과 OCR은 이미 pdf-inspector+PaddleOCR가 처리하므로,
Docling은 do_ocr=False 로 돌려 **구조(표/그림/수식/코드/헤더·풋터)만** 담당한다
(중복 OCR 방지, 속도 확보).

수식/코드는 Docling 레이아웃 모델이 해당 영역을 FORMULA/CODE 로 분류해야 CodeFormula
enrichment 모델이 실행된다(do_formula_enrichment/do_code_enrichment) — 즉 레이아웃
모델이 "이건 수식이다/코드다"라고 못 잡으면 이 어댑터도 못 잡는다(§5-4/§5-6 설계 방향의
1차 시도: Pix2Text 등 별도 의존성 추가 전에 이미 설치된 Docling 자체 기능부터 검증).

**`nested`(진짜 재귀적 표속의표)는 이 경로로는 항상 False 다.** Docling 이 주는 평면 셀
grid 만으로는 "병합"과 "중첩"을 안정적으로 구분할 신호가 없다 — span 불규칙성으로
근사했더니 실제 문서에서 25%(16개 중 4개) 오탐이었고, 더 정교한 규칙으로도 흔한 병합
패턴과 구별하지 못했다. **없는 신호를 참인 척 내지 않는다**는 원칙에 따라 merges(병합)만
정확히 제공하고 nested/nested_tables 는 비워 둔다. 다른 신호원이 필요하면 §5-2(PyMuPDF
벡터선 재귀 검출) 검토.
"""
from __future__ import annotations

from collections.abc import Callable

from .config import docling_device
from .ocr_paddle import cluster_lines, merge_wrapped_lines, relocate_stray_labels

_CONVERTER = None


def _get_converter():
    """docling.DocumentConverter 를 지연 생성 후 모듈 전역에 캐시(재사용 시 모델 재로딩 방지).
    OCR은 꺼서(do_ocr=False) PaddleOCR 훅과 역할이 겹치지 않게 한다."""
    global _CONVERTER
    if _CONVERTER is not None:
        return _CONVERTER

    import torch
    from docling.datamodel.accelerator_options import AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.datamodel.settings import settings as docling_settings
    from docling.document_converter import DocumentConverter, PdfFormatOption

    # 어느 디바이스에 올릴지는 배포 설정에서 받아온다(DOC_PARSER_DEVICE). "auto" 면
    # Docling 자체 감지에 맡긴다 — 이 모듈은 CPU/GPU 를 스스로 정하지 않는다.
    device = docling_device()
    on_cuda = device.startswith("cuda") or (device == "auto" and torch.cuda.is_available())

    # CUDA 가 아니면 torch.compile 을 끈다.
    #
    # docling 은 레이아웃 탐지 모델을 torch.compile 로 감싸는데(추론 속도 최적화),
    # CPU 백엔드에서는 TorchInductor 가 C++ 를 생성하려고 MSVC(cl.exe)를 찾는다.
    # 빌드도구가 없는 PC 에서는 여기서 InvalidCxxCompiler 로 죽고 **Docling 단계가
    # 통째로 실패**한다(표 구조·헤더풋터 복원이 전부 빠짐). CUDA 에서는 GPU 커널
    # 경로라 이 문제가 없어서, GPU 면 그대로 컴파일해 속도 이득을 유지한다.
    #
    # 끄면 추론이 느려질 뿐 결과는 같다. 실측(2026-08-06, CPU 빌드 torch 2.13.0):
    # 켠 상태 = 변환 실패 / 끈 상태 = tables=3 figures=13 headers_footers=10 성공.
    docling_settings.inference.compile_torch_models = on_cuda

    opts = PdfPipelineOptions()
    opts.accelerator_options = AcceleratorOptions(device=device)
    opts.do_ocr = False          # 스캔 페이지 OCR은 PaddleOCR 훅이 담당(중복 방지)
    opts.do_table_structure = True
    # 수식 영역 -> LaTeX (§5-4: Pix2Text 전에 Docling 자체 기능 우선 시도)
    opts.do_formula_enrichment = True
    opts.do_code_enrichment = True      # 코드 영역 -> 들여쓰기 보존된 코드 텍스트 (§5-6)

    _CONVERTER = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
    return _CONVERTER


def _bbox_list(bbox) -> list[float] | None:
    """docling_core 의 BoundingBox 객체(pydantic, l/t/r/b 속성)를 pdf_backend/model.py 가
    기대하는 [l,t,r,b] 리스트로 변환. 좌표계(top-left/bottom-left) 변환은 하지 않음 —
    §5-8(공통 좌표 정규화 레이어) 미착수 항목과 연결됨."""
    if bbox is None:
        return None
    return [float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b)]


def _cells_grid(table_data) -> tuple[list[list[str]], list[list[list[float] | None]]]:
    """docling TableData.table_cells(평면 리스트, 각 셀에 row/col 시작 인덱스 포함)를
    rows x cols 2차원 텍스트 그리드 + 같은 모양의 bbox 그리드로 재구성.
    row_span/col_span 은 시작 셀에만 텍스트/bbox 를 채우고 나머지 병합 영역은 빈 값으로
    남긴다(간단화). bbox 그리드는 pdf_backend._apply_docling() 이 빈 셀(text=="")을
    PaddleOCR 결과로 채울 때 "이 칸이 페이지 어디쯤인지" 찾는 데 쓴다(§4-0 이슈③)."""
    rows, cols = table_data.num_rows, table_data.num_cols
    text_grid = [["" for _ in range(cols)] for _ in range(rows)]
    bbox_grid: list[list[list[float] | None]] = [[None for _ in range(cols)] for _ in range(rows)]
    for cell in table_data.table_cells:
        r, c = cell.start_row_offset_idx, cell.start_col_offset_idx
        if 0 <= r < rows and 0 <= c < cols:
            text_grid[r][c] = (cell.text or "").strip()
            bbox_grid[r][c] = _bbox_list(getattr(cell, "bbox", None))
    return text_grid, bbox_grid


def _cell_merges(table_data) -> list[dict]:
    """1x1 초과(row_span>1 또는 col_span>1)인 셀만 병합 영역으로 뽑는다 — 판단·추정 없이
    Docling이 이미 계산해둔 row_span/col_span 을 그대로 옮기는 순수 기계적 변환(개선①).
    "이 표가 무슨 의미인지"는 전혀 해석하지 않으므로 이전 `_has_nested_structure`(삭제됨)
    같은 오탐 위험이 없다."""
    return [
        {"row": c.start_row_offset_idx, "col": c.start_col_offset_idx,
         "row_span": c.row_span, "col_span": c.col_span}
        for c in table_data.table_cells
        if c.row_span > 1 or c.col_span > 1
    ]


def _bbox_center_in(inner: list[float] | None, outer: list[float] | None,
                    margin_ratio: float = 0.05) -> bool:
    """inner bbox 중심점이 outer bbox 안에 있는지, outer 크기에 비례한 허용오차로 판정.
    pdf_backend._bbox_center_in() 과 동일 설계(절대 pt 대신 상대 비율 — 문서 1건에 맞춘
    절대값은 과적합이라는 판단, avoid-single-example-overfitting 참조). 여기서는 둘 다
    Docling 이 준 같은 좌표계(BOTTOMLEFT, PDF pt)라 픽셀 변환은 필요 없다."""
    if not inner or not outer:
        return False
    cx, cy = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    mx = (outer[2] - outer[0]) * margin_ratio
    my = (outer[1] - outer[3]) * margin_ratio
    return (outer[0] - mx <= cx <= outer[2] + mx
            and outer[3] - my <= cy <= outer[1] + my)


def docling_convert(clean_path: str) -> dict:
    """DOCLING_HOOK 의 실제 구현체 — pdf_backend._apply_docling() 이 이 함수의 반환값을
    받아 마크다운 기반 TABLE 블록을 구조화된 값으로 덮어쓰고, FIGURE 블록을 새로 추가한다.

    흐름: DocumentConverter.convert() 로 문서 전체 변환(레이아웃+표구조 모델 추론)
    → doc.tables/doc.pictures 순회 → 페이지 인덱스는 docling 1-indexed 를 이 프로젝트
    표준인 0-indexed 로 맞춰서(-1) 반환.
    """
    conv = _get_converter()
    result = conv.convert(clean_path)
    doc = result.document

    tables: list[dict] = []
    for item in doc.tables:
        prov = item.prov[0] if item.prov else None
        page = (prov.page_no - 1) if prov else 0   # docling: 1-indexed -> 0-indexed
        bbox = _bbox_list(prov.bbox) if prov else None
        cells, cell_bbox = _cells_grid(item.data)
        tables.append({
            "page": page,
            "rows": item.data.num_rows,
            "cols": item.data.num_cols,
            "cells": cells,
            "cell_bbox": cell_bbox,   # bbox 그리드(BOTTOMLEFT, PDF pt) — 빈 셀 채우기용(§4-0 이슈③)
            "merges": _cell_merges(item.data),   # 병합 영역(개선①) — 사실 그대로, 추정 없음
            "bbox": bbox,
            "nested": False,   # 모듈 docstring 참조 — Docling 경로로는 신뢰 불가라 항상 False
            "cell_images": [],  # docling_convert() 아래에서 그림-표 매칭 후 채움(개선③)
        })

    # 그림: 우선 전부 모으고, 아래에서 표 셀 안에 들어가는 것만 그 표로 옮긴다(개선③).
    all_figures: list[dict] = []
    for pic in doc.pictures:
        prov = pic.prov[0] if pic.prov else None
        page = (prov.page_no - 1) if prov else 0
        bbox = _bbox_list(prov.bbox) if prov else None
        all_figures.append({"page": page, "bbox": bbox})

    figures: list[dict] = []
    tables_by_page: dict[int, list[dict]] = {}
    for t in tables:
        tables_by_page.setdefault(t["page"], []).append(t)
    for fig in all_figures:
        placed = False
        for t in tables_by_page.get(fig["page"], []):
            if not _bbox_center_in(fig["bbox"], t["bbox"]):
                continue
            cell_bbox = t["cell_bbox"]
            for r, row in enumerate(cell_bbox):
                for c, cb in enumerate(row):
                    if cb and _bbox_center_in(fig["bbox"], cb):
                        t["cell_images"].append({"row": r, "col": c, "bbox": fig["bbox"]})
                        placed = True
                        break
                if placed:
                    break
            if placed:
                break
        if not placed:
            figures.append(fig)   # 표에 안 속하면 기존처럼 독립 그림

    # 수식/코드/헤더·풋터: 레이아웃 모델이 분류한 라벨로 doc.texts 를 훑는다.
    from docling_core.types.doc import DocItemLabel

    formulas: list[dict] = []
    code: list[dict] = []
    headers_footers: list[dict] = []
    body_words: dict[int, list[dict]] = {}
    for item in doc.texts:
        prov = item.prov[0] if item.prov else None
        page = (prov.page_no - 1) if prov else 0
        bbox = _bbox_list(prov.bbox) if prov else None
        if item.label == DocItemLabel.FORMULA:
            formulas.append({"page": page, "bbox": bbox, "text": item.text or ""})
        elif item.label == DocItemLabel.CODE:
            language = str(getattr(item, "code_language", "") or "")
            code.append({"page": page, "bbox": bbox, "text": item.text or "", "language": language})
        elif item.label == DocItemLabel.PAGE_HEADER:
            headers_footers.append({"page": page, "bbox": bbox,
                                    "text": item.text or "", "kind": "header"})
        elif item.label == DocItemLabel.PAGE_FOOTER:
            headers_footers.append({"page": page, "bbox": bbox,
                                    "text": item.text or "", "kind": "footer"})
        elif item.label == DocItemLabel.TEXT and bbox and (item.text or "").strip():
            body_words.setdefault(page, []).append({"bbox": bbox, "text": item.text})

    return {"tables": tables, "figures": figures, "formulas": formulas, "code": code,
            "headers_footers": _merge_headers_footers(headers_footers),
            "body_texts": _build_body_texts(body_words, tables_by_page)}


def _build_body_texts(body_words: dict[int, list[dict]],
                      tables_by_page: dict[int, list[dict]]) -> list[dict]:
    """Docling 의 단어/구 단위 본문 TEXT 조각(doc.texts, label==TEXT)을 페이지별로 모아
    줄→문단으로 병합한다(§4-0 이슈⑦). pdf-inspector 는 needs_ocr 페이지의 마크다운을
    빈 문자열로 주기 때문에(§4-0 이슈⑥) 본문 문단을 아예 못 뽑는 페이지가 있는데,
    Docling 은 do_ocr=False 라도 진짜 벡터 텍스트가 있으면 이걸 잡아낸다 — 다만 단어
    단위라 그대로 쓰면 줄바꿈이 문서 폭 때문인지 진짜 구분인지 알 수 없으므로
    `cluster_lines`(단어→줄) + `merge_wrapped_lines`(줄→문단, 폭 판정)로 재구성한다.

    표 셀 안 텍스트도 label==TEXT 로 같이 나오는 경우가 있어(실측 확인, 표 텍스트가
    doc.tables 뿐 아니라 doc.texts 에도 중복으로 잡힘), 이미 그 페이지에서 검출된 표
    bbox 안에 중심점이 들어가는 조각은 제외한다 — 표 내용이 flat 문단으로 중복되는 걸
    막는다."""
    out: list[dict] = []
    for page, words in body_words.items():
        tables_here = tables_by_page.get(page, [])
        words = [w for w in words
                if not any(_bbox_center_in(w["bbox"], t["bbox"]) for t in tables_here)]
        if not words:
            continue
        lines = cluster_lines(words)
        text = merge_wrapped_lines(relocate_stray_labels(lines))
        if not text.strip():
            continue
        bbox = [min(ln["bbox"][0] for ln in lines), max(ln["bbox"][1] for ln in lines),
               max(ln["bbox"][2] for ln in lines), min(ln["bbox"][3] for ln in lines)]
        out.append({"page": page, "bbox": bbox, "text": text})
    return out


def _merge_headers_footers(items: list[dict]) -> list[dict]:
    """Docling은 헤더/풋터 한 줄을 조각내서 여러 텍스트 아이템으로 줄 때가 있다(실측 확인:
    "의뢰번호"와 ": SST-26-999"가 별개 PAGE_HEADER 아이템으로 옴). pdf-inspector 쪽은 같은
    줄을 한 블록으로 합쳐서 내놓기 때문에, 조각난 채로 중복 제거를 시도하면 조각 하나하나가
    너무 짧아서(→ 우연히 포함된 긴 문단까지 지우는 걸 막는 안전장치에 걸려) 정상적으로
    매칭이 안 된다. 그래서 같은 (페이지, header/footer 종류)로 묶어 순서대로 이어붙이고,
    bbox 도 합쳐서 하나의 항목으로 만든다 — doc.texts 순회 순서가 읽기 순서이므로 그대로
    이어붙이면 원래 줄이 복원된다."""
    groups: dict[tuple[int, str], list[dict]] = {}
    for it in items:
        groups.setdefault((it["page"], it["kind"]), []).append(it)

    merged: list[dict] = []
    for (page, kind), group in groups.items():
        text = " ".join(g["text"] for g in group if g["text"].strip())
        bboxes = [g["bbox"] for g in group if g["bbox"]]
        bbox = None
        if bboxes:
            bbox = [min(b[0] for b in bboxes), max(b[1] for b in bboxes),
                    max(b[2] for b in bboxes), min(b[3] for b in bboxes)]
        merged.append({"page": page, "bbox": bbox, "text": text, "kind": kind})
    return merged


def make_docling_hook() -> Callable[[str], dict]:
    """doc_parser.register_docling() 에 넘길 훅 팩토리. run_poc.py --docling 이 호출."""
    return docling_convert
