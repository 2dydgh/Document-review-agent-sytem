"""HWP 5.0(구버전 바이너리, OLE2 Compound File) → 공통 문서 모델(DocumentModel) 백엔드.

구현 근거는 (1) 한컴 공식 스펙 보완문서("한글문서파일형식_5.0_revision1.3.pdf")와
(2) 오픈소스 `hwp-hwpx-parser`(Apache-2.0, 코드 재사용 없이 구조 이해에만 참고)이고,
그 위에 실 파일 검증과 rhwp(Rust, MIT) 교차검증이 더해진 상태다.
정비 전 상세 이력(교차검증에서 찾은 버그 5건, 실측으로 바로잡은 스펙과의 차이 등)은
`주석_이력_아카이브.md` 참조.

**핵심 설계**: HWP5 표 셀은 HWPX 처럼 셀 주소(행/열)와 병합 수를 레코드에 직접 갖고
있어(스펙 표80), docx_backend 처럼 앵커 셀 identity 로 병합을 역산할 필요가 없다 —
텍스트만 주는 hwp-hwpx-parser.get_tables() 보다 정확한 TableData 를 복원할 수 있는 근거.

**신뢰도 표시** — 구조마다 확인 출처가 달라 위험도가 다르다:
  - **스펙에서 직접 확인**: 레코드 헤더, 표 행/열/행별 셀수, 셀 주소·병합수, BinData
    레코드 구조, 제목 판별(표44), 수식 스크립트(표105), 다단 "단정의" 속성(표138/139).
  - **구현체 참고로 채택**(스펙에서 못 찾음, 실 파일 검증 전까지 보장 안 됨): 압축/암호화
    플래그 비트 위치, 제어문자별 확장 바이트 크기, 그림 컨트롤의 BinData 참조 오프셋,
    BinData 스트림 파일명 규칙.
  - **구조적 유사성에 기반한 추정**(검증 우선순위 높음): HWPTAG_PARA_SHAPE/STYLE 의
    tag_id 숫자값, 머리말/꼬리말 하위 레코드 배치, 도형 안 텍스트 인접 구조, 다단
    컨트롤의 속성 배치.

**범위**: 문단 텍스트, 표(병합·중첩), 이미지(OCR 훅), 각주/미주, 제목, 수식 스크립트,
머리말/꼬리말, 도형 안 텍스트, 다단 메타.
**미검증**: 각주/미주·이미지·머리말/꼬리말·도형 텍스트·수식·다단은 검증에 쓴 파일에 해당
요소가 없어 실제로 발동해보지 못했다. HWP5 는 합성 픽스처를 만들 라이브러리가 없어
(HWPX 와 달리) 레코드 스트림을 손으로 구성한 단위 테스트로만 회귀를 잡는다.
**암호화**: 탐지만 하고 복호화는 의도적 미구현 — 공식 스펙이 알고리즘을 공개하지 않고
검증용 샘플도 없다(`parse_hwp` 참조).
"""
from __future__ import annotations

import struct
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import olefile

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

# 이미지 OCR 훅 — docx_backend/hwpx_backend.OCR_HOOK 과 동일 시그니처.
OCR_HOOK: Callable[[bytes, int], list[dict]] | None = None

# ---------------------------------------------------------------------------
# 레코드 태그 ID (스펙 표 57 "본문의 데이터 레코드" — HWPTAG_BEGIN=0x10 기준 오프셋)
# ---------------------------------------------------------------------------
HWPTAG_BEGIN = 0x10
# DocInfo 안에서만 등장(hwp-hwpx-parser·스펙 표 나열 순서 모두 확인)
HWPTAG_BIN_DATA = HWPTAG_BEGIN + 2
# 아래 두 값은 스펙 본문에 숫자로 나와 있지 않아 DocInfo 레코드 나열 순서(BIN_DATA=+2 확정
# 기준 순차 배치)로 추정 — 실 파일 검증 우선순위 높음(모듈 docstring 참조).
HWPTAG_PARA_SHAPE = HWPTAG_BEGIN + 9          # DocInfo 안에서만 등장(추정)
HWPTAG_PARA_HEADER = HWPTAG_BEGIN + 50
HWPTAG_PARA_TEXT = HWPTAG_BEGIN + 51
HWPTAG_CTRL_HEADER = HWPTAG_BEGIN + 55
HWPTAG_LIST_HEADER = HWPTAG_BEGIN + 56
HWPTAG_TABLE = HWPTAG_BEGIN + 61
HWPTAG_SHAPE_COMPONENT_RECTANGLE = HWPTAG_BEGIN + 63
HWPTAG_SHAPE_COMPONENT_ELLIPSE = HWPTAG_BEGIN + 64
HWPTAG_SHAPE_COMPONENT_POLYGON = HWPTAG_BEGIN + 66
HWPTAG_SHAPE_COMPONENT_PICTURE = HWPTAG_BEGIN + 69
HWPTAG_EQEDIT = HWPTAG_BEGIN + 72

# 도형 중 텍스트(글상자)를 담을 수 있는 종류만 — hwpx_backend._SHAPE_TEXT_TAGS(rect/ellipse/
# polygon)와 동일 범위(line/arc/curve 등은 제외).
_SHAPE_TEXT_TAGS = {HWPTAG_SHAPE_COMPONENT_RECTANGLE, HWPTAG_SHAPE_COMPONENT_ELLIPSE,
                    HWPTAG_SHAPE_COMPONENT_POLYGON}


def _ctrl_id(c1: str, c2: str, c3: str, c4: str) -> int:
    return ord(c1) | (ord(c2) << 8) | (ord(c3) << 16) | (ord(c4) << 24)


