"""HWPX(zip+XML, OWPML) → 공통 문서 모델(DocumentModel) 백엔드.

docx_backend.py 가 python-docx 의 oxml(`w:tc` 등)을 직접 순회해 병합/중첩 표를
정확히 복원하는 것과 같은 방식으로, 여기서는 python-hwpx(Apache-2.0)의 oxml 객체
모델(`hwpx.oxml.*`)을 직접 순회한다. 핵심 차이:

  - **표**: HWPX 는 OOXML 과 달리 각 셀(`hp:tc`)이 `hp:cellAddr`(row/col)·
    `hp:cellSpan`(rowSpan/colSpan)을 직접 갖고 있어, docx_backend 처럼 반복되는
    앵커 셀 identity 로 병합 영역을 "역산"할 필요가 없다. python-hwpx 의
    `HwpxOxmlTable.get_cell_map()` 이 이미 각 논리 좌표를 (앵커, span) 으로 매핑해
    주므로 그대로 사용한다. 중첩 표는 `cell.tables`(셀 안 문단의 `hp:tbl` 재귀)로 얻는다.
  - **인라인 요소 스캔 범위**: HWPX 는 표가 문단 안(run 의 직계 자식)에 중첩되는 구조라
    (`hp:p > hp:run > hp:tbl`), 문단 전체를 `.//`(재귀 검색)로 훑으면 표 셀 안의
    이미지/각주 등이 표 처리 로직과 이중으로 잡힌다. 그래서 이미지/수식/각주·미주/
    도형 텍스트는 **run 의 직계 자식만** 보고(표 재귀와 동일한 깊이 원칙),
    표(`hp:tbl`)는 `paragraph.tables`/`cell.tables` 로만 별도 처리한다.
  - **이미지**: `hp:pic > hc:img[@binaryItemIDRef]` 가 헤더의 `hh:binItem[@id]` 를
    참조하고, 그 `BinData` 속성이 zip 안 실제 파일명이다(`BinData/<파일명>`).
  - **수식**: HWP 고유 EqEdit 스크립트(`hp:equation > hp:script`)를 python-hwpx 가
    이미 LaTeX 로 변환해주므로(`hwpx.equation.render_equation`), 변환 성공 시 LaTeX,
    실패 시 원본 스크립트를 FORMULA 블록 text 에 담는다(둘 다 텍스트로 이미 확보된
    상태라 needs_semantic 은 사용하지 않음 — docx_backend 의 FIGURE 관례와 다름).
  - **각주/미주**: `hp:footNote`/`hp:endNote` 는 run 의 직계 자식으로 등장 위치 그대로
    본문 흐름 안에 FOOTNOTE 블록으로 남긴다(note_kind 로 구분).
  - **도형 안 텍스트**: `hp:rect`/`hp:ellipse`/`hp:polygon`(python-hwpx 의
    markdown_export.py 와 동일한 범위 — line/arc/curve 등은 텍스트를 담지 않음) 안의
    `hp:p` 를 모아 FIGURE 블록에 실제 텍스트로 채운다(OCR 대상 아님).
  - **머리말/꼬리말**: 실무에서 두 경로가 다 쓰여 병행 지원한다. (1) 구역 속성
    `section.properties.get_header/get_footer("BOTH")` — python-hwpx 생성 API 로 만든
    문서가 쓰는 경로. (2) `hp:p > hp:run > hp:ctrl > hp:header|footer > hp:subList` —
    한컴 오피스가 실제로 내보낸 문서는 머리말/꼬리말을 구역 속성이 아니라 본문 흐름
    중의 인라인 컨트롤로 넣는다(실측 발견. (1)만 보면 그 안의 표가 통째로 유실됨,
    `_header_footer_control_blocks` 참조).
    첫 페이지/짝수 페이지 전용은 두 경로 모두 docx_backend 와 동일하게 범위 밖.
  - **다단(멀티컬럼)**: 새 블록 타입이 아니라 `DocumentModel.meta["columns"]` 에
    구역별 컬럼 수만 기록한다 — 콘텐츠 순서 자체는 바뀌지 않으므로.
  - **페이지 근사**: 구역 경계 + 문단의 `pageBreak="1"` 속성(OWPML `hp:p` 의 명시적
    쪽나눔 플래그)만 반영한 하한값 — docx_backend 의 `pages_approx` 관례와 동일.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from hwpx.document import HwpxDocument
from hwpx.equation import render_equation
from hwpx.oxml import HwpxOxmlNote, HwpxOxmlParagraph, HwpxOxmlTable
from hwpx.oxml.namespaces import HC, HP, tag_local_name

from . import ocr_batch
from .model import (
    FIGURE,
    FOOTNOTE,
    FORMULA,
    HEADING,
    ORIGIN_TEXT,
    PARAGRAPH,
    SECTION_BODY,
    SECTION_FOOTER,
    SECTION_HEADER,
    TABLE,
    Block,
    DocumentModel,
    TableData,
)

# 이미지 OCR 훅 — docx_backend.OCR_HOOK 과 동일 시그니처. doc_parser.register_ocr() 이
# 등록한 같은 훅 함수를 그대로 재사용한다(페이지 개념이 없는 이미지엔 인덱스 0 고정).
OCR_HOOK: Callable[[bytes, int], list[dict]] | None = None

_HEADING_STYLE_EN = re.compile(r"^Heading\s*(\d+)$", re.IGNORECASE)
_HEADING_STYLE_KO = re.compile(r"^(?:개요|제목)\s*(\d+)$")
_SHAPE_TEXT_TAGS = {"rect", "ellipse", "polygon"}


# ---------------------------------------------------------------------------
# 제목(heading) 판별
# ---------------------------------------------------------------------------
def _heading_level(paragraph: HwpxOxmlParagraph, doc: HwpxDocument) -> int | None:
    """스타일 이름(영문/국문 관례) 우선 판별 후, 매칭 안 되면 문단속성(paraPr)의
    hp:heading(type=OUTLINE) 레벨로 폴백한다 — docx_backend._heading_level 과 동일 원칙."""
    style_id = paragraph.style_id_ref
    style = doc.style(style_id) if style_id is not None else None
    name = ((style.name if style is not None else "") or "").strip()
    m = _HEADING_STYLE_EN.match(name) or _HEADING_STYLE_KO.match(name)
    if m:
        return int(m.group(1))

    para_pr_id = paragraph.para_pr_id_ref
    para_pr = doc.paragraph_property(para_pr_id) if para_pr_id is not None else None
    heading = para_pr.heading if para_pr is not None else None
    if (heading is not None and (heading.type or "").upper() == "OUTLINE"
            and heading.level is not None):
        return heading.level + 1  # 0-indexed -> 1-indexed
    return None


# ---------------------------------------------------------------------------
# 이미지(BinData) 해석
# ---------------------------------------------------------------------------
def _build_bin_data_index(doc: HwpxDocument) -> dict[str, str]:
    """`hc:img[@binaryItemIDRef]` 참조값 -> zip 내부 경로("BinData/<파일명>") 매핑을
    문서 전체에서 한 번만 구축.

    실측(python-hwpx 로 생성한 합성 fixture)에서 확인: python-hwpx 는 `hh:binItem`
    자체의 정수 `id` 속성과, `hc:img` 가 실제로 참조하는 `binaryItemIDRef` 값(예:
    "BIN0001" — BinData 파일명의 stem)이 서로 다르다. 표준 스펙상 실제 한컴 오피스가
    쓰는 값(정수 id)일 가능성도 있어, 안전하게 두 키(정수 id, 파일명 stem) 모두로
    같은 경로를 찾을 수 있게 인덱싱한다."""
    index: dict[str, str] = {}
    for header in doc.headers:
        for item in header.list_bin_items():
            bin_data = item.get("BinData")
            if not bin_data:
                continue
            path = f"BinData/{bin_data}"
            item_id = item.get("id")
            if item_id:
                index.setdefault(item_id, path)
            stem = PurePosixPath(bin_data).stem
            if stem:
                index.setdefault(stem, path)
    return index


def _resolve_image_bytes(doc: HwpxDocument, path_index: dict[str, str],
                         item_id: str) -> bytes | None:
    path = path_index.get(item_id)
    if path is None:
        return None
    try:
        return doc.package.read(path)
    except Exception:  # noqa
        return None


def _build_figure_block_from_image(doc: HwpxDocument, path_index: dict[str, str], item_id: str,
                                   page: int, section: str, warnings: list[str]) -> Block:
    """이미지 하나를 FIGURE 블록으로 변환. OCR_HOOK 이 등록돼 있으면 OCR 을 **예약**해
    두었다가 parse 끝에서 한꺼번에 병렬로 돌린다(docx_backend._build_figure_block 과
    동일 관례 · ocr_batch)."""
    block = Block(FIGURE, page, text=None, origin=ORIGIN_TEXT,
                  needs_semantic=True, section=section)
    if OCR_HOOK is not None:
        image_bytes = _resolve_image_bytes(doc, path_index, item_id)
        if image_bytes is None:
            warnings.append(
                f"{ocr_batch.figure_label(page)}을 문서에서 꺼내지 못했습니다. "
                f"이 그림 안의 글자는 검토하지 않았습니다.")
        else:
            ocr_batch.schedule(block, image_bytes, warnings)
    return block


# ---------------------------------------------------------------------------
# 수식 — EqEdit 스크립트 -> LaTeX(python-hwpx 내장 변환), 실패 시 원본 스크립트
# ---------------------------------------------------------------------------
def _build_formula_block(script: str, page: int, section: str) -> Block | None:
    script = (script or "").strip()
    if not script:
        return None
    text = script
    try:
        rendered = render_equation(script)
        if rendered.latex:
            text = rendered.latex
    except Exception:  # noqa — 변환 실패는 조용히 원본 스크립트로 폴백(수식 자체는 텍스트로 이미 확보)
        pass
    return Block(FORMULA, page, text=text, origin=ORIGIN_TEXT, section=section)


# ---------------------------------------------------------------------------
# 도형 안 텍스트 — FIGURE 재사용(OCR 대상 아님, 이미 텍스트 확보)
# ---------------------------------------------------------------------------
def _build_shape_block(shape_el, page: int, section: str) -> Block:
    lines: list[str] = []
    for p_el in shape_el.findall(f".//{HP}p"):
        texts: list[str] = []
        for run in p_el.findall(f"{HP}run"):
            for t in run.findall(f"{HP}t"):
                if t.text:
                    texts.append(t.text)
        line = "".join(texts).strip()
        if line:
            lines.append(line)
    text = "\n".join(lines) if lines else None
    return Block(FIGURE, page, text=text, origin=ORIGIN_TEXT,
                 needs_semantic=(text is None), section=section)


def _build_note_block(note_el, note_local: str, page: int, section: str,
                      paragraph: HwpxOxmlParagraph) -> Block:
    """`hp:footNote`/`hp:endNote` 요소 하나를 FOOTNOTE 블록으로.

    같은 요소가 두 위치에서 나온다 — run 의 직계 자식이거나, 인라인 `hp:ctrl` 안이거나.
    둘 다 실제로 쓰이므로 변환은 여기 한 곳으로 모은다."""
    note = HwpxOxmlNote(note_el, paragraph)
    note_text = (note.text or "").strip() or None
    return Block(FOOTNOTE, page, text=note_text, origin=ORIGIN_TEXT, section=section,
                 note_kind="footnote" if note_local == "footNote" else "endnote")


# ---------------------------------------------------------------------------
# 문단 안 인라인 요소(이미지/수식/각주·미주/도형)
#   — run 의 직계 자식 + 인라인 hp:ctrl 안(머리말/꼬리말·각주/미주) 둘 다 스캔
# ---------------------------------------------------------------------------
def _paragraph_extra_blocks(paragraph: HwpxOxmlParagraph, page: int, section: str,
                            doc: HwpxDocument, path_index: dict[str, str],
                            warnings: list[str],
                            image_sink: list[Block] | None = None) -> list[Block]:
    """image_sink 가 주어지면 이미지 FIGURE 블록은 반환 리스트 대신 그쪽에 담긴다
    (표 셀 안에서 호출될 때 셀 (row,col) 에 되묶기 위함 — hwp_backend._extract_cell 의
    cell_images 와 동일한 역할). 기본값(None)이면 기존처럼 반환 리스트에 섞여 나온다."""
    blocks: list[Block] = []
    for run in paragraph.element.findall(f"{HP}run"):
        for child in run:
            local = tag_local_name(child.tag)
            if local == "pic":
                img = child.find(f"{HC}img")
                item_id = img.get("binaryItemIDRef") if img is not None else None
                if item_id:
                    fig = _build_figure_block_from_image(doc, path_index, item_id, page,
                                                         section, warnings)
                    (image_sink if image_sink is not None else blocks).append(fig)
            elif local == "equation":
                script_el = child.find(f"{HP}script")
                formula = _build_formula_block(
                    script_el.text if script_el is not None else "", page, section)
                if formula is not None:
                    blocks.append(formula)
            elif local in ("footNote", "endNote"):
                blocks.append(_build_note_block(child, local, page, section, paragraph))
            elif local in _SHAPE_TEXT_TAGS:
                blocks.append(_build_shape_block(child, page, section))
            elif local == "ctrl":
                header_el = child.find(f"{HP}header")
                footer_el = child.find(f"{HP}footer")
                if header_el is not None:
                    blocks.extend(_header_footer_control_blocks(
                        header_el, SECTION_HEADER, page, paragraph, doc, path_index, warnings))
                elif footer_el is not None:
                    blocks.extend(_header_footer_control_blocks(
                        footer_el, SECTION_FOOTER, page, paragraph, doc, path_index, warnings))
                else:
                    # 각주/미주도 머리말·꼬리말과 똑같이 인라인 ctrl 안에 들어온다.
                    # run 직계 자식만 보던 위 분기로는 이 경로를 통째로 놓쳐 각주가
                    # 조용히 사라졌다(python-hwpx 5.8.0 에서 표면화, 실문서도 동일 구조).
                    for note_local in ("footNote", "endNote"):
                        for note_el in child.findall(f"{HP}{note_local}"):
                            blocks.append(_build_note_block(
                                note_el, note_local, page, section, paragraph))
    return blocks


def _header_footer_control_blocks(hf_el, section_tag: str, page: int,
                                  owning_paragraph: HwpxOxmlParagraph,
                                  doc: HwpxDocument, path_index: dict[str, str],
                                  warnings: list[str]) -> list[Block]:
    """머리말/꼬리말이 `section.properties.get_header/get_footer("BOTH")` 로 찾아지지 않고,
    본문 문단 흐름 중 `hp:run > hp:ctrl > hp:header|footer` 로 인라인 등장하는 경우를 처리.

    실측(2026-08-03, 실제 법률 문서 `.hwpx`)으로 발견: 한컴 오피스가 실제로 내보낸 문서는
    이 인라인 컨트롤 방식을 쓰는데, `_section_header_footer_blocks`(섹션 속성 기반)만으로는
    이런 문서의 머리말/꼬리말이 통째로 빈 목록으로 나왔다(rhwp 교차검증으로 표 2개가
    유실된 것을 발견). python-hwpx 생성 API(`set_header_text` 등)로 만든 합성 문서는
    섹션 속성 경로를 쓰므로 두 경로를 모두 유지한다."""
    blocks: list[Block] = []
    sub_list = hf_el.find(f"{HP}subList")
    if sub_list is None:
        return blocks
    for p_el in sub_list.findall(f"{HP}p"):
        wrapped = HwpxOxmlParagraph(p_el, owning_paragraph.section)
        for table in wrapped.tables:
            blocks.extend(_table_blocks(table, page, section_tag, doc, path_index, warnings))
        blocks.extend(_convert_paragraph(wrapped, page, section_tag, doc, path_index, warnings))
    return blocks


def _convert_paragraph(paragraph: HwpxOxmlParagraph, page: int, section: str,
                       doc: HwpxDocument, path_index: dict[str, str],
                       warnings: list[str]) -> list[Block]:
    blocks: list[Block] = []
    text = (paragraph.text or "").strip()
    if text:
        level = _heading_level(paragraph, doc)
        if level is not None:
            blocks.append(Block(HEADING, page, text=text, level=level,
                                origin=ORIGIN_TEXT, section=section))
        else:
            blocks.append(Block(PARAGRAPH, page, text=text, origin=ORIGIN_TEXT, section=section))
    blocks.extend(_paragraph_extra_blocks(paragraph, page, section, doc, path_index, warnings))
    return blocks


# ---------------------------------------------------------------------------
# 표 — get_cell_map() 의 (앵커, span) 을 그대로 병합 그리드로 사용
# ---------------------------------------------------------------------------
def _extract_table(table: HwpxOxmlTable, doc: HwpxDocument, path_index: dict[str, str],
                   warnings: list[str], extra_blocks: list[Block],
                   page: int, section: str) -> TableData:
    grid = table.get_cell_map()
    n_rows, n_cols = table.row_count, table.column_count
    cells_text: list[list[str]] = [["" for _ in range(n_cols)] for _ in range(n_rows)]
    merges: list[dict[str, int]] = []
    nested_tables: list[dict] = []
    images: list[dict] = []

    for r in range(n_rows):
        for c in range(n_cols):
            pos = grid[r][c]
            if not pos.is_anchor:
                continue
            cell = pos.cell
            cells_text[r][c] = (cell.text or "").strip()
            if pos.row_span > 1 or pos.col_span > 1:
                merges.append({"row": r, "col": c,
                               "row_span": pos.row_span, "col_span": pos.col_span})
            for cell_paragraph in cell.paragraphs:
                # 이미지는 nested_tables 와 마찬가지로 (row,col) 에 되묶어 images 에 담고,
                # 나머지(수식/각주/도형)는 기존처럼 extra_blocks(문서 최상위)로 흘려보낸다.
                cell_images: list[Block] = []
                extra_blocks.extend(_paragraph_extra_blocks(
                    cell_paragraph, page, section, doc, path_index, warnings,
                    image_sink=cell_images))
                images.extend({"row": r, "col": c, "figure": fig} for fig in cell_images)
            for nested in cell.tables:
                nested_tables.append({
                    "row": r, "col": c,
                    "table": _extract_table(nested, doc, path_index, warnings,
                                            extra_blocks, page, section),
                })

    return TableData(rows=n_rows, cols=n_cols, cells=cells_text,
                     nested=bool(nested_tables), detected_only=False,
                     merges=merges, nested_tables=nested_tables, images=images)


def _table_blocks(table: HwpxOxmlTable, page: int, section: str,
                  doc: HwpxDocument, path_index: dict[str, str],
                  warnings: list[str]) -> list[Block]:
    """표 블록 + 그 표(중첩 표 포함) 셀 안에서 발견된 이미지/수식/각주/도형 블록들을 함께 반환."""
    extra_blocks: list[Block] = []
    table_data = _extract_table(table, doc, path_index, warnings, extra_blocks, page, section)
    blocks = [Block(TABLE, page, origin=ORIGIN_TEXT, section=section, table=table_data)]
    blocks.extend(extra_blocks)
    return blocks


# ---------------------------------------------------------------------------
# 머리말/꼬리말 — 구역마다 기본("BOTH") 머리말/꼬리말만
# ---------------------------------------------------------------------------
def _section_header_footer_blocks(section, page: int) -> list[Block]:
    blocks: list[Block] = []
    props = section.properties
    header = props.get_header("BOTH")
    if header is not None:
        text = (header.text or "").strip()
        if text:
            blocks.append(Block(PARAGRAPH, page, text=text, origin=ORIGIN_TEXT,
                                section=SECTION_HEADER))
    footer = props.get_footer("BOTH")
    if footer is not None:
        text = (footer.text or "").strip()
        if text:
            blocks.append(Block(PARAGRAPH, page, text=text, origin=ORIGIN_TEXT,
                                section=SECTION_FOOTER))
    return blocks


# ---------------------------------------------------------------------------
# 다단(멀티컬럼) 메타 — 블록이 아니라 meta["columns"] 로만 기록
# ---------------------------------------------------------------------------
def _paragraph_column_defs(paragraph: HwpxOxmlParagraph, sec_idx: int) -> list[dict]:
    defs: list[dict] = []
    for ctrl in paragraph.element.findall(f"{HP}run/{HP}ctrl"):
        col_pr = ctrl.find(f"{HP}colPr")
        if col_pr is not None:
            try:
                col_count = int(col_pr.get("colCount") or "1")
            except ValueError:
                col_count = 1
            if col_count > 1:  # 1단(기본값)은 "다단"이 아니므로 기록하지 않음
                defs.append({"section": sec_idx, "col_count": col_count})
    return defs


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def parse_hwpx(path: str | Path) -> DocumentModel:
    """doc_parser.parse_document() 가 .hwpx 확장자에 대해 위임하는 최종 구현."""
    path = str(path)
    name = Path(path).name
    warnings: list[str] = []
    try:
        doc = HwpxDocument.open(path)
    except Exception as e:  # noqa
        warnings.append(f"hwpx 열기 실패: {e}")
        return DocumentModel(name, {"opened": False}, [], warnings)

    with doc:
        # 순회 중 만나는 이미지는 OCR 을 예약만 하고, 끝에서 한꺼번에 병렬로 돌린다.
        ocr_batch.begin()
        path_index = _build_bin_data_index(doc)
        blocks: list[Block] = []
        columns_meta: list[dict] = []
        page = 0

        for sec_idx, section in enumerate(doc.sections):
            if sec_idx > 0:
                page += 1
            blocks.extend(_section_header_footer_blocks(section, page))

            for paragraph in section.paragraphs:
                columns_meta.extend(_paragraph_column_defs(paragraph, sec_idx))

                # OWPML hp:p[@pageBreak] 은 "이 문단이 새 페이지에서 시작한다"는 문단 자신의
                # 속성이다(docx w:br[@type=page] 처럼 문단 중간에 끼는 흐름상 개바꿈이 아님) —
                # 그래서 이 문단의 블록을 만들기 전에 먼저 페이지를 올린다.
                if paragraph.element.get("pageBreak") == "1":
                    page += 1

                for table in paragraph.tables:
                    blocks.extend(_table_blocks(table, page, SECTION_BODY, doc,
                                                path_index, warnings))

                blocks.extend(_convert_paragraph(paragraph, page, SECTION_BODY, doc,
                                                 path_index, warnings))

        meta = {
            "opened": True,
            "paragraphs": len(doc.paragraphs),
            "tables": sum(1 for b in blocks if b.type == TABLE),  # 머리말/꼬리말 인라인 표 포함
            "sections": len(doc.sections),
            "pages_approx": page + 1,
        }
        if columns_meta:
            meta["columns"] = columns_meta
        # 검토자 화면에 지적으로 나가면 안 되는 종류다 — 이 문서를 못 읽었다는
        # 보고가 아니라 **우리 숫자에 붙는 각주**다. warnings 에 넣으면
        # parser_bridge 가 그대로 parser_warnings 로 옮기고 orchestrator 가
        # 미검토 INFO 카드로 만든다(모든 문서에서 매번).
        meta["backend_notes"] = [
            "pages_approx 는 구역 경계·명시적 쪽나눔(hp:p[@pageBreak=1])만 "
            "반영한 근사 하한값"]
        ocr_batch.run(OCR_HOOK)
        return DocumentModel(name, meta, blocks, warnings)
