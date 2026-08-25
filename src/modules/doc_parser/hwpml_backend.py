"""HWPML(구형 HWP XML 포맷) → 공통 문서 모델(DocumentModel) 백엔드.

**배경**: `.hwp` 확장자를 쓰지만 OLE2 바이너리(HWP5)가 아니라 **평문 XML**인 문서가
실측(2026-08-03)으로 발견됐다 — 법제처 국가법령정보센터가 법률을 이 포맷으로 배포하는
사례. 루트가 `<HWPML Version="2.1">` 이고 hwp5_backend.py 가 다루는 OLE2 바이너리(HWP5),
hwpx_backend.py 가 다루는 zip+OWPML(HWPX)과는 다른 **제3의 포맷**이다.

**HWP5/HWPX 대비 오히려 다루기 쉬움**: 압축·바이너리 레코드·zip 이 전혀 없는 순수 텍스트
XML 이라 파이썬 표준 `xml.etree.ElementTree` 만으로 파싱된다(새 의존성 없음). 표 셀도
HWPX 처럼 `ColAddr`/`RowAddr`/`ColSpan`/`RowSpan` 속성이 그대로 붙어 있어 그리드 복원이
간단하고, 제목(개요) 레벨도 `PARASHAPE` 요소의 `HeadingType`/`Level` 속성으로 직접
읽힌다 — HWP5 처럼 바이트 오프셋을 스펙 문서에서 역산할 필요가 없다.

**실측(2026-08-03, 실제 .hwp 1건: 법률 XML)으로 확인된 것**: 문단(P/TEXT/CHAR), 제목
(PARASHAPE), 표(TABLE/ROW/CELL, 병합), 이미지(PICTURE→BinItem→`<TAIL><BINDATASTORAGE>`
의 Base64 BINDATA), 머리말/꼬리말(HEADER/FOOTER 요소, PARALIST 하위 문단). **실측 못한
것**: 각주/미주(FOOTNOTESHAPE 스타일 정의는 있었으나 이 문서엔 실제 각주가 없어 FOOTNOTE
요소 자체를 못 봄 — HEADER/FOOTER 와 동일한 PARALIST 패턴일 것으로 가정해 구현), 수식,
다단(멀티컬럼, 이번 1차 범위에서 제외), 이미지가 여러 개인 문서에서 BinItem↔BINDATA Id
매핑이 항상 1:1로 일치하는지(이 문서에서는 그랬음).
"""
from __future__ import annotations