# 스펙 표127 "MAKE_4CHID(a,b,c,d)"는 컨트롤 ID를 (a<<24)|(b<<16)|(c<<8)|d 로 정의하는데,
# 파일에는 리틀엔디언으로 저장돼 read-back 시 byte0=d,byte1=c,byte2=b,byte3=a 순서가 되므로
# _ctrl_id() 인자는 스펙 표기를 뒤집어 넣는다 — 각주(MAKE_4CHID('f','n',' ',' ') ->
# _ctrl_id(' ',' ','n','f'))로 이미 hwp-hwpx-parser 와 교차검증됨.
CTRL_ID_FOOTNOTE = _ctrl_id(" ", " ", "n", "f")
CTRL_ID_ENDNOTE = _ctrl_id(" ", " ", "n", "e")
CTRL_ID_HEADER = _ctrl_id("d", "a", "e", "h")   # MAKE_4CHID('h','e','a','d')
CTRL_ID_FOOTER = _ctrl_id("t", "o", "o", "f")   # MAKE_4CHID('f','o','o','t')
CTRL_ID_COLDEF = _ctrl_id("d", "l", "o", "c")   # MAKE_4CHID('c','o','l','d')

_INLINE_CTRL_EXT_SIZE = 8
_EXTENDED_CTRL_EXT_SIZE = 12


@dataclass
class _Ctx:
    """섹션 파싱 중 공유하는 상태(OLE 핸들·BinData 확장자 매핑·문단모양(제목) 매핑·
    다단(멀티컬럼) 메타·경고 누산)."""
    ole: olefile.OleFileIO
    bindata_ext: dict[int, str] = field(default_factory=dict)
    para_shapes: list[tuple[str | None, int | None]] = field(default_factory=list)
    columns: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# 레코드 순회 — tag(10bit)/level(10bit)/size(12bit), size==0xFFF 면 확장 크기 4바이트 추가
# ---------------------------------------------------------------------------
def _iter_records(data: bytes):
    offset = 0
    n = len(data)
    while offset + 4 <= n:
        header_value = struct.unpack_from("<I", data, offset)[0]
        tag_id = header_value & 0x3FF
        level = (header_value >> 10) & 0x3FF
        size = (header_value >> 20) & 0xFFF
        offset += 4
        if size == 0xFFF:
            if offset + 4 > n:
                break
            size = struct.unpack_from("<I", data, offset)[0]
            offset += 4
        if size == 0 or offset + size > n:
            break
        yield tag_id, level, data[offset:offset + size]
        offset += size


def _read_ctrl_id(record_data: bytes) -> int:
    if len(record_data) >= 4:
        return struct.unpack_from("<I", record_data, 0)[0]
    return 0


# ---------------------------------------------------------------------------
# 표 — HWPTAG_TABLE(스펙 표74/75) + 셀 HWPTAG_LIST_HEADER(스펙 표65+표79+표80)
# ---------------------------------------------------------------------------
def _parse_table_header(data: bytes) -> tuple[int, int, list[int]] | None:
    """rows/cols/행별 셀 개수. 오프셋 18(=4+2+2+2+8, 스펙 표75)부터 2바이트씩 rows개."""
    if len(data) < 18:
        return None
    rows = struct.unpack_from("<H", data, 4)[0]
    cols = struct.unpack_from("<H", data, 6)[0]
    offset = 18
    row_counts: list[int] = []
    for _ in range(rows):
        if offset + 2 > len(data):
            break
        row_counts.append(struct.unpack_from("<H", data, offset)[0])
        offset += 2
    if len(row_counts) != rows:
        row_counts = [cols] * rows
    return rows, cols, row_counts


def _parse_cell_attrs(data: bytes) -> tuple[int, int, int, int] | None:
    """표 셀의 HWPTAG_LIST_HEADER 에서 셀주소/병합 필드를 읽는다.

    **실측(2026-07-31, 실제 .hwp 3건) 오프셋 보정**: 스펙 표65("문단 리스트 헤더")는
    문단수(INT16)+속성(UINT32)=6바이트로 문서화돼 있으나, 실제 파일의 레코드를 16진
    덤프해 보니 셀 속성(표80) 필드는 오프셋 6이 아니라 **오프셋 8**부터 시작했다(중간에
    스펙 문서에 없는 2바이트 필드가 더 있음 — 어떤 필드인지는 특정 못함). 이 보정은
    실측으로 colAddr=0/rowAddr=0/colSpan=1/rowSpan=1/폭=13798/높이=2986/여백=141×4
    (스펙에 나온 표 셀 기본 여백값과 일치)/테두리ID=4 가 전부 동시에 그럴듯한 값으로
    맞아떨어지는 것으로 확인했다 — 스펙 문서만 보고 짠 최초 구현(오프셋 6)은 셀 주소가
    1024 같은 말도 안 되는 값으로 나와 모든 셀이 "표 범위 밖"으로 버려지는 버그였다."""
    if len(data) < 34:
        return None
    col_addr = struct.unpack_from("<H", data, 8)[0]
    row_addr = struct.unpack_from("<H", data, 10)[0]
    col_span = struct.unpack_from("<H", data, 12)[0]
    row_span = struct.unpack_from("<H", data, 14)[0]
    return col_addr, row_addr, max(col_span, 1), max(row_span, 1)


def _extract_cell(records: list[tuple[int, int, bytes]], cell_idx: int, cell_level: int,
                  ctx: _Ctx, page: int, section: str,
                  extra_blocks: list[Block]) -> tuple[str, TableData | None, list[Block], int]:
    """셀 하나의 텍스트·중첩표·이미지와 (부수적으로 발견되는) 각주/수식/도형 블록을 모아 반환.
    이미지는 nested_table 과 마찬가지로 셀 위치에 되묶을 수 있도록 별도 리스트로 반환하고,
    각주/수식/도형은 기존처럼 extra_blocks(문서 최상위)로만 흘려보낸다.
    (row_addr, col_addr, next_i) 는 호출자가 채운다.

    **실측(2026-07-31, 실제 .hwp 3건)으로 확인**: 셀의 HWPTAG_LIST_HEADER 뿐 아니라 그
    첫 문단의 HWPTAG_PARA_HEADER 도 셀과 **같은 level**에 나오고, 그 문단의 실제 내용
    (PARA_TEXT/PARA_CHAR_SHAPE/PARA_LINE_SEG)만 한 단계 더 깊다(level+1). 그래서
    "level <= cell_level 이면 셀 종료"가 아니라, **같은 level에서 LIST_HEADER(다음 형제
    셀)나 TABLE(형제 표)을 만났을 때만 종료**하고, 그 외(PARA_HEADER 등 같은 level의
    메타 레코드)는 이 셀 내부로 계속 취급해야 한다. 이 차이 때문에 처음 구현에서는 모든
    표 셀이 항상 빈 문자열로 나오는 버그가 있었다(스펙 문서만으로는 이 level 관계를 알 수
    없었음 — 실 파일로 처음 검증됨)."""
    texts: list[str] = []
    nested_table: TableData | None = None
    cell_images: list[Block] = []
    i = cell_idx + 1
    n = len(records)
    while i < n:
        tag_id, level, data = records[i]
        if level < cell_level:
            break
        if level == cell_level:
            if tag_id in (HWPTAG_LIST_HEADER, HWPTAG_TABLE):
                break  # 다음 형제 셀 또는 형제 표 시작 — 이 셀은 끝
            if tag_id == HWPTAG_PARA_HEADER:
                # 새 문단의 시작 — 자리를 먼저 만들어둔다(스펙: 문자수 0인 문단은
                # PARA_TEXT 레코드 자체가 없다 — "20 . . .\n\n보고자..." 처럼 완전히 빈
                # 줄은 뒤따르는 PARA_TEXT 가 아예 없어서, PARA_TEXT 만 보고 있으면 이
                # 문단 자체가 통째로 사라진다. rhwp 교차검증(2026-08-03)으로 발견).
                texts.append("")
            i += 1  # 같은 level의 메타 레코드(PARA_HEADER 포함) — 셀 내부로 계속 취급
            continue
        # level > cell_level: 이 셀 내부 콘텐츠
        if tag_id == HWPTAG_TABLE:
            nested_data, next_i, nested_extra = _extract_table(records, i, ctx, page, section)
            nested_table = nested_data  # 셀 하나에 표가 여럿이면 마지막 것만 유지(드문 케이스)
            extra_blocks.extend(nested_extra)
            i = next_i
            continue
        if tag_id == HWPTAG_CTRL_HEADER:
            ctrl_id = _read_ctrl_id(data)
            if ctrl_id in (CTRL_ID_FOOTNOTE, CTRL_ID_ENDNOTE):
                note_block, next_i = _extract_note(records, i, level, ctrl_id, page, section)
                extra_blocks.append(note_block)
                i = next_i
                continue
            i += 1
            continue
        if tag_id == HWPTAG_PARA_TEXT:
            # 직전 PARA_HEADER 가 만들어둔 자리를 채운다(같은 문단의 실제 내용).
            if texts:
                texts[-1] = _decode_para_text(data).strip()
            else:
                texts.append(_decode_para_text(data).strip())
            i += 1
            continue
        if tag_id == HWPTAG_SHAPE_COMPONENT_PICTURE:
            fig = _build_figure_from_picture_record(data, ctx, page, section)
            if fig is not None:
                cell_images.append(fig)
            i += 1
            continue
        if tag_id in _SHAPE_TEXT_TAGS:
            fig, next_i = _extract_shape_text(records, i, level, page, section)
            extra_blocks.append(fig)
            i = next_i
            continue
        if tag_id == HWPTAG_EQEDIT:
            script = _decode_equation_script(data)
            extra_blocks.append(Block(FORMULA, page, text=script, origin=ORIGIN_TEXT,
                                      section=section))
            i += 1
            continue
        i += 1
    # 내부 빈 줄은 보존하되(위 주석 참조) 셀 앞뒤의 우발적 공백/개행만 정리.
    return "\n".join(texts).strip(), nested_table, cell_images, i