import base64
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import ocr_batch
from .model import (
    FIGURE,
    FOOTNOTE,
    HEADING,
    ORIGIN_OCR,
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
from .ocr_paddle import flip_bbox_y, merge_wrapped_lines, reading_order, relocate_stray_labels

# 이미지 OCR 훅 — 다른 백엔드와 동일 시그니처.
OCR_HOOK: Callable[[bytes, int], list[dict]] | None = None


@dataclass
class _Ctx:
    para_shapes: dict[str, tuple[str | None, int | None]] = field(default_factory=dict)
    bindata: dict[str, bytes] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def looks_like_hwpml(path: str) -> bool:
    """`.hwp` 확장자 파일이 OLE2(HWP5) 대신 HWPML(XML) 인지 파일 앞부분만 읽어 확인.
    doc_parser.__init__.parse_document() 가 .hwp 라우팅 시점에 이 함수로 먼저 판별한다."""
    try:
        with open(path, "rb") as f:
            head = f.read(512)
    except Exception:  # noqa
        return False
    try:
        text = head.decode("utf-8", errors="ignore")
    except Exception:  # noqa
        return False
    return "<HWPML" in text or "<!DOCTYPE HWPML" in text


# ---------------------------------------------------------------------------
# 제목(heading) — PARASHAPELIST/PARASHAPE 요소의 HeadingType/Level 속성 직접 확인
# ---------------------------------------------------------------------------
def _load_para_shapes(root: ET.Element) -> dict[str, tuple[str | None, int | None]]:
    shapes: dict[str, tuple[str | None, int | None]] = {}
    for ps in root.iter("PARASHAPE"):
        pid = ps.get("Id")
        if pid is None:
            continue
        head_type = ps.get("HeadingType")
        try:
            level = int(ps.get("Level", "0"))
        except ValueError:
            level = 0
        shapes[pid] = (head_type, level if level > 0 else None)
    return shapes


def _heading_level(ctx: _Ctx, para_shape_id: str | None) -> int | None:
    if para_shape_id is None:
        return None
    info = ctx.para_shapes.get(para_shape_id)
    if info is None:
        return None
    head_type, level = info
    if head_type != "Outline" or level is None:
        return None
    return level


# ---------------------------------------------------------------------------
# 이미지 — TAIL/BINDATASTORAGE/BINDATA(Base64) 를 BinItem 값으로 조회
# ---------------------------------------------------------------------------
def _load_bindata(root: ET.Element, warnings: list[str]) -> dict[str, bytes]:
    bindata: dict[str, bytes] = {}
    for bd in root.iter("BINDATA"):
        bid = bd.get("Id")
        if bid is None:
            continue
        encoding = bd.get("Encoding")
        text = (bd.text or "").strip()
        if not text:
            continue
        if encoding != "Base64":
            warnings.append(
                f"BinData id={bid} 인코딩({encoding})이 Base64 가 아니라 건너뜀(미구현)")
            continue
        try:
            bindata[bid] = base64.b64decode(text)
        except Exception as e:  # noqa
            warnings.append(f"BinData id={bid} Base64 디코딩 실패: {e}")
    return bindata


def _build_figure_from_picture(picture_el: ET.Element, ctx: _Ctx, page: int,
                               section: str) -> Block | None:
    image_el = picture_el.find("IMAGE")
    if image_el is None:
        return None
    bin_item = image_el.get("BinItem")
    text: str | None = None
    origin = ORIGIN_TEXT
    if OCR_HOOK is not None and bin_item is not None:
        image_bytes = ctx.bindata.get(bin_item)
        if image_bytes is None:
            ctx.warnings.append(
                f"{ocr_batch.figure_label(page)}을 문서에서 꺼내지 못했습니다. "
                f"이 그림 안의 글자는 검토하지 않았습니다.")
        else:
            try:
                raw = OCR_HOOK(image_bytes, 0) or []
                flipped = flip_bbox_y([ln for ln in raw if ln.get("bbox")])
                lines = reading_order(flipped) + [ln for ln in raw if not ln.get("bbox")]
                text = merge_wrapped_lines(relocate_stray_labels(lines)) or None
                origin = ORIGIN_OCR
            except Exception as e:  # noqa
                ctx.warnings.append(
                    f"{ocr_batch.figure_label(page)}을 읽다가 오류가 났습니다 → {e}. "
                    f"이 그림 안의 글자는 검토하지 않았습니다.")
    return Block(FIGURE, page, text=text, origin=origin, needs_semantic=True, section=section)


# ---------------------------------------------------------------------------
# 문단 텍스트 — P/TEXT/CHAR 만(재귀 아님) — 표/그림/머리말꼬리말은 TEXT 의 다른 자식이라
# 이 경로로는 안 잡힌다(중복 처리 방지, docx/hwpx/hwp5 백엔드와 동일 원칙).
# ---------------------------------------------------------------------------
def _paragraph_text(p_element: ET.Element) -> str:
    parts: list[str] = []
    for text_el in p_element.findall("TEXT"):
        for char_el in text_el.findall("CHAR"):
            if char_el.text:
                parts.append(char_el.text)
    return "".join(parts)


def _build_note_block(note_el: ET.Element, page: int, section: str, kind: str) -> Block | None:
    """각주/미주 — HEADER/FOOTER 와 동일한 PARALIST 패턴을 가정(실측 못함, 모듈 docstring 참조)."""
    # ponytail: 각주가 실제로 들어있는 HWPML 샘플이 없어 구조를 가정만 했다 —
    # 실문서에서 FOOTNOTE 구조가 다르면 조용히 빈 블록이 된다. 샘플 확보 시 검증 필요.
    paralist = note_el.find("PARALIST")
    texts: list[str] = []
    if paralist is not None:
        for p_el in paralist.findall("P"):
            t = _paragraph_text(p_el).strip()
            if t:
                texts.append(t)
    text = "\n".join(texts) if texts else None
    return Block(FOOTNOTE, page, text=text, origin=ORIGIN_TEXT, section=section, note_kind=kind)


def _paragraph_extra_blocks(p_element: ET.Element, ctx: _Ctx, page: int,
                            section: str) -> list[Block]:
    """표/머리말/꼬리말은 호출자가 별도로 처리 — 여기서는 그림/각주/미주만."""
    blocks: list[Block] = []
    for text_el in p_element.findall("TEXT"):
        for child in text_el:
            if child.tag == "PICTURE":
                fig = _build_figure_from_picture(child, ctx, page, section)
                if fig is not None:
                    blocks.append(fig)
            elif child.tag == "FOOTNOTE":
                note = _build_note_block(child, page, section, "footnote")
                if note is not None:
                    blocks.append(note)
            elif child.tag == "ENDNOTE":
                note = _build_note_block(child, page, section, "endnote")
                if note is not None:
                    blocks.append(note)
    return blocks


def _convert_paragraph(p_element: ET.Element, ctx: _Ctx, page: int, section: str) -> list[Block]:
    blocks: list[Block] = []
    text = _paragraph_text(p_element).strip()
    if text:
        level = _heading_level(ctx, p_element.get("ParaShape"))
        if level is not None:
            blocks.append(Block(HEADING, page, text=text, level=level,
                                origin=ORIGIN_TEXT, section=section))
        else:
            blocks.append(Block(PARAGRAPH, page, text=text, origin=ORIGIN_TEXT, section=section))
    blocks.extend(_paragraph_extra_blocks(p_element, ctx, page, section))
    return blocks


# ---------------------------------------------------------------------------
# 표 — TABLE/ROW/CELL 에 이미 ColAddr/RowAddr/ColSpan/RowSpan 이 명시돼 있어(HWPX 와
# 동일) 앵커 근사나 레벨 계산 없이 그대로 채운다.
# ---------------------------------------------------------------------------
def _extract_table(table_el: ET.Element, ctx: _Ctx, page: int,
                   section: str) -> tuple[TableData, list[Block]]:
    extra_blocks: list[Block] = []
    try:
        rows = int(table_el.get("RowCount", "0"))
        cols = int(table_el.get("ColCount", "0"))
    except ValueError:
        rows = cols = 0
    cells_text: list[list[str]] = [["" for _ in range(cols)] for _ in range(rows)]
    merges: list[dict[str, int]] = []
    nested_tables: list[dict] = []

    for row_el in table_el.findall("ROW"):
        for cell_el in row_el.findall("CELL"):
            try:
                col_addr = int(cell_el.get("ColAddr", "0"))
                row_addr = int(cell_el.get("RowAddr", "0"))
                col_span = int(cell_el.get("ColSpan", "1"))
                row_span = int(cell_el.get("RowSpan", "1"))
            except ValueError:
                ctx.warnings.append("표 셀 주소/병합 속성 파싱 실패 — 이 셀은 건너뜀")
                continue

            paralist = cell_el.find("PARALIST")
            cell_paragraphs = paralist.findall("P") if paralist is not None else []
            texts: list[str] = []
            for p_el in cell_paragraphs:
                # 빈 문단도 포함(hwp_backend._extract_cell 참조 — rhwp 교차검증으로 발견:
                # 셀 안 빈 줄을 건너뛰면 실제 서식 정보가 유실된다).
                texts.append(_paragraph_text(p_el).strip())
                extra_blocks.extend(_paragraph_extra_blocks(p_el, ctx, page, section))
                for nested_table_el in p_el.findall("TEXT/TABLE"):
                    nested_data, nested_extra = _extract_table(nested_table_el, ctx, page, section)
                    nested_tables.append({"row": row_addr, "col": col_addr, "table": nested_data})
                    extra_blocks.extend(nested_extra)

            if not (0 <= row_addr < rows and 0 <= col_addr < cols):
                ctx.warnings.append(
                    f"표 셀 주소({row_addr},{col_addr})가 표 크기({rows}x{cols}) 밖 — 건너뜀")
                continue
            # 내부 빈 줄은 보존하되(hwp_backend._extract_cell 참조) 셀 앞뒤의 우발적
            # 공백/개행만 정리.
            cells_text[row_addr][col_addr] = "\n".join(texts).strip()
            if row_span > 1 or col_span > 1:
                merges.append({"row": row_addr, "col": col_addr,
                               "row_span": row_span, "col_span": col_span})

    table_data = TableData(rows=rows, cols=cols, cells=cells_text,
                           nested=bool(nested_tables), detected_only=False,
                           merges=merges, nested_tables=nested_tables)
    return table_data, extra_blocks


# ---------------------------------------------------------------------------
# 머리말/꼬리말 — HEADER/FOOTER 요소 하위 PARALIST 의 문단을 그대로 이어붙임.
# 실측(2026-08-03 법률 XML)에서 머리말 자체가 로고/제목을 담은 표를 포함하는 문서를
# 발견해(관공서 문서에서 흔한 레터헤드 레이아웃), 표/그림도 body 와 동일하게 함께 뽑는다
# — 텍스트만 이어붙이면 이런 문서는 제목 표 내용이 통째로 유실된다.
# ---------------------------------------------------------------------------
def _build_header_footer_blocks(hf_el: ET.Element, ctx: _Ctx, page: int,
                                section_tag: str) -> list[Block]:
    paralist = hf_el.find("PARALIST")
    if paralist is None:
        return []
    blocks: list[Block] = []
    texts: list[str] = []
    for p_el in paralist.findall("P"):
        for table_el in p_el.findall("TEXT/TABLE"):
            table_data, extra = _extract_table(table_el, ctx, page, section_tag)
            blocks.append(Block(TABLE, page, origin=ORIGIN_TEXT, section=section_tag,
                                table=table_data))
            blocks.extend(extra)
        t = _paragraph_text(p_el).strip()
        if t:
            texts.append(t)
        blocks.extend(_paragraph_extra_blocks(p_el, ctx, page, section_tag))
    text = "\n".join(texts).strip()
    if text:
        blocks.insert(0, Block(PARAGRAPH, page, text=text, origin=ORIGIN_TEXT, section=section_tag))
    return blocks


# ---------------------------------------------------------------------------
# 섹션 순회
# ---------------------------------------------------------------------------
def _walk_section(section_el: ET.Element, ctx: _Ctx, page: int) -> tuple[list[Block], int]:
    """PageBreak="true" 는(hp_backend.py 의 HWP5 pageBreak 속성과 동일하게, 실측으로
    검증된 관례를 그대로 적용) "이 문단이 새 페이지에서 시작한다"는 문단 자신의 속성이라
    그 문단의 블록을 만들기 전에 먼저 페이지를 올린다."""
    blocks: list[Block] = []
    for p_el in section_el.findall("P"):
        if p_el.get("PageBreak") == "true":
            page += 1

        for table_el in p_el.findall("TEXT/TABLE"):
            table_data, extra = _extract_table(table_el, ctx, page, SECTION_BODY)
            blocks.append(Block(TABLE, page, origin=ORIGIN_TEXT, section=SECTION_BODY,
                                table=table_data))
            blocks.extend(extra)
        for header_el in p_el.findall("TEXT/HEADER"):
            blocks.extend(_build_header_footer_blocks(header_el, ctx, page, SECTION_HEADER))
        for footer_el in p_el.findall("TEXT/FOOTER"):
            blocks.extend(_build_header_footer_blocks(footer_el, ctx, page, SECTION_FOOTER))

        blocks.extend(_convert_paragraph(p_el, ctx, page, SECTION_BODY))
    return blocks, page


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def parse_hwpml(path: str | Path, password: str = "") -> DocumentModel:
    """doc_parser.parse_document() 가 HWPML 로 판별된 .hwp 파일에 대해 위임하는 구현.
    password 는 아직 미지원(이 포맷의 암호화 방식 자체를 조사 못함)."""
    path = str(path)
    name = Path(path).name
    warnings: list[str] = []

    try:
        tree = ET.parse(path)
        root = tree.getroot()
    except ET.ParseError as e:
        warnings.append(f"hwpml 열기 실패: XML 파싱 오류 — {e}")
        return DocumentModel(name, {"opened": False}, [], warnings)
    except Exception as e:  # noqa
        warnings.append(f"hwpml 열기 실패: {e}")
        return DocumentModel(name, {"opened": False}, [], warnings)

    if root.tag != "HWPML":
        warnings.append(f"hwpml 열기 실패: 루트 태그가 HWPML 이 아님({root.tag})")
        return DocumentModel(name, {"opened": False}, [], warnings)

    para_shapes = _load_para_shapes(root)
    bindata = _load_bindata(root, warnings)
    ctx = _Ctx(para_shapes=para_shapes, bindata=bindata, warnings=warnings)

    blocks: list[Block] = []
    page = 0
    table_count = 0
    sections = root.findall("BODY/SECTION")
    for idx, section_el in enumerate(sections):
        if idx > 0:
            page += 1
        section_blocks, page = _walk_section(section_el, ctx, page)
        blocks.extend(section_blocks)
        table_count += sum(1 for b in section_blocks if b.type == TABLE)

    meta = {
        "opened": True,
        "sections": len(sections),
        "tables": table_count,
        "pages_approx": max(page + 1, 1),
    }
    # 검토자 화면에 지적으로 나가면 안 되는 종류다 — 이 문서를 못 읽었다는
    # 보고가 아니라 **우리 숫자에 붙는 각주**다. warnings 에 넣으면
    # parser_bridge 가 그대로 parser_warnings 로 옮기고 orchestrator 가
    # 미검토 INFO 카드로 만든다(모든 문서에서 매번).
    meta["backend_notes"] = [
        "HWPML 백엔드는 실제 .hwp(XML) 1건(2026-08-03)으로만 검증됨 — 문단/제목/표/병합/"
        "이미지/머리말꼬리말은 그 문서 구조 기준. 각주/미주는 HEADER/FOOTER 와 같은 패턴을"
        " 가정했을 뿐 실측 못함, 수식·다단 메타·암호화는 미구현(모듈 docstring 참조)",
        "pages_approx 는 구역(SECTION) 경계·명시적 PageBreak 속성만 반영한 근사값"]
    return DocumentModel(name, meta, blocks, warnings)