def _extract_table(records: list[tuple[int, int, bytes]], table_idx: int, ctx: _Ctx,
                   page: int, section: str) -> tuple[TableData, int, list[Block]]:
    """docx_backend._extract_table / hwpx_backend._extract_table 과 동일한 역할.
    HWPX 처럼 셀이 자신의 (row,col)·(row_span,col_span)을 직접 갖고 있어(스펙 표80)
    앵커 identity 기반 근사 없이 정확한 그리드를 그대로 채운다."""
    tag_id, table_level, data = records[table_idx]
    extra_blocks: list[Block] = []
    header = _parse_table_header(data)
    if header is None:
        ctx.warnings.append("표 레코드(HWPTAG_TABLE) 파싱 실패 — 헤더 정보 부족, 빈 표로 대체")
        return TableData(rows=0, cols=0), table_idx + 1, extra_blocks

    rows, cols, row_counts = header
    total_cells = sum(row_counts) if row_counts else rows * cols
    cells_text: list[list[str]] = [["" for _ in range(cols)] for _ in range(rows)]
    merges: list[dict[str, int]] = []
    nested_tables: list[dict] = []
    images: list[dict] = []

    i = table_idx + 1
    n = len(records)
    cells_found = 0
    while i < n and cells_found < total_cells:
        tag2, level2, data2 = records[i]
        if level2 < table_level:
            break  # 표 범위를 완전히 벗어남
        if tag2 != HWPTAG_LIST_HEADER:
            i += 1  # 셀이 아닌 레코드(표 자신의 트레일링 필드 등) — 건너뜀
            continue
        # 실측 확인: 셀의 LIST_HEADER 는 표 자신과 "같은" level 에 나온다(표 안으로 한
        # 단계 더 들어가지 않음) — docx_backend 의 w:tbl/w:tr/w:tc 계층 구조와 달리 HWP5
        # 레코드 스트림은 셀을 형제로 나열한다.
        cell_level = level2
        attrs = _parse_cell_attrs(data2)
        text, cell_nested, cell_images, next_i = _extract_cell(records, i, cell_level, ctx, page,
                                                                section, extra_blocks)
        if attrs is not None:
            col_addr, row_addr, col_span, row_span = attrs
            if 0 <= row_addr < rows and 0 <= col_addr < cols:
                cells_text[row_addr][col_addr] = text
                if row_span > 1 or col_span > 1:
                    merges.append({"row": row_addr, "col": col_addr,
                                   "row_span": row_span, "col_span": col_span})
                if cell_nested is not None:
                    nested_tables.append({"row": row_addr, "col": col_addr, "table": cell_nested})
                for fig in cell_images:
                    images.append({"row": row_addr, "col": col_addr, "figure": fig})
            else:
                ctx.warnings.append(
                    f"표 셀 주소({row_addr},{col_addr})가 표 크기({rows}x{cols}) 밖 — 건너뜀")
                extra_blocks.extend(cell_images)  # 셀 위치를 못 붙이므로 최상위 블록으로라도 보존
        else:
            ctx.warnings.append("표 셀(HWPTAG_LIST_HEADER) 속성 파싱 실패 — 이 셀은 빈 값으로 유지")
            extra_blocks.extend(cell_images)  # 위와 동일한 이유로 최상위 블록으로 보존
        cells_found += 1
        i = next_i

    table_data = TableData(rows=rows, cols=cols, cells=cells_text,
                           nested=bool(nested_tables), detected_only=False,
                           merges=merges, nested_tables=nested_tables, images=images)
    return table_data, i, extra_blocks


# ---------------------------------------------------------------------------
# 각주/미주 — HWPTAG_CTRL_HEADER(ctrl id=" nf"/" ne") 하위 레코드가 본문
# ---------------------------------------------------------------------------
def _extract_note(records: list[tuple[int, int, bytes]], ctrl_idx: int, ctrl_level: int,
                  ctrl_id: int, page: int, section: str) -> tuple[Block, int]:
    kind = "footnote" if ctrl_id == CTRL_ID_FOOTNOTE else "endnote"
    texts: list[str] = []
    i = ctrl_idx + 1
    n = len(records)
    while i < n:
        tag_id, level, data = records[i]
        if level <= ctrl_level:
            break
        if tag_id == HWPTAG_PARA_TEXT:
            t = _decode_para_text(data).strip()
            if t:
                texts.append(t)
        i += 1
    text = "\n".join(texts) if texts else None
    block = Block(FOOTNOTE, page, text=text, origin=ORIGIN_TEXT, section=section, note_kind=kind)
    return block, i


# ---------------------------------------------------------------------------
# 머리말/꼬리말 — HWPTAG_CTRL_HEADER(ctrl id="head"/"foot", 스펙 표127) 하위 레코드가
# 본문. 각주/미주와 동일한 "CTRL_HEADER 하위 레코드 = 문단 리스트" 패턴을 그대로 적용
# (구조적 유사성에 근거한 가정 — 모듈 docstring 신뢰도 표시 참조).
# ---------------------------------------------------------------------------
def _extract_header_footer(records: list[tuple[int, int, bytes]], ctrl_idx: int, ctrl_level: int,
                           page: int, section_tag: str) -> tuple[list[Block], int]:
    texts: list[str] = []
    i = ctrl_idx + 1
    n = len(records)
    while i < n:
        tag_id, level, data = records[i]
        if level <= ctrl_level:
            break
        if tag_id == HWPTAG_PARA_TEXT:
            t = _decode_para_text(data).strip()
            if t:
                texts.append(t)
        i += 1
    text = "\n".join(texts).strip()
    blocks = ([Block(PARAGRAPH, page, text=text, origin=ORIGIN_TEXT, section=section_tag)]
              if text else [])
    return blocks, i


# ---------------------------------------------------------------------------
# 도형 안 텍스트(글상자) — 스펙 표81 "글상자 속성이 있으면 글상자의 리스트 정보를 얻는다"만
# 확인했고 정확한 레코드 인접 구조는 확인 못 해 셀/각주와 같은 패턴을 가정(모듈 docstring 참조).
# ---------------------------------------------------------------------------
def _extract_shape_text(records: list[tuple[int, int, bytes]], shape_idx: int, shape_level: int,
                        page: int, section: str) -> tuple[Block, int]:
    texts: list[str] = []
    i = shape_idx + 1
    n = len(records)
    while i < n:
        tag_id, level, data = records[i]
        if level <= shape_level:
            break
        if tag_id == HWPTAG_PARA_TEXT:
            t = _decode_para_text(data).strip()
            if t:
                texts.append(t)
        i += 1
    text = "\n".join(texts) if texts else None
    block = Block(FIGURE, page, text=text, origin=ORIGIN_TEXT,
                  needs_semantic=(text is None), section=section)
    return block, i


# ---------------------------------------------------------------------------
# 이미지 — HWPTAG_SHAPE_COMPONENT_PICTURE -> BinData storage_id -> BinData 스트림
# ---------------------------------------------------------------------------
def _load_bindata_extensions(ole: olefile.OleFileIO, warnings: list[str]) -> dict[int, str]:
    """DocInfo 스트림의 HWPTAG_BIN_DATA(스펙 표17, Type==EMBEDDING 케이스)에서
    storage_id -> 확장자 매핑을 구축. 오프셋: attr(2B) + storage_id(UINT16, 오프셋2) +
    ext_len(UINT16, 오프셋4) + ext(UTF-16LE, 오프셋6부터)."""
    ext_map: dict[int, str] = {}
    if not ole.exists("DocInfo"):
        return ext_map
    try:
        raw = ole.openstream("DocInfo").read()
    except Exception as e:  # noqa
        warnings.append(f"DocInfo 스트림 읽기 실패 — 이미지 확장자 매핑 불가: {e}")
        return ext_map
    try:
        data = zlib.decompress(raw, -15)
    except zlib.error:
        data = raw
    for tag_id, _level, record in _iter_records(data):
        if tag_id != HWPTAG_BIN_DATA or len(record) < 6:
            continue
        storage_id = struct.unpack_from("<H", record, 2)[0]
        ext_len = struct.unpack_from("<H", record, 4)[0]
        end = 6 + ext_len * 2
        if end > len(record):
            continue
        ext = record[6:end].decode("utf-16-le", errors="ignore")
        if ext:
            ext_map[storage_id] = ext
    return ext_map


# ---------------------------------------------------------------------------
# 제목(heading) — DocInfo의 HWPTAG_PARA_SHAPE(속성1 bit23~24=문단머리모양종류,
# bit25~27=문단수준, 스펙 표44) 를 문단 모양 아이디(등장 순서) 순으로 읽어둔다.
# ---------------------------------------------------------------------------
_PARA_HEAD_TYPES = {0: None, 1: "OUTLINE", 2: "NUMBER", 3: "BULLET"}


def _decode_para_shape_flags(record: bytes) -> tuple[str | None, int | None]:
    """HWPTAG_PARA_SHAPE 속성1(오프셋0, UINT32, 스펙 표44)의 bit23~24(문단머리모양종류)·
    bit25~27(문단수준)만 읽는다."""
    if len(record) < 4:
        return None, None
    attr1 = struct.unpack_from("<I", record, 0)[0]
    head_type = _PARA_HEAD_TYPES.get((attr1 >> 23) & 0x3)
    level_bits = (attr1 >> 25) & 0x7
    return head_type, (level_bits if level_bits > 0 else None)


def _load_para_shapes(ole: olefile.OleFileIO,
                      warnings: list[str]) -> list[tuple[str | None, int | None]]:
    shapes: list[tuple[str | None, int | None]] = []
    if not ole.exists("DocInfo"):
        return shapes
    try:
        raw = ole.openstream("DocInfo").read()
    except Exception as e:  # noqa
        warnings.append(f"DocInfo 스트림 읽기 실패 — 제목(heading) 판별 불가: {e}")
        return shapes
    try:
        data = zlib.decompress(raw, -15)
    except zlib.error:
        data = raw
    for tag_id, _level, record in _iter_records(data):
        if tag_id != HWPTAG_PARA_SHAPE:
            continue
        shapes.append(_decode_para_shape_flags(record))
    return shapes


def _heading_level(ctx: _Ctx, para_shape_id: int | None) -> int | None:
    """개요(OUTLINE) 타입 문단모양이면 1-indexed 레벨을, 아니면(번호/글머리표/일반 문단) None."""
    if para_shape_id is None or not (0 <= para_shape_id < len(ctx.para_shapes)):
        return None
    head_type, level = ctx.para_shapes[para_shape_id]
    if head_type != "OUTLINE" or level is None:
        return None
    return level


# ---------------------------------------------------------------------------
# 수식 — HWPTAG_EQEDIT(스펙 표105): attr(4B) + scriptLen(UINT16,2B) + script(WCHAR)
# ---------------------------------------------------------------------------
def _decode_equation_script(data: bytes) -> str | None:
    if len(data) < 6:
        return None
    script_len = struct.unpack_from("<H", data, 4)[0]
    end = min(6 + script_len * 2, len(data))
    if end <= 6:
        return None
    try:
        text = data[6:end].decode("utf-16-le", errors="ignore").strip()
    except Exception:  # noqa
        return None
    return text or None


# ---------------------------------------------------------------------------
# 다단(멀티컬럼) — 단정의(cold) 컨트롤. 스펙 표127에 "문단리스트" √ 표시가 없어(각주/
# 머리말꼬리말과 달리 하위 레코드로 내용이 오지 않음), 개체 이외의 컨트롤 일반 규칙
# (표64: "컨트롤 ID 이하 속성들은 CtrlID에 따라 다르다")대로 같은 CTRL_HEADER 레코드
# 안에 ctrl_id(4B) 바로 뒤에 타입별 속성이 이어 붙는다고 보고 구현 — 이 가정 자체는
# 실측 못함(검증에 쓴 3개 파일에 다단 문서 없음).
# ---------------------------------------------------------------------------
def _decode_column_count(record_data: bytes) -> int | None:
    """스펙 표138/139: ctrl_id(4B) 뒤 UINT16 속성의 bit2~9 가 단 개수(1~255)."""
    if len(record_data) < 6:
        return None
    attr = struct.unpack_from("<H", record_data, 4)[0]
    col_count = (attr >> 2) & 0xFF
    return col_count if col_count > 0 else None


def _resolve_image_bytes(ole: olefile.OleFileIO, bindata_ext: dict[int, str],
                         storage_id: int) -> bytes | None:
    ext = bindata_ext.get(storage_id)
    candidates: list[list[str]] = []
    if ext:
        candidates.append(["BinData", f"BIN{storage_id:04X}.{ext}"])
    try:
        names = [entry[1] for entry in ole.listdir() if len(entry) >= 2 and entry[0] == "BinData"]
    except Exception:  # noqa
        names = []
    for entry_name in names:
        if entry_name.upper().startswith(f"BIN{storage_id:04X}"):
            path = ["BinData", entry_name]
            if path not in candidates:
                candidates.append(path)
    for path in candidates:
        if not ole.exists(path):
            continue
        try:
            raw = ole.openstream(path).read()
        except Exception:  # noqa
            continue
        try:
            return zlib.decompress(raw, -15)
        except zlib.error:
            return raw
    return None


def _build_figure_from_picture_record(data: bytes, ctx: _Ctx, page: int,
                                      section: str) -> Block | None:
    """이 오프셋(71)은 스펙에서 직접 확인하지 못해 hwp-hwpx-parser 의 동작 중인 구현을
    참고해 채택했다(모듈 docstring 참조) — 실 파일 검증 전까지 정확도 미보장."""
    if len(data) < 73:
        return None
    bindata_id = struct.unpack_from("<H", data, 71)[0]
    if bindata_id <= 0:
        return None
    # OCR 은 여기서 기다리지 않고 예약만 한다 — parse_hwp 끝에서 한꺼번에 병렬로
    # 돌려 이 블록의 text 를 채운다(docx_backend 와 동일 관례 · ocr_batch).
    block = Block(FIGURE, page, text=None, origin=ORIGIN_TEXT,
                  needs_semantic=True, section=section)
    if OCR_HOOK is not None:
        image_bytes = _resolve_image_bytes(ctx.ole, ctx.bindata_ext, bindata_id)
        if image_bytes is None:
            ctx.warnings.append(
                f"{ocr_batch.figure_label(page)}을 문서에서 꺼내지 못했습니다. "
                f"이 그림 안의 글자는 검토하지 않았습니다.")
        else:
            ocr_batch.schedule(block, image_bytes, ctx.warnings)
    return block


# ---------------------------------------------------------------------------
# 문단 텍스트 디코딩 — 제어문자(0~31)별 확장 바이트 크기는 hwp-hwpx-parser 관례 채택
# ---------------------------------------------------------------------------
def _is_valid_ctrl_id_bytes(data: bytes, offset: int) -> bool:
    """offset 위치의 4바이트가 컨트롤ID(예: GSO=" osg")로 유효한지 — 4바이트 전부
    인쇄 가능 ASCII(0x20~0x7E) 범위인지로 판별(hwp-hwpx-parser 관례)."""
    if offset + 4 > len(data):
        return False
    for j in range(4):
        b = data[offset + j]
        if not (0x20 <= b <= 0x7E):
            return False
    return True


def _decode_para_text(data: bytes) -> str:
    chars: list[str] = []
    i = 0
    n = len(data)
    while i + 1 < n:
        code = struct.unpack_from("<H", data, i)[0]
        i += 2
        if code == 0 or code == 13:
            continue
        if code == 9:
            chars.append("\t")
            continue
        if code == 10:
            # 강제 줄바꿈(Shift+Enter, 문단 내 줄바꿈) — 실측(2026-08-03, rhwp 교차검증)으로
            # 무시하면 "및 [code10]노무제공자" 같은 텍스트가 "및 노무제공자"로 줄이 합쳐지는
            # 실제 버그를 발견함. code 13(문단 끝 마커, 각 PARA_TEXT 끝에 옴)과는 다름.
            chars.append("\n")
            continue
        if code in (1, 5, 6, 7):
            i += _INLINE_CTRL_EXT_SIZE
            continue
        if code in (2, 3, 4) or (15 <= code <= 23):
            if i + 2 <= n:
                next_code = struct.unpack_from("<H", data, i)[0]
                looks_like_char = (
                    0x0020 <= next_code <= 0x007E or 0xAC00 <= next_code <= 0xD7AF
                    or 0x3130 <= next_code <= 0x318F or next_code in (3, 4, 11, 12, 13)
                    or 15 <= next_code <= 23
                )
                if not looks_like_char:
                    i += _EXTENDED_CTRL_EXT_SIZE
            else:
                i += _EXTENDED_CTRL_EXT_SIZE
            continue
        if code == 11:
            # GSO(그리기개체/표/그림 등) 컨트롤 문자 — 뒤에 오는 4바이트가 실제로 "유효한
            # 컨트롤ID"(4바이트 전부 인쇄 가능 ASCII 0x20~0x7E, 예: " osg"=GSO)일 때만
            # 확장 필드(12바이트)를 건너뛴다. 이 검사 없이 무조건 건너뛰면, 진짜
            # 컨트롤ID가 아닌 우연한 0x000B 코드(공백 등으로 채워진 다음 글자)를 만났을
            # 때 그 뒤의 실제 텍스트까지 삼켜버린다 — rhwp 교차검증(2026-08-03)으로
            # "가        평"이 "가"로 잘리는 실제 버그를 발견해 확인함.
            if _is_valid_ctrl_id_bytes(data, i):
                i += _EXTENDED_CTRL_EXT_SIZE
            continue
        if code == 12:
            i += _INLINE_CTRL_EXT_SIZE
            continue
        if code < 32:
            continue
        chars.append(chr(code))
    return "".join(chars)


# ---------------------------------------------------------------------------
# 섹션 순회 — 표/각주는 자신의 하위 레코드 범위를 건너뛰도록 next_i 를 그대로 받아씀
# ---------------------------------------------------------------------------
def _walk_section(records: list[tuple[int, int, bytes]], ctx: _Ctx, page: int,
                  section_idx: int = 0) -> list[Block]:
    blocks: list[Block] = []
    i = 0
    n = len(records)
    pending_para_shape_id: int | None = None  # 직전 HWPTAG_PARA_HEADER 가 알려준 문단모양 ID
    while i < n:
        tag_id, level, data = records[i]

        if tag_id == HWPTAG_TABLE:
            table_data, next_i, extra = _extract_table(records, i, ctx, page, SECTION_BODY)
            blocks.append(Block(TABLE, page, origin=ORIGIN_TEXT, section=SECTION_BODY,
                                table=table_data))
            blocks.extend(extra)
            i = next_i
            continue

        if tag_id == HWPTAG_CTRL_HEADER:
            ctrl_id = _read_ctrl_id(data)
            if ctrl_id in (CTRL_ID_FOOTNOTE, CTRL_ID_ENDNOTE):
                note_block, next_i = _extract_note(records, i, level, ctrl_id, page, SECTION_BODY)
                blocks.append(note_block)
                i = next_i
                continue
            if ctrl_id in (CTRL_ID_HEADER, CTRL_ID_FOOTER):
                section_tag = SECTION_HEADER if ctrl_id == CTRL_ID_HEADER else SECTION_FOOTER
                hf_blocks, next_i = _extract_header_footer(records, i, level, page, section_tag)
                blocks.extend(hf_blocks)
                i = next_i
                continue
            if ctrl_id == CTRL_ID_COLDEF:
                col_count = _decode_column_count(data)
                if col_count is not None and col_count > 1:  # 1단(기본값)은 다단이 아님
                    ctx.columns.append({"section": section_idx, "col_count": col_count})
                i += 1
                continue
            i += 1
            continue

        if tag_id == HWPTAG_PARA_HEADER:
            if len(data) >= 10:
                pending_para_shape_id = struct.unpack_from("<H", data, 8)[0]
            i += 1
            continue

        if tag_id == HWPTAG_PARA_TEXT:
            text = _decode_para_text(data).strip()
            if text:
                level_no = _heading_level(ctx, pending_para_shape_id)
                if level_no is not None:
                    blocks.append(Block(HEADING, page, text=text, level=level_no,
                                        origin=ORIGIN_TEXT, section=SECTION_BODY))
                else:
                    blocks.append(Block(PARAGRAPH, page, text=text, origin=ORIGIN_TEXT,
                                        section=SECTION_BODY))
            pending_para_shape_id = None
            i += 1
            continue

        if tag_id == HWPTAG_SHAPE_COMPONENT_PICTURE:
            fig = _build_figure_from_picture_record(data, ctx, page, SECTION_BODY)
            if fig is not None:
                blocks.append(fig)
            i += 1
            continue

        if tag_id in _SHAPE_TEXT_TAGS:
            fig, next_i = _extract_shape_text(records, i, level, page, SECTION_BODY)
            blocks.append(fig)
            i = next_i
            continue

        if tag_id == HWPTAG_EQEDIT:
            script = _decode_equation_script(data)
            blocks.append(Block(FORMULA, page, text=script, origin=ORIGIN_TEXT,
                                section=SECTION_BODY))
            if script is None:
                ctx.warnings.append("수식 개체(HWPTAG_EQEDIT) 스크립트 디코딩 실패 — 내용 비움")
            i += 1
            continue

        i += 1
    return blocks


# ---------------------------------------------------------------------------
# 파일 헤더 — 스펙 표3 "파일 인식 정보"(256바이트): signature(32)+fileVersion(4)+
# 속성1(4, 오프셋36)+속성2(4)+EncryptVersion(4, 오프셋44)+... 전부 스펙 PDF에서 직접 확인.
# ---------------------------------------------------------------------------
def _read_file_header(ole: olefile.OleFileIO) -> dict[str, bool | int]:
    """속성1(오프셋36) 비트: bit0=압축, bit1=암호 설정, bit2=배포용 문서, bit4=DRM 보안
    문서, bit8=공인인증서 암호화, bit10=공인인증서 DRM. EncryptVersion(오프셋44)은
    0=None/1~4=버전별 암호화 알고리즘(스펙에 알고리즘 자체는 미기술)."""
    default = {"compressed": True, "encrypted": False, "distributed": False, "drm": False,
              "cert_encrypted": False, "encrypt_version": 0}
    try:
        header = ole.openstream("FileHeader").read(48)
    except Exception:  # noqa
        return default
    if len(header) < 48:
        return default
    properties = struct.unpack_from("<I", header, 36)[0]
    encrypt_version = struct.unpack_from("<I", header, 44)[0]
    return {
        "compressed": bool(properties & 0x01),
        "encrypted": bool(properties & 0x02),
        "distributed": bool(properties & 0x04),
        "drm": bool(properties & 0x10),
        "cert_encrypted": bool(properties & 0x100),
        "encrypt_version": encrypt_version,
    }


def _decompress_section(ole: olefile.OleFileIO, stream_name: str, compressed: bool) -> bytes:
    raw = ole.openstream(stream_name).read()
    if not compressed:
        return raw
    try:
        return zlib.decompress(raw, -15)
    except zlib.error:
        try:
            return zlib.decompress(raw, 15)
        except zlib.error:
            return raw


def _sniff_hwpml(path: str) -> bool:
    """.hwp 확장자지만 OLE2 가 아닐 때, 실측(2026-07-31)으로 발견된 제3의 포맷인
    HWPML(구형 XML, `<HWPML Version=...>`)인지 파일 앞부분만 읽어 확인한다. 국가법령정보
    센터 등이 법령을 이 포맷으로 배포하는 사례를 실제로 확인했다 — HWP5도 HWPX도 아니라
    이 백엔드로는 열 수 없으므로, 무엇이 문제인지 정확히 알려주기 위한 진단용."""
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
# 메인
# ---------------------------------------------------------------------------
def parse_hwp(path: str | Path, password: str = "") -> DocumentModel:
    """doc_parser.parse_document() 가 .hwp 확장자에 대해 위임하는 최종 구현.

    **Phase 4(암호화·배포용 문서) 범위**: 스펙 표3 "파일 인식 정보"로 암호화(bit1)·배포용
    문서(bit2)·DRM 보안 문서(bit4)·공인인증서 암호화(bit8) 여부는 **정확히 탐지**하지만,
    실제 복호화/역난독화 알고리즘은 **구현하지 않았다** — 한컴 공식 스펙 문서 자체가
    암호화 알고리즘을 공개하지 않고(EncryptVersion 필드만 있고 그게 어떤 암호화인지는
    안 나와 있음), 검증에 쓸 실제 암호화/배포용 문서 샘플도 없어(2026-07-31 기준 확보한
    샘플 4개 중 이 케이스 없음) 스펙 짐작만으로 크립토 코드를 짜는 건 "그럴듯하게 틀린
    결과"를 낼 위험이 커서 의도적으로 범위 밖에 뒀다. 대신 어떤 보호가 걸려 있는지
    meta 에 정확히 표시하고, password 를 받아도(아직 쓸 데가 없어) 명확히 경고한다.
    실제 암호화/배포용 샘플이 생기면 이 함수가 다음에 채울 지점이다.
    """
    path = str(path)
    name = Path(path).name
    warnings: list[str] = []
    # 순회 중 만나는 이미지는 OCR 을 예약만 하고, 끝에서 한꺼번에 병렬로 돌린다.
    ocr_batch.begin()

    try:
        if not olefile.isOleFile(path):
            if _sniff_hwpml(path):
                warnings.append(
                    "hwp 열기 실패: OLE2 바이너리(HWP5)가 아니라 HWPML(구형 XML) 포맷으로"
                    " 보임 — 이 백엔드(hwp_backend.py)는 HWP5 전용이라 지원 범위 밖(실측으로"
                    " 발견, 별도 백엔드 필요 여부는 별도 논의)")
            else:
                warnings.append("hwp 열기 실패: OLE2 복합 문서 형식이 아님")
            return DocumentModel(name, {"opened": False}, [], warnings)
        ole = olefile.OleFileIO(path)
    except Exception as e:  # noqa
        warnings.append(f"hwp 열기 실패: {e}")
        return DocumentModel(name, {"opened": False}, [], warnings)

    try:
        if not ole.exists("FileHeader"):
            warnings.append("hwp 열기 실패: FileHeader 스트림 없음(HWP5 문서가 아닌 것으로 보임)")
            return DocumentModel(name, {"opened": False}, [], warnings)

        flags = _read_file_header(ole)
        protection_meta = {
            "encrypted": flags["encrypted"],
            "distributed": flags["distributed"],
            "drm": flags["drm"],
            "cert_encrypted": flags["cert_encrypted"],
        }
        # ponytail: 보호 문서는 탐지만 하고 본문 없이 반환한다 — 복호화/역난독화 미구현.
        # 알고리즘이 공식 스펙에 없고 검증용 샘플도 없어서 의도적으로 범위 밖.
        # 실제 암호화 샘플이 확보되면 그때 구현 착수.
        if flags["encrypted"] or flags["distributed"] or flags["drm"] or flags["cert_encrypted"]:
            kind = ("암호화" if flags["encrypted"] else
                   "배포용(복제 방지)" if flags["distributed"] else
                   "DRM 보안" if flags["drm"] else "공인인증서 암호화")
            warnings.append(
                f"{kind} 문서로 탐지됨(EncryptVersion={flags['encrypt_version']}) — 실제"
                " 복호화/역난독화는 미구현(알고리즘이 공식 스펙에 없고 검증용 샘플도 없어"
                " 의도적으로 범위 밖에 둠, 모듈 docstring 참조). 본문 추출 불가")
            if password:
                warnings.append("password 인자를 받았지만 아직 사용하는 곳이 없음(미구현)")
            return DocumentModel(name, {"opened": True, **protection_meta}, [], warnings)

        bindata_ext = _load_bindata_extensions(ole, warnings)
        para_shapes = _load_para_shapes(ole, warnings)
        ctx = _Ctx(ole=ole, bindata_ext=bindata_ext, para_shapes=para_shapes, warnings=warnings)

        blocks: list[Block] = []
        section_idx = 0
        page = 0
        table_count = 0
        while ole.exists(f"BodyText/Section{section_idx}"):
            if section_idx > 0:
                page += 1
            data = _decompress_section(ole, f"BodyText/Section{section_idx}", flags["compressed"])
            records = list(_iter_records(data))
            section_blocks = _walk_section(records, ctx, page, section_idx)
            blocks.extend(section_blocks)
            table_count += sum(1 for b in section_blocks if b.type == TABLE)
            section_idx += 1

        meta = {
            "opened": True,
            "sections": section_idx,
            "tables": table_count,
            "pages_approx": max(page + 1, 1),
            **protection_meta,
        }
        if ctx.columns:
            meta["columns"] = ctx.columns
        # 검토자 화면에 지적으로 나가면 안 되는 종류다 — 이 문서를 못 읽었다는
        # 보고가 아니라 **우리 숫자에 붙는 각주**다. warnings 에 넣으면
        # parser_bridge 가 그대로 parser_warnings 로 옮기고 orchestrator 가
        # 미검토 INFO 카드로 만든다(모든 문서에서 매번).
        meta["backend_notes"] = [
            "표/병합/중첩표·문단 텍스트는 실제 .hwp 3건(2026-07-31)으로 검증됨. 각주/미주·"
            "이미지·머리말꼬리말·도형 텍스트·수식·제목(개요)·다단은 검증에 쓴 파일에 해당"
            " 요소가 없어 아직 실측 검증 못함(모듈 docstring 참조)",
            "pages_approx 는 구역(Section) 경계만 반영한 근사값"]
        ocr_batch.run(OCR_HOOK)
        return DocumentModel(name, meta, blocks, warnings)
    finally:
        ole.close()
