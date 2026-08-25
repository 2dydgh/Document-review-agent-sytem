"""PDF → 공통 문서 모델(DocumentModel) 백엔드.

확정 파이프라인:
  [A] 정규화 prestep(복호화)  ─ PyMuPDF (운영은 pikepdf/qpdf 로 교체 가능)
  [B] pdf-inspector           ─ 페이지 분류(TextBased/Scanned/Mixed) + 마크다운 추출
        ├ 텍스트 페이지 → pdf-inspector 직접추출 (OCR 안 태움)
        └ 스캔 페이지   → PaddleOCR (OCR_HOOK)
  [C] Docling                 ─ 장절·표 구조(무선/병합) + 그림/수식/코드/헤더·풋터
                                (DOCLING_HOOK)
  [D] Qwen3-VL                ─ 그림·다이어그램 의미해석 (어댑터 미구현, needs_semantic 로 표시만)
  [E] 공통 문서 모델로 정규화 ─ **하류는 어느 경로였는지 모른다**

텍스트 엔진 폴백 게이트: pdf-inspector 한글(CID) 추출 품질 실패 시 TEXT_ENGINE="pymupdf" 로
전환하면 텍스트 추출만 PyMuPDF 로 바뀌고 라우팅 구조는 그대로 유지된다.
"""
from __future__ import annotations

import re
import shutil
import statistics
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import fitz
import pdf_inspector as pi

from .model import (
    CODE,
    FIGURE,
    FORMULA,
    HEADING,
    ORIGIN_DOCLING,
    ORIGIN_OCR,
    ORIGIN_TEXT,
    PARAGRAPH,
    SECTION_FOOTER,
    SECTION_HEADER,
    TABLE,
    Block,
    DocumentModel,
    TableData,
)
from .ocr_paddle import (
    cluster_lines,
    flip_bbox_y,
    merge_wrapped_lines,
    reading_order,
    relocate_stray_labels,
)

# ---- 확장점(plugin hooks) ----
# PaddleOCR — [{"bbox":[x0,y0,x1,y1]|None,"text":str}]
OCR_HOOK: Callable[[bytes, int], list[dict]] | None = None
DOCLING_HOOK: Callable[[str], dict] | None = None         # 표/구조/그림
# Qwen3-VL 훅은 어댑터가 생길 때 여기 추가한다(needs_semantic=True 블록이 그 입력).

# ---- 텍스트 엔진 폴백 게이트 스위치 ----
TEXT_ENGINE = "pdf-inspector"   # or "pymupdf"

# 표 칸 텍스트를 뽑을 때 쓰는 "이 페이지의 줄 전부" 캐시(_page_text_lines).
# 한 페이지를 다 훑고 다음 페이지로 넘어가므로 한 장만 들고 있으면 된다.
_PAGE_LINES_CACHE: dict = {}

WATERMARK_KEYWORDS = ["대외비", "사본", "복사금지", "무단전재", "초안",
                      "confidential", "sample", "draft", "do not copy"]
_OCR_DPI = 200

# ponytail: 스캔 페이지 OCR 동시 호출 수 — 원격 VL OCR(vLLM)은 배치 처리라 병렬이 곧 처리량.
# 주의: 로컬 PaddleOCR 훅으로 바꾸면 엔진 인스턴스가 스레드 안전하지 않을 수 있다 —
# 그때는 1 로 내리거나 훅 안에서 락을 잡을 것.
_OCR_WORKERS = 4


# ---------------------------------------------------------------------------
# [A] 정규화 prestep
# ---------------------------------------------------------------------------
def _permissions(doc: fitz.Document) -> dict:
    """PyMuPDF 문서의 권한 비트를 사람이 읽을 수 있는 dict로 변환(복사/인쇄/편집 허용 여부)."""
    p = doc.permissions
    return {"copy": bool(p & fitz.PDF_PERM_COPY),
            "print": bool(p & fitz.PDF_PERM_PRINT),
            "modify": bool(p & fitz.PDF_PERM_MODIFY), "raw": int(p)}


def _normalize(path: str, password: str, tmpdir: str) -> tuple[str | None, dict, list[str]]:
    """[A] 정규화 prestep 본체 — parse_pdf() 가 가장 먼저 호출한다.

    PyMuPDF 로 열어 암호화 상태를 확인하고, user-password 가 걸려 있는데 맞는 비번이
    없으면 여기서 처리를 중단(None 반환)한다. owner-password/권한플래그만 걸린
    경우(§2-1 ① 유형)는 비번 없이 열리므로 **권한을 제거한 평문 PDF로 재저장**해
    clean_path 를 돌려준다 — 이게 pdf-inspector 가 10_restricted.pdf 를
    "scanned/0페이지"로 오분류하던 문제(§3-0-1)의 해결책이다. 반환된 clean_path 가
    이후 pdf-inspector/Docling/PaddleOCR 전 단계에 공통으로 전달된다.

    tmpdir 은 parse_pdf() 가 소유하는 임시 디렉터리다 — 보호 문서를 푼 **평문 사본이
    디스크에 남지 않도록** 파싱이 끝나면 통째로 지워진다(보안: 사내 문서의 권한 해제본이
    out/ 아래 무기한 쌓이던 동작을 대체).
    """
    warnings: list[str] = []
    doc = fitz.open(path)
    encrypted = bool(doc.needs_pass) or bool(doc.metadata.get("encryption"))
    if doc.needs_pass and not doc.authenticate(password):
        perm = _permissions(doc)
        doc.close()
        warnings.append("user-password 암호화: 유효 비밀번호 없음 → 파싱 불가")
        return None, {"opened": False, "encrypted": True, "permissions": perm}, warnings

    perm = _permissions(doc)
    clean_path = path
    if encrypted:
        clean_path = str(Path(tmpdir) / (Path(path).stem + ".plain.pdf"))
        doc.save(clean_path, encryption=fitz.PDF_ENCRYPT_NONE)
        warnings.append("암호화/권한 PDF → 복호화 prestep 수행(pdf-inspector 단독 실패 케이스)")
        if not perm["copy"]:
            warnings.append("복사 권한 OFF 이나 콘텐츠 정상 파싱됨(권한 플래그)")
    doc.close()
    meta = {"opened": True, "encrypted": encrypted, "permissions": perm,
            "restricted": (not perm["copy"]) or (not perm["modify"]),
            "normalized": clean_path != path}
    return clean_path, meta, warnings


def _pymupdf_page_text(clean_path: str, idx: int) -> str:
    """텍스트 엔진 폴백 게이트 FAIL 시(TEXT_ENGINE="pymupdf") 텍스트 페이지 추출에 쓰는 대체 경로.
    pdf-inspector 대신 PyMuPDF 로 직접 텍스트를 뽑는다
    (표는 여전히 마크다운 쪽 사용, parse_pdf 참조)."""
    doc = fitz.open(clean_path)
    t = doc[idx].get_text("text") or ""
    doc.close()
    return t.strip()


def _render_page_png(clean_path: str, idx: int, dpi: int = _OCR_DPI) -> bytes:
    """스캔 페이지를 OCR 입력용 PNG로 렌더링. parse_pdf() 가 OCR_HOOK 호출 직전에 사용."""
    doc = fitz.open(clean_path)
    data = doc[idx].get_pixmap(dpi=dpi).tobytes("png")
    doc.close()
    return data


def _render_bbox_png(clean_path: str, idx: int, bbox: list[float] | None,
                     dpi: int = _OCR_DPI) -> bytes | None:
    """Docling 이 찾은 그림/표 셀 이미지 bbox([l,t,r,b], BOTTOMLEFT PDF pt) 영역만 잘라
    OCR 입력용 PNG로 렌더링(§4-0 이슈⑨) — 페이지 전체가 아니라 그림 영역만 넘겨야 주변
    본문 글자가 같이 인식되지 않는다. bbox 좌표계 변환: fitz.Rect 는 page.rect 와 같은
    top-left 원점(y 아래로 증가)을 쓰므로, BOTTOMLEFT 의 t(위쪽 끝, 큰 y)/b(아래쪽 끝,
    작은 y)를 `page_height - t`/`page_height - b`로 뒤집는다."""
    if not bbox:
        return None
    doc = fitz.open(clean_path)
    page = doc[idx]
    page_h = float(page.rect.height)
    left, t, r, b = bbox
    rect = fitz.Rect(left, page_h - t, r, page_h - b)
    if rect.is_empty or rect.width <= 0 or rect.height <= 0:
        doc.close()
        return None
    data = page.get_pixmap(dpi=dpi, clip=rect).tobytes("png")
    doc.close()
    return data


def _ocr_figure(clean_path: str, page: int, bbox: list[float] | None,
                max_area_ratio: float = 0.5) -> str | None:
    """그림/표 셀 이미지 영역에 OCR 을 걸어 안의 글자를 인식한다(§4-0⑨).

    다른 백엔드(DOCX/HWP/HWPX/HWPML)는 임베드 이미지를 찾으면 바로 OCR 하는데 PDF 만
    이 단계가 없어 맞춘 것이다. 훅 미설정·bbox 없음·크롭/OCR 실패 시 조용히 None
    (예외로 전체 파싱을 막지 않는다).

    bbox 가 페이지 면적의 max_area_ratio(기본 50%)를 넘으면 OCR 하지 않는다 — 페이지
    대부분을 덮는 그림은 삽화가 아니라 배경/워터마크일 가능성이 높고, 그대로 OCR 하면
    이미 본문·표로 뽑힌 내용을 중복으로, 그것도 본문 경로의 보정(§4-0⑥)이 빠진 더 나쁜
    품질로 다시 뽑는다. 작은 삽화·로고·다이어그램은 그대로 OCR 된다."""
    if OCR_HOOK is None or not bbox:
        return None
    try:
        doc = fitz.open(clean_path)
        page_rect = doc[page].rect
        doc.close()
        left, t, r, b = bbox
        fig_area = max(r - left, 0.0) * max(t - b, 0.0)
        page_area = page_rect.width * page_rect.height
        if page_area > 0 and fig_area / page_area > max_area_ratio:
            return None
        png = _render_bbox_png(clean_path, page, bbox)
        if not png:
            return None
        raw = OCR_HOOK(png, page) or []
        flipped = flip_bbox_y([ln for ln in raw if ln.get("bbox")])
        lines = reading_order(flipped) + [ln for ln in raw if not ln.get("bbox")]
        return merge_wrapped_lines(relocate_stray_labels(lines)) or None
    except Exception:
        return None


def _rotated_pages(clean_path: str) -> set[int]:
    """`/Rotate` 가 0이 아닌(90/180/270) 페이지 인덱스 집합(§4-0①).

    Docling 은 회전 페이지에서 표 구조를 뒤틀리게 낸다(원인: docling 이 이미지 bbox 는
    회전 보정하면서 텍스트 셀 bbox 는 안 해 좌표계가 어긋남). pdf-inspector 는 회전
    페이지에서도 정확하므로, `_apply_docling` 이 이 페이지들만 Docling 표를 버리고
    마크다운 표를 유지하도록 걸러내는 데 쓴다. 90°만 실측 검증됨."""
    doc = fitz.open(clean_path)
    pages = {i for i in range(doc.page_count) if doc[i].rotation % 360 != 0}
    doc.close()
    return pages


def _page_height_pt(clean_path: str, idx: int) -> float:
    """페이지의 PDF pt 높이. OCR bbox(픽셀, top-left 원점)를 Docling bbox 좌표계
    (BOTTOMLEFT, PDF pt)로 맞추는 데 필요한 유일한 값(_px_bbox_to_pdf_pt 참고)."""
    doc = fitz.open(clean_path)
    h = float(doc[idx].rect.height)
    doc.close()
    return h


def _px_bbox_to_pdf_pt(bbox_px: list[float], dpi: int, page_height_pt: float) -> list[float]:
    """PaddleOCR bbox(렌더 이미지 픽셀, top-left 원점, y 아래로 증가)를 Docling 이 쓰는
    좌표계([l,t,r,b], BOTTOMLEFT 원점, y 위로 증가, PDF pt 단위)로 변환한다.

    §4-0 이슈③(스캔 페이지 표 구조 소실) 대응의 핵심 — 이 변환이 없으면 두 엔진의 bbox를
    겹침 비교할 수 없다(§5-8 "공통 좌표 정규화"의 최소 구현). dpi 는 _render_page_png 가
    렌더링한 배율과 반드시 같아야 한다(기본 _OCR_DPI)."""
    scale = 72.0 / dpi
    x0, y0, x1, y1 = bbox_px
    return [x0 * scale, page_height_pt - y0 * scale,
            x1 * scale, page_height_pt - y1 * scale]


def _bbox_center_in(inner: list[float] | None, outer: list[float] | None,
                    margin_ratio: float = 0.05) -> bool:
    """inner 의 중심점이 outer 안에 있는지(둘 다 [l,t,r,b] BOTTOMLEFT).

    OCR 줄이 Docling 표/셀 영역에 속하는지 판정할 때 쓴다. 허용 오차는 고정 pt 가
    아니라 outer 크기에 대한 **비율** — 두 엔진의 bbox 오차는 표/셀 크기에 비례해
    커지고, 고정 pt 는 특정 문서에 과적합되기 쉽다.
    margin_ratio=0.05 는 검증 문서가 늘면 재조정할 수 있는 잠정값."""
    # ponytail: margin_ratio=0.05 는 실측 표본이 적은 상태의 잠정 휴리스틱 —
    # golden/ 재검증 셋이 채워지면 그 셋으로 재측정해 결정한다.
    if not inner or not outer:
        return False
    cx, cy = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    mx = (outer[2] - outer[0]) * margin_ratio
    my = (outer[1] - outer[3]) * margin_ratio   # BOTTOMLEFT: top(outer[1]) > bottom(outer[3])
    return (outer[0] - mx <= cx <= outer[2] + mx
            and outer[3] - my <= cy <= outer[1] + my)


def _bbox_overlaps(a: list[float] | None, b: list[float] | None,
                   margin_ratio: float = 0.15) -> bool:
    """[l,t,r,b](BOTTOMLEFT) 두 bbox 가 겹치는지 — 주로 OCR 줄이 신뢰 원문 자리를 다시
    읽은 건지 판정하는 데 쓴다(겹치면 버린다, §4-0⑥).

    판정은 "포함"이 아니라 **두 bbox 를 각자 크기의 margin_ratio 만큼 부풀린 뒤 교차**다.
    마진 0 이면 OCR↔벡터 좌표가 조금만 어긋나도 겹침을 놓쳐 같은 문장이 양쪽에서
    중복 채택되고, 중심점 포함 판정으로 바꾸면 오히려 더 엄격해져 부분적으로만 겹치는
    줄을 놓친다(둘 다 실측으로 확인).
    margin_ratio=0.15 는 OCR↔벡터 오차가 셀 겹침(0.05)보다 크다고 보고 잡은 잠정값."""
    if not a or not b:
        return False

    def expand(box: list[float]) -> list[float]:
        left, t, r, b_ = box
        mx, my = (r - left) * margin_ratio, (t - b_) * margin_ratio
        return [left - mx, t + my, r + mx, b_ - my]

    al, at, ar, ab = expand(a)
    bl, bt, br, bb = expand(b)
    return al < br and bl < ar and ab < bt and bb < at


def _reliable_text_items(clean_path: str, idx: int) -> list[dict]:
    """needs_ocr 페이지에서 "OCR 없이 그대로 써도 되는" 원문 텍스트 줄을 뽑는다(§4-0⑥).

    스캔 이미지 위에 얹힌 텍스트 레이어는 일부만 인코딩이 깨지는 경우가 있어,
    U+FFFD 가 없는 단어만 신뢰 가능으로 채택한다 — 멀쩡한 원문을 OCR 로 다시 읽어
    오타를 새로 만드는 걸 막는 게 목적("경기 성남시 수정구" → "경기도 성나, 수정구").

    텍스트 소스는 pdf-inspector 가 아니라 **PyMuPDF** 다 — 실측에서 pdf-inspector 가
    한 페이지를 통째로 0건으로 놓치거나 다수 글자가 깨진 반면 PyMuPDF 는 온전히
    뽑아냈다(텍스트 엔진 폴백 게이트가 PyMuPDF 를 대체 엔진으로 채택한 것과 같은 근거).
    좌표는 PyMuPDF(좌상단 원점) → 프로젝트 공통 [l,t,r,b](좌하단 원점)로 변환한다.

    `split_gap_ratio=2.0`(§4-0⑲): 같은 y 의 왼쪽 라벨열과 오른쪽 내용열이 한 줄로
    병합되는 걸 막는다 — 한 번 병합되면 이후 어떤 단계로도 되돌릴 수 없다.
    임계값 근거는 `ocr_paddle.cluster_lines` 참조."""
    doc = fitz.open(clean_path)
    page_h = float(doc[idx].rect.height)
    words = doc[idx].get_text("words")
    doc.close()
    items = [{"bbox": [x0, page_h - y0, x1, page_h - y1], "text": text}
            for x0, y0, x1, y1, text, *_ in words if text.strip() and "�" not in text]
    return cluster_lines(items, split_gap_ratio=2.0)


# 마크다운 추출 실패 판정에서 "기준선에 준한다"고 볼 하한 비율.
# 절대 글자 수 임계를 쓰지 않는 이유는 _md_extract_failed docstring 참조.
_MD_FALLBACK_RATIO = 0.5


def _text_volume(clean_path: str, idx: int) -> int:
    """페이지에서 OCR 없이 신뢰 가능하게 뽑히는 원문 글자 수(_reliable_text_items 기준).
    _md_extract_failed 의 입력이자, 그 기준선을 만드는 척도이기도 하다 — 양쪽을 같은
    척도로 재야 비교가 성립하므로 이 함수 하나로 통일한다."""
    return sum(len(ln["text"]) for ln in _reliable_text_items(clean_path, idx))


def _md_extract_failed(volume: int, baseline: float | None) -> bool:
    """`needs_ocr` 로 표시된 페이지가 **진짜 스캔**인지, pdf-inspector 의 마크다운 추출만
    실패한 **정상 텍스트 페이지**인지 판정한다.

    배경(실측 2026-08-06, `99. 일반성적서 예시.pdf`): pdf-inspector 는 같은 문서에 대해
    `classify_pdf()` 로는 "OCR 필요 페이지 없음"(`pages_needing_ocr=[]`)이라고 답하면서
    `extract_pages_markdown()` 에서는 10쪽 중 6쪽을 빈 문자열 + `needs_ocr=True`
    (`ocr_reason="suspected_garbled_text"`)로 돌려준다. 그런데 같은 라이브러리의
    `extract_text()` 는 그 문서의 한글을 100% 뽑고(PyMuPDF 와 음절 수 동일), 문제의 6쪽도
    PyMuPDF 로 374~1302자가 멀쩡히 나온다 — "글자가 깨진 것 같다"는 의심이 오탐이다.
    이 플래그를 그대로 믿으면 텍스트 페이지에 OCR 을 태워 시간을 쓰고, 원문 대신 OCR
    오인식 텍스트를 결과에 담게 된다.

    "깨졌다"는 의심 자체는 함부로 무시하지 않는다 — 기준선을 만드는 `_text_volume()` 이
    `_reliable_text_items()` 를 쓰므로 U+FFFD 가 섞인 단어는 애초에 글자 수에 안 잡힌다.
    진짜로 깨진 페이지는 글자 수가 기준선에 못 미쳐 OCR 경로로 남는다.

    판정은 **문서 내부 상대 기준**으로만 한다 — "N자 이상이면 텍스트 페이지" 식의 절대
    임계는 문서 1건에 맞춘 튜닝(과적합)이라 다른 문서에서 근거가 없다. 대신 같은 문서에서
    마크다운 추출에 성공한 페이지들의 원문 글자 수 중앙값을 기준선으로 삼는다:

      - 기준선의 `_MD_FALLBACK_RATIO` 이상이면 → 추출 실패(스캔 아님). OCR 을 건너뛴다.
      - 미만이면 → 진짜 스캔으로 보고 기존 OCR 경로 유지. 스캔 페이지에 얹힌 텍스트
        레이어(쪽번호 스탬프 등 수십 자)는 여기서 걸러진다.
      - 기준선 자체가 없으면(문서 전체가 스캔이라 성공 페이지가 0개) → **판정하지 않고**
        OCR 유지. 비교 근거가 없을 때 추측하지 않는다.
    """
    if not baseline:
        return False
    return volume >= baseline * _MD_FALLBACK_RATIO


# ---------------------------------------------------------------------------
# 마크다운 → 블록 파서
# ---------------------------------------------------------------------------
def _markdown_to_blocks(md: str, page: int, origin: str = ORIGIN_TEXT) -> list[Block]:
    """pdf-inspector 가 페이지 단위로 내주는 마크다운 문자열(제목 #, 표 |a|b|, 코드 ``` 펜스)을
    한 줄씩 훑으며 공통 문서 모델 Block(HEADING/PARAGRAPH/TABLE/CODE)로 쪼갠다.
    parse_pdf() 가 텍스트 페이지마다 호출 — Docling 훅이 없을 때는 여기서 만든 TABLE
    블록이 최종 결과가 되고(§ detected_only=True), 있으면 _apply_docling() 이 나중에 덮어쓴다."""
    blocks: list[Block] = []
    para: list[str] = []
    table_rows: list[list[str]] = []
    in_code = False
    code: list[str] = []

    def flush_para():
        """누적된 일반 텍스트 줄들을 하나의 PARAGRAPH 블록으로 확정."""
        if para:
            blocks.append(Block(PARAGRAPH, page, text=" ".join(para).strip(), origin=origin))
            para.clear()

    def flush_table():
        """누적된 파이프(|) 표 행들을 TABLE 블록으로 확정. 구분선(---) 행은 제외하고 셀 개수로
        열 수를 계산한다.

        `detected_only=True` 로 낸다 — 마크다운 파이프표에는 병합·중첩 정보가 애초에 없고
        열 수도 "행별 셀 개수의 최댓값"이라 구조가 확정된 적이 없다. 구조를 실제로 확인한
        `_apply_docling()` 이 이 표를 교체할 때만 False 로 내린다."""
        if table_rows:
            rows = [r for r in table_rows if not _is_sep_row(r)]
            cols = max((len(r) for r in rows), default=0)
            blocks.append(Block(TABLE, page, origin=origin,
                                table=TableData(rows=len(rows), cols=cols,
                                                cells=rows, nested=False,
                                                detected_only=True)))
            table_rows.clear()

    for line in (md or "").splitlines():
        s = line.strip()
        if s.startswith("```"):
            flush_para()
            flush_table()
            if in_code:
                blocks.append(Block(CODE, page, text="\n".join(code), origin=origin))
                code.clear()
            in_code = not in_code
            continue
        if in_code:
            code.append(line)
            continue
        if not s:
            flush_para()
            flush_table()
            continue
        if s.startswith("|") and s.endswith("|"):
            flush_para()
            table_rows.append([c.strip() for c in s.strip("|").split("|")])
            continue
        flush_table()
        if s.startswith("#"):
            flush_para()
            level = len(s) - len(s.lstrip("#"))
            blocks.append(Block(HEADING, page, text=s.lstrip("# ").strip(),
                                level=level, origin=origin))
        else:
            para.append(s)
    flush_para()
    flush_table()
    if in_code and code:
        blocks.append(Block(CODE, page, text="\n".join(code), origin=origin))
    return blocks


_HEAD_NUM = re.compile(r"^\d+(?:\.\d+)*\.?$")


def _heading_level(num: str) -> int:
    """'1.0'→1, '3.1'→2 — 이 도메인 양식은 X.0 이 최상위 절이다."""
    parts = [p for p in num.rstrip(".").split(".") if p]
    if len(parts) > 1 and parts[-1] == "0":
        parts.pop()
    return min(len(parts), 6)


def _rescue_split_headings(blocks: list[Block]) -> list[Block]:
    """pdf-inspector 가 격자 레이아웃을 찢으며 잃어버린 절 제목을 복구한다(§4-0 이슈㉒).

    실측(SKN56_CDMS_RVVR_Rev05.pdf) 두 패턴:
      - p5: 페이지 전체가 표로 잡혀 머리행이 `|1.0|Purpose|||` — 제목 블록이 없다.
      - p7: 번호가 `**3.0**` 문단으로, 제목이 번호 없는 `# References` 로 찢어졌다.
    절 트리에 1.0/3.0 이 없으니 필수 절 검사가 멀쩡한 문서에 "필수 항목 누락"
    MAJOR 를 냈다. 두 패턴만, 신호가 명확할 때만 복구한다 — 번호는 점을 포함한
    숫자열이어야 하고(쪽번호 "21" 같은 정수 단독 제외), 패턴②는 같은 페이지에
    번호 문단과 번호 없는 H1 이 **각각 하나뿐**일 때만 짝지어 추측을 배제한다.
    """
    def _num(text: str) -> str:
        s = (text or "").strip().strip("*").strip()
        return s if ("." in s and _HEAD_NUM.match(s)) else ""

    # 패턴② — 번호 단독 문단 + 번호 없는 H1 짝짓기(페이지당 하나씩일 때만)
    orphans: dict[int, list[Block]] = {}
    bare_h1: dict[int, list[Block]] = {}
    for b in blocks:
        if b.type == PARAGRAPH and _num(b.text):
            orphans.setdefault(b.page, []).append(b)
        elif (b.type == HEADING and (b.level or 1) == 1
              and (b.text or "").strip() and not (b.text or "").strip()[0].isdigit()):
            bare_h1.setdefault(b.page, []).append(b)
    drop: set[int] = set()
    for page, os_ in orphans.items():
        h1s = bare_h1.get(page) or []
        if len(os_) == 1 and len(h1s) == 1:
            num = _num(os_[0].text)
            h1s[0].text = num + " " + h1s[0].text.strip()
            h1s[0].level = _heading_level(num)
            drop.add(id(os_[0]))

    # 패턴① — 머리행이 [번호, 짧은 제목]뿐인 표 → 표 앞에 제목 블록 삽입.
    # 표 자체는 그대로 둔다(본문 텍스트가 그 셀들에 실려 있다).
    out: list[Block] = []
    for b in blocks:
        if id(b) in drop:
            continue
        if b.type == TABLE and b.table and b.table.cells:
            first = [(c or "").strip() for c in b.table.cells[0]]
            filled = [c for c in first if c]
            if (len(filled) == 2 and _num(filled[0])
                    and filled[1][:1].isalpha() and len(filled[1]) <= 80):
                out.append(Block(HEADING, b.page, text=filled[0] + " " + filled[1],
                                 level=_heading_level(filled[0]), origin=b.origin))
        out.append(b)
    return out


def _is_sep_row(row: list[str]) -> bool:
    """마크다운 표의 헤더 구분선(`|---|:--:|` 같은 행)인지 판별 — flush_table 이 실제
    데이터 행과 구분해 걸러내는 데 사용."""
    return bool(row) and all(set(c) <= set("-: ") and c for c in row)


# ---------------------------------------------------------------------------
# [C] Docling 보강 (표 구조/그림)
# ---------------------------------------------------------------------------
def _norm_ws(s: str) -> str:
    """공백류를 전부 단일 스페이스로 접어 비교용으로 정규화. 코드/수식 중복 제거에 사용
    (pdf-inspector 가 만든 한 줄짜리 뭉개진 텍스트와 Docling 이 되살린 서식있는 텍스트를
    내용 기준으로 같은 것인지 판정하려면 공백 차이를 무시해야 한다)."""
    return " ".join((s or "").split())


def _fill_table_from_ocr(dt: dict, ocr_lines_by_page: dict[int, list[dict]],
                         consumed: dict[int, set[int]]) -> None:
    """§4-0 이슈③ 대응: Docling 표(dt, docling_convert 의 raw dict)의 bbox 영역과 겹치는
    OCR 줄을 찾아 (a) consumed 에 표시해 나중에 flat OCR 문단에서 빼고,
    (b) Docling이 못 채운 빈 셀(cells[r][c]=="")만 그 줄 텍스트로 채운다 — **이미 Docling이
    채운 셀은 절대 덮어쓰지 않는다**(Docling 결과를 신뢰하고, OCR은 빈틈만 메움).
    표 밖 OCR 줄은 손대지 않고 그대로 문단에 남는다."""
    page = int(dt.get("page", 0))
    lines = ocr_lines_by_page.get(page)
    tbbox = dt.get("bbox")
    if not lines or not tbbox:
        return
    cell_bbox = dt.get("cell_bbox")
    cells = dt.get("cells")
    for i, ln in enumerate(lines):
        if i in consumed[page] or not ln.get("bbox"):
            continue
        if not _bbox_center_in(ln["bbox"], tbbox):
            continue
        consumed[page].add(i)   # 표 영역에 속한 줄 — Docling 결과와 중복이니 문단에서는 제외
        if not cell_bbox or not cells:
            continue
        for r, row in enumerate(cells):
            for c, val in enumerate(row):
                if val:
                    continue  # Docling이 이미 인식함 — 그대로 둔다
                cb = cell_bbox[r][c] if r < len(cell_bbox) and c < len(cell_bbox[r]) else None
                if cb and _bbox_center_in(ln["bbox"], cb):
                    cells[r][c] = (ln["text"] or "").strip()


def _build_cell_images(dt: dict, page: int, clean_path: str | None = None) -> list[dict]:
    """docling_adapter 가 표 dict 에 담아준 cell_images([{row,col,bbox}])를
    TableData.images 형식([{row,col,figure:Block}], 개선③)으로 변환. clean_path 가 주어지면
    (§4-0 이슈⑨) 이미지 영역에 OCR을 걸어 안의 글자를 인식(`_ocr_figure`) — 그림 자체가
    "무엇을 그렸는지"(장면 의미)는 여전히 모르므로 OCR 성공 여부와 무관하게 FIGURE 블록에
    needs_semantic=True 는 유지한다(그림 블록 공통 관례)."""
    out = []
    for ci in dt.get("cell_images", []):
        bbox = ci.get("bbox")
        text = _ocr_figure(clean_path, page, bbox) if clean_path else None
        origin = ORIGIN_OCR if text else ORIGIN_DOCLING
        out.append({"row": ci["row"], "col": ci["col"],
                    "figure": Block(FIGURE, page, text=text, bbox=bbox, origin=origin,
                                    needs_semantic=True)})
    return out


def _run_ocr_parallel(idxs: list[int], ocr_one) -> dict[int, list | Exception]:
    """페이지별 OCR 을 병렬 실행 — 예외는 삼키지 않고 값으로 모아 호출부가
    페이지 단위 warning 처리를 그대로 하게 한다."""
    out: dict[int, list | Exception] = {}
    with ThreadPoolExecutor(max_workers=min(_OCR_WORKERS, len(idxs))) as pool:
        futs = {i: pool.submit(ocr_one, i) for i in idxs}
        for i, fut in futs.items():
            try:
                out[i] = fut.result()
            except Exception as e:  # noqa: BLE001 — 호출부의 페이지별 except 경로로 전달
                out[i] = e
    return out


def _apply_docling(blocks: list[Block], struct: dict, warnings: list[str],
                   ocr_lines_by_page: dict[int, list[dict]] | None = None,
                   rotated_pages: set[int] | None = None,
                   clean_path: str | None = None) -> list[Block]:
    """DOCLING_HOOK 결과로 표 구조(중첩/병합)·그림·수식·코드 블록을 보강한다.

    같은 페이지의 기존 TABLE 블록을 순서대로 매칭해 구조 정보로 교체하고(origin 도
    ORIGIN_DOCLING 으로), 매칭 안 된 표·그림은 새 블록으로 추가한다.

    항목별 처리 규칙:
      - 그림: clean_path 가 있으면 OCR 로 안의 글자를 인식한다(§4-0⑨, `_ocr_figure`) —
        다른 백엔드는 하는데 PDF 만 이 단계가 없었다.
      - 수식/코드: pdf-inspector 가 뭉개서 PARAGRAPH 로 넣어둔 같은 내용을 먼저 지운 뒤
        FORMULA/CODE 로 추가(중복 방지). headers_footers 도 같은 방식으로 처리하되
        타입은 PARAGRAPH 유지 + section 만 지정(docx_backend 와 같은 관례).
      - 표 빈 셀: ocr_lines_by_page 가 있으면 `_fill_table_from_ocr` 로 채우고, 표와
        겹친 OCR 줄은 flat PARAGRAPH 에서 제거(§4-0③).
      - 회전 페이지: rotated_pages 의 Docling 표는 무시하고 마크다운 표를 유지한다
        (detected_only=True) — Docling 회전 표 뒤틀림 회피(§4-0①, 90°만 검증됨).
      - body_texts: 그 페이지에 문단이 하나도 없을 때만 보충(§4-0⑦, 순수 공백 채우기).

    기대 struct 형식(느슨):
        {"tables":[{page,rows,cols,cells,cell_bbox,merges,nested,bbox,cell_images}],
                              "figures":[{page,bbox}],
                              "formulas":[{page,bbox,text}],
                              "code":[{page,bbox,text,language}],
                              "headers_footers":[{page,bbox,text,kind}],
                              "body_texts":[{page,bbox,text}]}
    """
    try:
        d_tables = struct.get("tables", [])
        d_figs = struct.get("figures", [])
        d_formulas = struct.get("formulas", [])
        d_code = struct.get("code", [])
        d_headers_footers = struct.get("headers_footers", [])
        d_body_texts = struct.get("body_texts", [])
    except Exception:
        return blocks

    rotated_pages = rotated_pages or set()
    if rotated_pages:
        skipped_pages = sorted({int(t.get("page", 0)) for t in d_tables
                                if int(t.get("page", 0)) in rotated_pages})
        if skipped_pages:
            warnings.append(f"회전 페이지 {skipped_pages}: Docling 표 구조 신뢰 불가(§4-0 이슈①) "
                            f"— pdf-inspector 표 유지")
        d_tables = [t for t in d_tables if int(t.get("page", 0)) not in rotated_pages]

    ocr_lines_by_page = ocr_lines_by_page or {}
    consumed: dict[int, set[int]] = {p: set() for p in ocr_lines_by_page}
    for dt in d_tables:
        _fill_table_from_ocr(dt, ocr_lines_by_page, consumed)

    # 페이지별 Docling 표를 큐로
    by_page: dict[int, list[dict]] = {}
    for t in d_tables:
        by_page.setdefault(int(t.get("page", 0)), []).append(t)

    out: list[Block] = []
    for b in blocks:
        if b.type == TABLE and by_page.get(b.page):
            dt = by_page[b.page].pop(0)
            b.table = TableData(rows=int(dt.get("rows", b.table.rows if b.table else 0)),
                                cols=int(dt.get("cols", b.table.cols if b.table else 0)),
                                cells=dt.get("cells", b.table.cells if b.table else []),
                                nested=bool(dt.get("nested", False)),
                                detected_only=False,
                                merges=dt.get("merges", []),
                                images=_build_cell_images(dt, b.page, clean_path))
            b.bbox = dt.get("bbox", b.bbox)
            b.origin = ORIGIN_DOCLING
        elif b.type == TABLE and b.page in rotated_pages and b.table:
            # Docling 표를 의도적으로 안 씀(회전 페이지) — 마크다운 표 그대로지만
            # "구조 확정" 아님을 정직하게 표시(§4-0 이슈①)
            b.table.detected_only = True
        out.append(b)
    # Docling 이 새로 찾은 표(마크다운에 없던 것 — 스캔 페이지 표는 전부 여기로 들어옴)도 추가
    for page, rest in by_page.items():
        for dt in rest:
            out.append(Block(TABLE, page, origin=ORIGIN_DOCLING, bbox=dt.get("bbox"),
                             table=TableData(int(dt.get("rows", 0)), int(dt.get("cols", 0)),
                                             dt.get("cells", []), bool(dt.get("nested", False)),
                                             merges=dt.get("merges", []),
                                             images=_build_cell_images(dt, page, clean_path))))
    # 그림 블록 — clean_path 있으면 OCR로 안의 글자를 인식(§4-0 이슈⑨)
    for f in d_figs:
        page = int(f.get("page", 0))
        bbox = f.get("bbox")
        text = _ocr_figure(clean_path, page, bbox) if clean_path else None
        out.append(Block(FIGURE, page, text=text, bbox=bbox,
                         origin=(ORIGIN_OCR if text else ORIGIN_DOCLING), needs_semantic=True))

    # 수식/코드 블록 — 같은 페이지에서 pdf-inspector가 이미 뭉개서 넣어둔 PARAGRAPH 중
    # 내용이 겹치는 것을 먼저 제거(공백 무시 부분일치)한 뒤 FORMULA/CODE로 교체 추가.
    # 완전히 다른 텍스트까지 잘못 지우지 않도록, "겹치는 블록이 정확히 하나만 있을 때"만 제거한다.
    for d_text, block_type in ((d_formulas, FORMULA), (d_code, CODE)):
        for item in d_text:
            page = int(item.get("page", 0))
            text = item.get("text", "") or ""
            norm_new = _norm_ws(text)
            covered = [b for b in out
                       if b.type == PARAGRAPH and b.page == page and b.text
                       and norm_new and _norm_ws(b.text) in norm_new]
            partial = [b for b in out
                       if b.type == PARAGRAPH and b.page == page and b.text
                       and norm_new and norm_new in _norm_ws(b.text)
                       and _norm_ws(b.text) not in norm_new]
            if len(covered) == 1:
                out.remove(covered[0])
            elif len(covered) > 1:
                # ponytail: 텍스트 부분일치만 보는 중복 판정이라 후보가 2개 이상이면
                # 어느 걸 지울지 못 정해 전부 남긴다(중복 블록이 결과에 남는 게 천장).
                # bbox 겹침까지 같이 보면 확정 가능 — 아래 header/footer 경로도 동일.
                warnings.append(
                    f"p{page}: {block_type} 중복 후보 {len(covered)}개 — 자동 제거 보류")
            if partial:
                # 제거 조건(수정 2026-08-06): 문단이 "수식 + 서술"로 뭉쳐 있으면(새
                # 텍스트가 문단의 부분일 뿐이면) 서술까지 지우게 되므로 문단을 남긴다.
                warnings.append(
                    f"p{page}: {block_type} 텍스트가 문단에 포함돼 있으나 문단에 "
                    f"다른 내용도 있어 유지 — 중복 가능")
            out.append(Block(block_type, page, text=text, bbox=item.get("bbox"),
                             origin=ORIGIN_DOCLING))

    # 헤더/풋터 블록(개선②) — Docling 이 PAGE_HEADER/PAGE_FOOTER 로 분류한 텍스트를
    # section=SECTION_HEADER/FOOTER 를 단 PARAGRAPH 로 추가하고, pdf-inspector가 본문과
    # 구분 없이 만들어둔 같은 내용의 블록은 제거한다(예: "의뢰번호: SST-26-999"가
    # 페이지마다 본문에 반복 등장하던 문제, §4-0 개선②). 헤더/풋터 문구는 굵게·크게
    # 표시되는 경우가 많아 pdf-inspector 가 이걸 HEADING 으로 잘못 분류해두기도 해서
    # (실측 확인: 이 문서 3~4페이지) PARAGRAPH 뿐 아니라 HEADING 도 같이 검사한다.
    # 헤더/풋터 문구는 보통 짧아서 (norm_new in 기존블록) 방향만으로는 그 문구를 우연히
    # 포함한 훨씬 긴 무관한 블록까지 통째로 지울 위험이 있다 — 기존 블록이 헤더 텍스트의
    # 3배를 넘게 길면 그 방향은 매칭에서 제외해 과잉 삭제를 막는다.
    # 비교는 공백을 아예 다 지우고(_norm_ws 는 공백을 하나로 줄일 뿐 없애지는 않음) 한다 —
    # Docling이 조각을 이어붙이며 생기는 콜론 앞뒤 공백 차이("의뢰번호 : X" vs pdf-inspector
    # 원문 "의뢰번호: X") 때문에 부분일치가 실패하던 걸 실측으로 확인해서 반영.
    def _tight(s: str) -> str:
        return _norm_ws(s).replace(" ", "")

    for item in d_headers_footers:
        page = int(item.get("page", 0))
        text = item.get("text", "") or ""
        kind = item.get("kind", "header")
        norm_new = _tight(text)
        if not norm_new:
            continue
        matches = [b for b in out if b.type in (PARAGRAPH, HEADING)
                   and b.page == page and b.text and (
            _tight(b.text) in norm_new
            or (norm_new in _tight(b.text) and len(_tight(b.text)) <= len(norm_new) * 3)
        )]
        if len(matches) == 1:
            out.remove(matches[0])
        elif len(matches) > 1:
            warnings.append(f"p{page}: header/footer 중복 후보 {len(matches)}개 — 자동 제거 보류")
        section = SECTION_HEADER if kind == "header" else SECTION_FOOTER
        out.append(Block(PARAGRAPH, page, text=text, bbox=item.get("bbox"),
                         origin=ORIGIN_DOCLING, section=section))

    # 스캔 페이지: 표 영역과 겹쳐 표 처리에 이미 쓰인(consumed) OCR 줄은 flat 문단에서 제거.
    # 표 밖 줄(narrative 텍스트)만 남겨 문단으로 재구성 — Docling 표와 내용이 중복되지 않게.
    for page, idxs in consumed.items():
        if not idxs:
            continue
        remaining = [ln for i, ln in enumerate(ocr_lines_by_page[page])
                    if i not in idxs and (ln.get("text") or "").strip()]
        new_text = merge_wrapped_lines(relocate_stray_labels(remaining)) or None
        for b in out:
            if b.type == PARAGRAPH and b.page == page and b.origin == ORIGIN_OCR:
                b.text = new_text
        out = [b for b in out if not (b.type == PARAGRAPH and b.page == page
                                       and b.origin == ORIGIN_OCR and not b.text)]

    # §4-0 이슈⑦: pdf-inspector가 그 페이지에서 PARAGRAPH를 하나도 못 뽑았는데(주로 needs_ocr
    # 페이지가 빈 마크다운을 주는 경우, §4-0 이슈⑥) Docling은 do_ocr=False라도 진짜 벡터
    # 텍스트를 찾아낸 경우에만 보충한다 — 이미 문단이 있는 페이지는 절대 안 건드림(순수
    # 공백 채우기, docling_adapter._build_body_texts가 표 내용은 이미 걸러서 줌).
    pages_with_paragraph = {b.page for b in out if b.type == PARAGRAPH and b.text}
    for bt in d_body_texts:
        page = int(bt.get("page", 0))
        if page in pages_with_paragraph:
            continue
        text = bt.get("text", "") or ""
        if not text.strip():
            continue
        out.append(Block(PARAGRAPH, page, text=text, bbox=bt.get("bbox"), origin=ORIGIN_DOCLING))
        pages_with_paragraph.add(page)
    return out


def _pymupdf_cell_text(pg: fitz.Page, cell_bbox: tuple | None, page_h: float) -> str:
    """§4-0 이슈⑬-1: find_tables() 셀 bbox(top-left 원점) 안의 단어를 다시 뽑아
    cluster_lines+merge_wrapped_lines(§4-0 이슈⑦⑧ 재사용)로 줄바꿈 판정을 거쳐 합친다.
    cell_bbox 가 None 이거나(병합/빈 셀) 그 안에 단어가 하나도 없으면 빈 문자열 반환
    (호출 쪽에서 table.extract() 원본 값으로 폴백).

    **단어는 자르지 않고 중심점으로 배정한다(§4-0 이슈㉑, 2026-08-14)**: 예전에는
    `pg.get_text("words", clip=셀)` 로 뽑았는데, clip 은 경계에 걸친 단어의 **bbox 는
    원본 그대로** 두고 **텍스트만 잘라서** 돌려준다. find_tables() 가 열 경계를 단어
    한가운데로 그으면 양쪽 칸에 잘린 조각이 남았다 — 실측(SKN56_CDMS_RVVR_Rev05.pdf
    p22~25·36·38 평가표): "detail to show" → `"d il h"`, "Backup)" → `"B k )"`,
    "VR05-05" → `"VR05 05"`. 이 조각이 검토 본문에 실려 표현 점검이 수십 건의
    가짜 오타·용어불일치를 지적했다(§4-0 이슈⑳의 슬리버 칸 제거는 "칸 전체가
    잔여물"일 때만 잡아, 정상 단어와 조각이 섞인 칸은 통과했다).
    지금은 페이지 단어를 clip 없이 한 번 뽑아(페이지당 캐시) **단어 중심점이 든 칸에
    통째로** 배정한다 — 단어가 잘리는 일이 구조적으로 없다. 경계에 걸친 단어는 중심이
    있는 쪽 한 칸에만 들어가므로 이슈⑳의 잔여물도 애초에 생기지 않는다(좁은 여백
    칸은 어떤 단어의 중심도 못 품어 빈 칸이 된다)."""
    if not cell_bbox:
        return ""
    x0, y0, x1, y1 = cell_bbox
    words = _page_words(pg)
    words = [w for w in words
             if x0 <= (w[0] + w[2]) / 2 < x1 and y0 <= (w[1] + w[3]) / 2 < y1]
    items = [{"bbox": [w[0], page_h - w[1], w[2], page_h - w[3]], "text": w[4]} for w in words]
    if not items:
        return ""
    # 줄 끝 공백을 되살려서 넘긴다. `words` 는 단어를 잘라 주면서 그 공백을 버리는데,
    # 그 공백이 "단어가 끝났나 / 폭 때문에 한가운데서 끊겼나"를 가르는 유일한 신호다
    # (merge_wrapped_lines 의 trailing_space_known). 없으면 `Communication` 이
    # `Communicati on` 으로 갈라져 없는 용어 혼용이 지적된다(실측 13건).
    lines = _mark_line_endings(cluster_lines(items), _line_end_spaces(pg))
    return merge_wrapped_lines(relocate_stray_labels(lines), trailing_space_known=True)


def _page_words(pg) -> list:
    """페이지 단어 목록(clip 없음). 칸마다 clip 추출하면 단어가 잘리고(위 docstring)
    같은 페이지를 수십 번 파싱한다 — 한 번 읽어 캐시하고 칸 배정은 중심점으로 한다.

    **행 경계보다 먼저 단어 줄바꿈을 복원한다(§4-0 이슈㉓, 2026-08-14).**
    find_tables() 격자는 옆 열의 가로선을 병합 셀에도 연장해 가짜 행
    경계를 만든다. 그 경계가 ``Communicati``/``on``, ``Ba``/``ckup)``
    사이를 가르면 칸을 나눈 뒤에는 다시 합칠 근거가 없다. 그래서 PDF
    글자 흐름에서 '위 줄에 후행 공백 없음 + 다음 줄이 같은 x에서 인접'한
    첫/끝 단어를 먼저 한 단어로 합친 뒤, **첫 조각 좌표**로 칸에 한 번만
    배정한다. 실제 가로선 유무를 다시 추정하지 않고 PDF 자체의 공백
    신호를 쓰므로, 옆 열의 선이 이 칸을 가르는지와 무관하다."""
    doc = pg.parent
    if (_PAGE_WORDS_CACHE.get("doc") is not doc
            or _PAGE_WORDS_CACHE.get("page") != pg.number):
        try:
            words, consumed = _merge_wrapped_page_words(pg, list(pg.get_text("words")))
        except Exception:
            words, consumed = [], []
        _PAGE_WORDS_CACHE.clear()
        # doc 객체를 직접 보관한다. id(doc)만 두면 문서가 닫힌 뒤 Python이
        # 같은 id를 재사용해, 다른 PDF에 지난 PDF 단어를 내줄 수 있다.
        _PAGE_WORDS_CACHE.update({"doc": doc, "page": pg.number, "words": words,
                                  "consumed": consumed})
    return _PAGE_WORDS_CACHE["words"]


_PAGE_WORDS_CACHE: dict = {}


def _wrapped_line_pairs(lines: list[dict]) -> list[tuple[dict, dict]]:
    """후행 공백 없이 좌표가 같은 인접 원시 text-line 쌍.

    페이지 word 합치기와 pdf-inspector 평문 복구가 동일한 판정을 써야
    한쪽에서만 단어가 복원되는 불일치가 생기지 않는다.
    """
    pairs: list[tuple[dict, dict]] = []
    for prev in lines:
        prev_text = prev["text"]
        if not prev_text.strip() or prev["trailing_space"]:
            continue
        pb = prev["bbox_tl"]
        height = max(pb[3] - pb[1], 1.0)
        candidates = []
        for cur in lines:
            cb = cur["bbox_tl"]
            if cb[1] <= pb[1]:
                continue
            gap = cb[1] - pb[3]
            # 글꼴 bbox는 다음 기준선까지 아래로 내려가 인접 줄과 약간
            # 겹칠 수 있다(합성 PDF Helvetica 11pt 실측 0.21배). 기준선은
            # 다르고 x가 같은 조건이 이미 있으므로 0.3배까지만 허용한다.
            if not (-height * 0.3 <= gap <= height * 0.8):
                continue
            if abs(cb[0] - pb[0]) > height * 0.25:
                continue
            if not cur["text"].strip():
                continue
            candidates.append((max(gap, 0.0), abs(cb[0] - pb[0]), cur))
        if candidates:
            pairs.append((prev, min(candidates, key=lambda item: item[:2])[2]))
    return pairs


def _merge_wrapped_page_words(pg, words: list) -> tuple[list, list]:
    """PDF 원시 줄에서 단어 중간 줄바꿈을 한 word로 복원한다.

    PyMuPDF words 출력은 ``Communicati``/``on``을 두 word로 준다. 반면
    dict line은 위 줄의 후행 공백 유무를 보존하므로, 원문에 공백이
    없었다는 것을 확정할 수 있다. 이 함수는 좌표가 같고 세로로 바로 인접한
    줄 쌍만 다룬다. 앞 줄이 공백으로 끝나면 정상 단어 경계이므로 절대
    합치지 않는다.

    합친 word의 y 좌표는 첫 조각을 유지한다. 그래야 가짜 행 경계가 두
    조각 사이를 가라도 위/아래 칸에 각각 중복 배정되지 않는다.
    """
    if not words:
        return words, []
    lines = _page_text_lines(pg)
    pairs = _wrapped_line_pairs(lines)

    def word_in_line(w, line: dict) -> bool:
        x0, y0, x1, y1 = line["bbox_tl"]
        cx, cy = (w[0] + w[2]) / 2, (w[1] + w[3]) / 2
        return x0 - 0.5 <= cx <= x1 + 0.5 and y0 - 0.5 <= cy <= y1 + 0.5

    replacements: dict[int, tuple] = {}
    consumed: set[int] = set()
    for prev, cur in pairs:
        prev_match = re.search(r"(\S+)\s*$", prev["text"])
        cur_match = re.match(r"\s*(\S+)", cur["text"])
        if not prev_match or not cur_match:
            continue
        prev_tail, cur_head = prev_match.group(1), cur_match.group(1)
        # 문장부호/글자 경계만. 선·도형 조각은 단어로 합치지 않는다.
        if not (re.search(r"[\w가-힣)]$", prev_tail)
                and re.match(r"^[\w가-힣(]", cur_head)):
            continue
        prev_idxs = [i for i, w in enumerate(words)
                     if i not in consumed and w[4] == prev_tail and word_in_line(w, prev)]
        cur_idxs = [i for i, w in enumerate(words)
                    if i not in consumed and w[4] == cur_head and word_in_line(w, cur)]
        if not prev_idxs or not cur_idxs:
            continue
        prev_i = max(prev_idxs, key=lambda i: words[i][2])   # 위 줄의 마지막 word
        cur_i = min(cur_idxs, key=lambda i: words[i][0])     # 아래 줄의 첫 word
        if prev_i == cur_i:
            continue
        base = words[prev_i]
        merged = tuple([base[0], base[1], max(base[2], words[cur_i][2]), base[3],
                        prev_tail + cur_head, *base[5:]])
        replacements[prev_i] = merged
        consumed.add(cur_i)

    return ([replacements.get(i, w) for i, w in enumerate(words) if i not in consumed],
            [w for i, w in enumerate(words) if i in consumed])


def _cell_has_consumed_wrap(pg, cell_bbox: tuple | None) -> bool:
    """이 칸의 원래 word가 위 칸의 줄바꿈 단어로 흡수됐는지.

    흡수된 후속 조각만 있던 칸에서 `_pymupdf_cell_text` 결과는 빈 문자열이다.
    그때 table.extract() 폴백을 쓰면 ``ckup)`` 조각이 다시 살아나므로,
    이 신호가 있는 칸은 의도적 빈 칸으로 남겨야 한다.
    """
    if not cell_bbox:
        return False
    _page_words(pg)  # 캐시(흡수 목록 포함) 준비
    x0, y0, x1, y1 = cell_bbox
    return any(x0 <= (w[0] + w[2]) / 2 < x1 and y0 <= (w[1] + w[3]) / 2 < y1
               for w in _PAGE_WORDS_CACHE.get("consumed", []))


def _repair_wrapped_text(text: str, pairs: list[tuple[dict, dict]]) -> str:
    """pdf-inspector 평문에 남은 단어 중간 개행을 PDF 좌표 근거로 복원."""
    out = text
    for prev, cur in pairs:
        left, right = prev["text"].rstrip(), cur["text"].lstrip()
        if not left or not right:
            continue
        out = re.sub(re.escape(left) + r"[ \t]*\n[ \t]*" + re.escape(right),
                     lambda _m, merged=left + right: merged, out)
    return out


def _page_text_lines(pg) -> list[dict]:
    """PyMuPDF dict의 원시 text-line(좌표·후행 공백 보존), 페이지별 캐시."""
    doc = pg.parent
    if (_PAGE_LINES_CACHE.get("doc") is not doc
            or _PAGE_LINES_CACHE.get("page") != pg.number):
        lines: list[dict] = []
        try:
            got = pg.get_text("dict")
        except Exception:
            got = {}
        page_h = float(pg.rect.height)
        for block in got.get("blocks", []):
            for line in block.get("lines", []):
                text = "".join(span.get("text", "") for span in line.get("spans", []))
                bbox = line.get("bbox")
                if not text.strip() or not bbox:
                    continue
                x0, y0, x1, y1 = bbox
                lines.append({"text": text, "trailing_space": text[-1:].isspace(),
                              "bbox_tl": [x0, y0, x1, y1],
                              "bbox": [x0, page_h - y0, x1, page_h - y1]})
        _PAGE_LINES_CACHE.clear()
        _PAGE_LINES_CACHE.update({"doc": doc, "page": pg.number, "lines": lines})
    return _PAGE_LINES_CACHE["lines"]


def _line_end_spaces(pg) -> list[dict]:
    """이 페이지의 원시 text-line과 줄 끝 공백 신호.

    `get_text("words")` 는 단어 경계에서 잘라 그 공백을 버리지만 `"dict"` 의 span
    텍스트에는 남아 있다. 칸 배정·줄 묶기는 기존 단어 기반 경로를 그대로 두고
    (거기를 건드렸더니 칸에 걸친 줄이 통째로 빠져 한글이 113자 줄었다), 여기서는
    **신호만** 꺼내 얹는다.

    예전에는 '공백으로 끝난 원시 줄의 **문자열**'만 set으로 남겼다.
    Word PDF에서 같은 시각적 줄이 ``software `` / ``traceable to `` /
    ``software `` 세 text-line으로 나뉘면, words로 합쳐진
    ``software traceable to software``와 어느 set 원소도 같지 않아 공백이
    사라졌다. 이제 좌표까지 넘겨 합쳐진 줄의 **가장 오른쪽 원시
    조각**이 공백으로 끝났는지 판정한다.
    """
    return _page_text_lines(pg)


def _mark_line_endings(lines: list[dict], signals: list[dict]) -> list[dict]:
    """줄 끝에 공백이 있던 줄만 그 공백을 되살린다.

    `merge_wrapped_lines(trailing_space_known=True)` 가 읽는 신호가 이 공백이다 —
    있으면 단어가 끝난 것(공백으로 이음), 없으면 폭 때문에 단어 한가운데서 끊긴
    것(붙여 이음).
    """
    def overlap_ratio(a: list[float], b: list[float]) -> float:
        # BOTTOMLEFT bbox: [left, top, right, bottom]
        inter = max(0.0, min(a[1], b[1]) - max(a[3], b[3]))
        smaller = min(max(a[1] - a[3], 0.0), max(b[1] - b[3], 0.0))
        return inter / smaller if smaller > 0 else 0.0

    out = []
    for line in lines:
        text = line.get("text") or ""
        bbox = line.get("bbox")
        candidates = []
        if bbox:
            height = max(bbox[1] - bbox[3], 1.0)
            for signal in signals:
                sb = signal["bbox"]
                center_x = (sb[0] + sb[2]) / 2
                if not (bbox[0] - height * 0.25 <= center_x <= bbox[2] + height * 0.25):
                    continue
                if overlap_ratio(bbox, sb) < 0.5:
                    continue
                candidates.append(signal)
        # 같은 y의 조각이 여러 개면 합쳐진 줄의 마지막 word를 담은
        # 가장 오른쪽 조각이 줄 끝 공백을 결정한다.
        rightmost = max(candidates, key=lambda item: item["bbox"][2], default=None)
        if rightmost is not None and rightmost["trailing_space"]:
            text = text.rstrip() + " "
        out.append({**line, "text": text})
    return out


def _fill_missing_cell_bboxes(row_cell_bboxes: list[list[tuple | None]]) -> None:
    """find_tables() 가 일부 행에서만 잡은 셀 bbox 를 나머지 행에 채운다(§4-0⑬-2, in-place).

    bbox 가 실제로 잡힌 행에서 그 열의 x범위를 템플릿으로 가져와, 없는 행에는
    "그 행 자신의 y범위 + 템플릿 x범위"로 합성 bbox 를 만든다. 그 자리에 텍스트가
    없으면 `_pymupdf_cell_text` 가 빈 문자열을 주므로 안전하다.

    가드 2개(둘 다 절대 pt 가 아닌 상대비율, §4-0③과 같은 원칙):
      - 높이 비율 0.4~2.5배 밖 → 다른 행 구조(rowspan 등)로 보고 안 채움(§4-0⑬-2)
      - 같은 행의 실제 셀과 x가 50%↑ 겹침 → 그 넓은 셀이 이미 담고 있으므로 안 채움
        (§4-0⑬-5 — 이게 없으면 넓은 셀 안의 문장을 좁은 열 경계로 다시 잘라낸다)"""
    def x_overlap_ratio(a: tuple[float, float], b: tuple[float, float]) -> float:
        a0, a1 = a
        b0, b1 = b
        inter = max(0.0, min(a1, b1) - max(a0, b0))
        smaller = min(a1 - a0, b1 - b0)
        return inter / smaller if smaller > 0 else 0.0

    col_templates: dict[int, tuple[float, float, float]] = {}   # ci -> (x0, x1, 제공 행 높이)
    for row in row_cell_bboxes:
        for ci, cb in enumerate(row):
            if cb is not None and ci not in col_templates:
                col_templates[ci] = (cb[0], cb[2], cb[3] - cb[1])
    for row in row_cell_bboxes:
        ref = next((cb for cb in row if cb is not None), None)
        if ref is None:
            continue
        y_top, y_bot = ref[1], ref[3]
        row_h = y_bot - y_top
        real_x_ranges = [(cb[0], cb[2]) for cb in row if cb is not None]
        for ci in range(len(row)):
            if row[ci] is not None:
                continue
            tpl = col_templates.get(ci)
            if not tpl:
                continue
            x0, x1, src_h = tpl
            if src_h > 0 and row_h > 0 and not (0.4 <= row_h / src_h <= 2.5):
                continue   # 템플릿 제공 행과 높이가 너무 달라(rowspan 등) 다른 구조로 판단
            if any(x_overlap_ratio((x0, x1), rx) > 0.5 for rx in real_x_ranges):
                continue   # 이 행에 이미 그 영역을 덮는 실제(넓은) 셀이 있음 — 안 채움
            row[ci] = (x0, y_top, x1, y_bot)


def _bbox_area(bbox: list[float]) -> float:
    left, t, r, b = bbox
    return max(r - left, 0.0) * max(t - b, 0.0)


def _bbox_contains_ratio(outer: list[float], inner: list[float]) -> float:
    """inner bbox 가 outer bbox 안에 얼마나 들어있는지(교집합 면적 / inner 면적, 0~1) —
    둘 다 [l,t,r,b](BOTTOMLEFT)."""
    ol, ot, orr, ob = outer
    il, it, ir, ib = inner
    x0, x1 = max(ol, il), min(orr, ir)
    y0, y1 = max(ob, ib), min(ot, it)
    inter = max(x1 - x0, 0.0) * max(y1 - y0, 0.0)
    inner_area = _bbox_area(inner)
    return inter / inner_area if inner_area > 0 else 0.0


def _detect_column_bands(items: list[dict],
                         min_gap_ratio: float = 0.06) -> list[tuple[float, float]]:
    """items 의 x범위 합집합에서 열(column) 구간을 찾는다(§4-0⑯).

    각 항목 [x0,x1] 을 합쳐 나가다 남는 간격이 전체 폭의 min_gap_ratio 이상이면 열
    경계(gutter)로 본다 — 절대 pt 가 아닌 상대비율(§4-0③과 같은 원칙).
    단일 컬럼이면 구간 1개만 반환하고, 호출 쪽은 2개 미만이면 근거 부족으로 보고
    원문에 손대지 않는다."""
    with_bbox = [it for it in items if it.get("bbox")]
    if not with_bbox:
        return []
    left_edge = min(it["bbox"][0] for it in with_bbox)
    right_edge = max(it["bbox"][2] for it in with_bbox)
    width = right_edge - left_edge
    if width <= 0:
        return [(left_edge, right_edge)]
    min_gap = width * min_gap_ratio
    intervals = sorted((it["bbox"][0], it["bbox"][2]) for it in with_bbox)
    merged: list[list[float]] = []
    for left, r in intervals:
        if merged and left <= merged[-1][1] + min_gap:
            merged[-1][1] = max(merged[-1][1], r)
        else:
            merged.append([left, r])
    return [(left, r) for left, r in merged]


def _column_aware_text(items: list[dict]) -> str | None:
    """열마다 따로 위→아래로 읽어 왼쪽 열부터 이어붙인다(§4-0⑯).

    `cluster_rows`(→`reading_order`/`cluster_lines`가 의존)는 줄 단위로만 묶으므로,
    같은 y에 나란히 있는 다른 열의 내용을 한 줄로 뒤섞는다. 열별로 나눈 뒤에는 기존
    `cluster_lines`+`merge_wrapped_lines`를 그대로 재사용한다.
    pdf-inspector 의 읽기순서에 의존하지 않고 PyMuPDF words 의 bbox 만으로 다시
    조립하므로 상류가 뒤섞여 있어도 안전하다.
    열 경계가 없으면 None(근거 부족 → 호출 쪽이 원문 유지)."""
    bands = _detect_column_bands(items)
    if len(bands) < 2:
        return None
    col_texts: list[str] = []
    for left, r in bands:
        col_items = [it for it in items if left <= (it["bbox"][0] + it["bbox"][2]) / 2 <= r]
        if not col_items:
            continue
        lines = cluster_lines(col_items)
        text = merge_wrapped_lines(relocate_stray_labels(lines))
        if text.strip():
            col_texts.append(text.strip())
    return "\n".join(col_texts) if col_texts else None


def _fix_multicolumn_paragraphs(clean_path: str, blocks: list[Block],
                                scanned_pages: list[int]) -> None:
    """다단인데 열 구분 없이 뒤섞여 나온 문단을 PyMuPDF words 로 재구성한다(§4-0⑯, in-place).

    대상은 pdf-inspector 마크다운 문단(origin=ORIGIN_TEXT, bbox 없음)뿐 —
    scanned_pages 는 이미 OCR 경로가 읽기순서를 잡으므로 제외한다.
    열 경계가 2개 이상 확인될 때만 교체(근거 없으면 안 건드림, §4-0⑭⑮와 같은 원칙).
    이미 bbox 가 있는 표·헤더/풋터 영역의 words 는 빼서 중복을 막는다."""
    scanned = set(scanned_pages)
    exclude_by_page: dict[int, list[list[float]]] = {}
    target_by_page: dict[int, list[Block]] = {}
    for b in blocks:
        if b.page in scanned:
            continue
        if b.type == PARAGRAPH and b.origin == ORIGIN_TEXT and not b.bbox:
            target_by_page.setdefault(b.page, []).append(b)
        elif b.bbox and (b.type == TABLE or b.section in (SECTION_HEADER, SECTION_FOOTER)):
            # FIGURE 는 제외 대상에 넣지 않는다 — 배경/워터마크 그림 bbox 가 페이지
            # 대부분을 덮는 경우가 흔해서, 넣으면 words 가 통째로 걸러져 열 판정
            # 근거 자체가 사라진다(`_ocr_figure` 의 max_area_ratio 가드와 같은 문제).
            exclude_by_page.setdefault(b.page, []).append(b.bbox)
    if not target_by_page:
        return
    try:
        doc = fitz.open(clean_path)
    except Exception:
        return
    to_remove: set[int] = set()
    for page, para_blocks in target_by_page.items():
        if page >= doc.page_count:
            continue
        pg = doc[page]
        page_h = float(pg.rect.height)
        try:
            words = pg.get_text("words")
        except Exception:
            continue
        exclude = exclude_by_page.get(page, [])
        items = []
        for w in words:
            x0, y0, x1, y1, text = w[0], w[1], w[2], w[3], w[4]
            if not text.strip():
                continue
            bbox = [x0, page_h - y0, x1, page_h - y1]
            if any(_bbox_center_in(bbox, eb) for eb in exclude):
                continue
            items.append({"bbox": bbox, "text": text})
        new_text = _column_aware_text(items)
        if new_text is None:
            continue   # 열 경계 판정 근거 없음 — 안 건드림
        para_blocks[0].text = new_text
        for extra in para_blocks[1:]:
            to_remove.add(id(extra))
    doc.close()
    if to_remove:
        blocks[:] = [b for b in blocks if id(b) not in to_remove]


def _table_line_fragments(t: Block) -> list[str]:
    """표 블록의 셀 텍스트를 `\n` 단위 줄 조각으로 펼친다(3자 미만은 우연 일치 위험이
    커서 제외, §4-0 이슈⑬-6). `_drop_redundant_broad_tables`·`_attach_nested_table`
    둘 다 "이 표 내용이 다른 곳에 이미 있는지" 판정할 때 공유해서 쓴다."""
    frags: list[str] = []
    for row in t.table.cells:
        for cell in row:
            if not cell:
                continue
            frags.extend(p.strip() for p in cell.split("\n") if len(p.strip()) >= 3)
    return frags


def _trim_line_against_fragments(line: str, fragments: list[str]) -> str:
    """line 에서 fragments 에 있는 조각을 전부 지운(단어 붙음 방지를 위해 빈칸으로
    치환) 잔여 텍스트를 반환 — 완전히 겹치면 빈 문자열, 일부만 겹치면 안 겹치는
    부분만 남는다."""
    residual = line
    for frag in sorted(fragments, key=len, reverse=True):
        if frag in residual:
            residual = residual.replace(frag, " ")
    return " ".join(residual.split())


def _find_nested_table_pairs(bboxes: list[list[float] | None]) -> dict[int, int]:
    """포함 관계인 표 후보 쌍을 {안쪽_idx: 바깥쪽_idx} 로 반환한다(§4-0⑮).

    안쪽이 바깥쪽 안에 80% 이상 들어가고 바깥쪽이 더 클 때만 인정하며, 후보가
    여럿이면 가장 작게 감싸는 쪽을 부모로 고른다.
    §4-0⑩의 "조각 병합 안 함"과는 다른 문제다 — 그건 하나의 논리적 표가 쪼개진
    경우이고, 이건 표 안에 진짜 다른 표가 들어있어 관계만 표시하면 되는 경우다.

    **한계**: 3단 이상 중첩(부모의 부모)은 실제 근거가 없어 이 함수·호출부 모두
    검증되지 않았다 — 우연히 그런 페이지가 나와도 크래시는 안 나지만(개별 쌍 단위로만
    처리) 배치가 부정확할 수 있다."""
    parent: dict[int, int] = {}
    for i, ib in enumerate(bboxes):
        if not ib:
            continue
        best_j: int | None = None
        best_area: float | None = None
        for j, jb in enumerate(bboxes):
            if i == j or not jb:
                continue
            if _bbox_area(jb) <= _bbox_area(ib):
                continue
            if _bbox_contains_ratio(jb, ib) < 0.8:
                continue
            area = _bbox_area(jb)
            if best_area is None or area < best_area:
                best_j, best_area = j, area
        if best_j is not None:
            parent[i] = best_j
    return parent


def _is_undersegmented(existing_tables: list[Block], candidates: list[Block],
                       min_collapsed: int = 2) -> bool:
    """bbox 없는 pdf-inspector 표가 열을 뭉갰는지 find_tables() 결과와 대조 판정(§4-0⑰).

    find_tables() 가 **서로 다른 셀로 분리해 놓은 값**이 min_collapsed 개 이상
    pdf-inspector 의 **한 셀 안에** 들어가 있으면, 원래 여러 칸이던 걸 합친 것으로
    본다 — 추정이 아니라 두 엔진 결과의 문자열 포함 관계를 직접 대조하는 판정이다.
    조각은 `_table_line_fragments`(3자 이상)를 재사용하고, 두 엔진의 공백 표기 차이를
    흡수하려 양쪽 다 공백 정규화 후 비교한다.
    2개 이상을 요구하므로 정상적인 병합 셀이 우연히 긴 값을 갖는 경우로는 발동하지 않는다."""
    def norm(s: str) -> str:
        return " ".join(s.split())

    cand_frags = {norm(f) for c in candidates if c.table for f in _table_line_fragments(c)}
    cand_frags = {f for f in cand_frags if f}
    if len(cand_frags) < min_collapsed:
        return False
    for t in existing_tables:
        if not t.table:
            continue
        for row in t.table.cells:
            for cell in row:
                if not cell:
                    continue
                target = norm(cell)
                hits = {f for f in cand_frags if f != target and f in target}
                if len(hits) >= min_collapsed:
                    return True
    return False


def _attach_nested_table(parent: Block, parent_row_bboxes: list[list[tuple | None]],
                         page_h: float, child: Block) -> bool:
    """child 표를 parent 의 해당 칸에 `nested_tables` 로 붙인다(§4-0⑮).

    parent_row_bboxes 는 find_tables() 원본(top-left) 좌표라 여기서 BOTTOMLEFT 로
    변환해 child.bbox 와 포함 비율(80%↑)을 비교하고, 가장 잘 감싸는 칸을 고른다.
    자리를 찾으면 그 칸의 원문에서 child 와 겹치는 줄을 지운다(§4-0⑬-3과 같은 원칙) —
    안 그러면 구조화된 내용이 부모 칸에도 평문으로 남아 이중 기록된다.
    어느 칸에도 못 들어가면 False — 호출 쪽이 child 를 독립 평면 표로 남긴다(유실 없음)."""
    best_pos: tuple[int, int] | None = None
    best_ratio = 0.8
    for r_idx, row in enumerate(parent_row_bboxes):
        for c_idx, cb in enumerate(row):
            if not cb:
                continue
            x0, y0, x1, y1 = cb
            cell_bbox_bl = [x0, page_h - y0, x1, page_h - y1]
            ratio = _bbox_contains_ratio(cell_bbox_bl, child.bbox)
            if ratio >= best_ratio:
                best_pos, best_ratio = (r_idx, c_idx), ratio
    if best_pos is None:
        return False
    r, c = best_pos
    fragments = _table_line_fragments(child)
    if fragments and parent.table.cells[r][c]:
        lines = parent.table.cells[r][c].split("\n")
        remaining = [_trim_line_against_fragments(ln, fragments) for ln in lines]
        parent.table.cells[r][c] = "\n".join(ln for ln in remaining if ln).strip()
    parent.table.nested = True
    parent.table.nested_tables.append({"row": r, "col": c, "table": child.table})
    return True


def _build_pymupdf_table(t, pg: fitz.Page, page_h: float,
                         idx: int) -> tuple[Block, list[list[tuple | None]]] | None:
    """find_tables() 의 Table 객체 하나를 Block(TABLE)로 재구성(§4-0 이슈⑬-1⑬-2 로직) —
    `_pymupdf_gap_tables`의 평면 표 경로와 §4-0 이슈⑮의 중첩 표 경로가 공유한다.
    row_cell_bboxes(채움 후, find_tables() 원본 top-left 좌표)도 같이 반환한다 — 이슈⑮의
    중첩 표 소속 칸 판정(`_attach_nested_table`)에 필요."""
    try:
        raw_rows = t.extract()
    except Exception:
        return None
    if not raw_rows or not raw_rows[0]:
        return None
    row_cell_bboxes = [list(row.cells) for row in t.rows]
    _fill_missing_cell_bboxes(row_cell_bboxes)   # §4-0 이슈⑬-2
    cells: list[list[str]] = []
    for r_idx, row_bboxes in enumerate(row_cell_bboxes):
        raw_row = raw_rows[r_idx] if r_idx < len(raw_rows) else []
        row_cells: list[str] = []
        for c_idx, cb in enumerate(row_bboxes):
            fallback = ((raw_row[c_idx] or "").strip() if c_idx < len(raw_row) else "")
            rebuilt = _pymupdf_cell_text(pg, cb, page_h)
            # 후속 조각을 위 칸의 단어에 흡수해 의도적으로 빈 칸이 된
            # 경우는 extract() 폴백을 쓰지 않는다. 쓰면 ``ckup)``/``on``이
            # 다시 살아나 단독 오타 지적이 된다.
            row_cells.append(rebuilt if rebuilt or _cell_has_consumed_wrap(pg, cb)
                             else fallback)
        cells.append(row_cells)
    x0, y0, x1, y1 = t.bbox
    bbox = [x0, page_h - y0, x1, page_h - y1]   # top-left -> BOTTOMLEFT
    block = Block(TABLE, idx, bbox=bbox, origin=ORIGIN_TEXT,
                 table=TableData(rows=len(cells), cols=t.col_count, cells=cells))
    return block, row_cell_bboxes


def _drop_redundant_broad_tables(page_tables: list[Block]) -> list[Block]:
    """겹치는 넓은 표에서 좁은 표와 중복되는 줄만 지운다(§4-0⑬-3).

    find_tables() 는 같은 영역에 대해 "열 경계를 못 찾아 셀 1개로 뭉뚱그린 넓은 표"와
    "그 안을 잘게 쪼갠 좁은 표"를 동시에 내놓는 일이 있어 내용이 중복된다.

    동작:
      1. 각 표 a 에 대해, a 보다 작으면서 a 안에 80% 이상 들어가는 표 b 들을 찾는다
         (= a 가 b 를 통째로 다시 담고 있는 "넓은 표"인 상황).
      2. b 들의 셀 내용을 줄 조각으로 펼쳐, a 의 각 셀에서 그 조각들만 지운다.
      3. 지운 뒤 셀이 전부 비어버린 표만 결과에서 제외한다.

    **표를 통째로 버리면 안 된다** — 넓은 표에는 좁은 표 어디에도 없는 고유 내용이
    섞여 있을 수 있어서다(실측: "11.비고" 안내문). 그래서 표 단위가 아니라 줄 단위로
    지운다.
    조각 비교·트리밍은 `_table_line_fragments`/`_trim_line_against_fragments` 공용
    (3자 하한 — 2자까지 낮췄다가 "확인" 같은 흔한 단어가 무관한 문장에서 잘려나가는
    오탐이 나서 되돌림, §4-0⑬-6)."""
    out: list[Block] = []
    for a in page_tables:
        if not a.bbox or not a.table:
            out.append(a)
            continue
        nested_fragments: list[str] = []
        for b in page_tables:
            if b is a or not b.bbox or not b.table:
                continue
            if _bbox_area(b.bbox) >= _bbox_area(a.bbox):
                continue   # a 가 b 보다 작거나 같으면 a 는 "넓은 표" 후보가 아님
            if _bbox_contains_ratio(a.bbox, b.bbox) < 0.8:
                continue
            nested_fragments.extend(_table_line_fragments(b))
        if not nested_fragments:
            out.append(a)
            continue

        any_left = False
        for row in a.table.cells:
            for ci, cell in enumerate(row):
                if not cell:
                    continue
                lines = cell.split("\n")
                remaining = [_trim_line_against_fragments(ln, nested_fragments) for ln in lines]
                remaining = [ln for ln in remaining if ln]
                new_text = "\n".join(remaining).strip()
                row[ci] = new_text
                if new_text:
                    any_left = True
        if any_left:
            out.append(a)
    return out


def _pymupdf_gap_tables(clean_path: str, blocks: list[Block],
                        ocr_lines_by_page: dict[int, list[dict]] | None = None) -> list[Block]:
    """표가 없는 영역만 PyMuPDF `find_tables()` 로 보충한다(§4-0⑩).

    대상은 주로 needs_ocr 페이지다 — pdf-inspector 가 마크다운을 건너뛰고(§4-0⑥)
    Docling 도 do_ocr=False 라 구조를 못 잡는데, 정작 벡터 텍스트는 남아 있어
    find_tables() 가 OCR 없이 오타 없는 셀 값을 뽑아낸다.

    핵심 규칙:
      - 이미 표가 있는 자리는 안 건드리는 공백 채우기. 판정 단위는 페이지 전체가
        아니라 **기존 표 bbox**다(§4-0⑭).
      - find_tables() 가 논리적으로 하나인 표를 여러 조각으로 쪼개 줘도 **병합하지
        않고 각각 별도 TABLE 블록으로** 둔다(사용자 결정). merges/nested 는 판정
        신호가 없어 비워 둔다(§docling_adapter 의 "없는 신호는 내지 않는다" 원칙).
      - **좌표계 변환 필수**: find_tables() bbox 는 top-left 원점인데 이 프로젝트의
        나머지 bbox 는 전부 BOTTOMLEFT 다 — `page_height - y` 로 뒤집어 저장하지
        않으면 이후 bbox 를 쓰는 모든 판정이 어긋난다.
      - 새로 만든 표와 겹치는 OCR 줄은 소비 처리하고 그 페이지의 flat PARAGRAPH 를
        나머지 줄로 재구성한다 — 안 하면 같은 내용이 문단·표 양쪽에 남는다(§4-0⑪,
        `_fill_table_from_ocr` 와 같은 방식)."""
    ocr_lines_by_page = ocr_lines_by_page or {}
    # §4-0⑭: gap 판정을 페이지 단위 → 기존 표 bbox 단위로 정밀화. 페이지 단위로 보면
    # 작은 표 하나 때문에 같은 페이지의 겹치지도 않는 큰 영역까지 통째로 걸러진다.
    # bbox 없는 기존 표는 겹침을 판정할 좌표 자체가 없어 따로 모아 두고(unsafe_tables),
    # 아래에서 별도 근거가 확인될 때만 손댄다.
    existing_table_bboxes: dict[int, list[list[float]]] = {}
    unsafe_tables: dict[int, list[Block]] = {}   # bbox 없는 pdf-inspector 표(페이지별)
    for b in blocks:
        if b.type != TABLE:
            continue
        if b.bbox:
            existing_table_bboxes.setdefault(b.page, []).append(b.bbox)
        else:
            unsafe_tables.setdefault(b.page, []).append(b)
    unsafe_pages = set(unsafe_tables)
    try:
        doc = fitz.open(clean_path)
    except Exception:
        return []
    out: list[Block] = []
    consumed_by_page: dict[int, set[int]] = {}
    wrap_pairs_by_page: dict[int, list[tuple[dict, dict]]] = {}
    # bbox 없는 pdf-inspector 표를 find_tables() 결과로 교체하기로 한 페이지(§4-0⑮⑰)
    overridden_pages: set[int] = set()
    for idx in range(doc.page_count):
        pg = doc[idx]
        wrap_pairs_by_page[idx] = _wrapped_line_pairs(_page_text_lines(pg))
        try:
            found = pg.find_tables()
        except Exception:
            continue
        candidates = list(found.tables)
        if not candidates:
            continue
        page_h = float(pg.rect.height)
        existing = existing_table_bboxes.get(idx, [])

        cand_bboxes: list[list[float]] = []
        for t in candidates:
            x0, y0, x1, y1 = t.bbox
            cand_bboxes.append([x0, page_h - y0, x1, page_h - y1])   # top-left -> BOTTOMLEFT

        if idx in unsafe_pages:
            # 교체 근거 2가지 — 둘 다 "실측 신호가 있을 때만" 원칙:
            #   (§4-0⑮) 후보끼리 포함 관계가 있음 = pdf-inspector 마크다운이 표현할 수
            #           없는 표-안-표가 실재한다는 증거
            #   (§4-0⑰) 열을 뭉갠 게 문자열 포함 관계로 직접 확인됨(단순 2단 표는 위
            #           조건에 안 걸리므로 이쪽으로 잡는다)
            nested_parent = _find_nested_table_pairs(cand_bboxes)
            survivor_idx = list(range(len(candidates)))
            if not nested_parent:
                probe = [r[0] for r in
                         (_build_pymupdf_table(candidates[i], pg, page_h, idx)
                          for i in survivor_idx)
                         if r is not None]
                if not _is_undersegmented(unsafe_tables.get(idx, []), probe):
                    continue   # 근거 부족 — 기존처럼 페이지 전체를 안 건드림
            overridden_pages.add(idx)
        else:
            # margin_ratio=0(순수 기하 교차): 기본 0.15 는 OCR↔벡터 좌표 오차를 흡수하려
            # bbox 를 자기 크기만큼 부풀리는 값인데, 여기 둘은 같은 PDF 의 정확한 벡터
            # 좌표라 보정이 불필요하다. 그대로 쓰면 큰 표에서 마진이 수십 pt 로 부풀어
            # 안 겹치는 영역까지 겹친다고 오판한다.
            survivor_idx = [i for i, b in enumerate(cand_bboxes)
                            if not any(_bbox_overlaps(b, eb, margin_ratio=0.0) for eb in existing)]
            if not survivor_idx:
                continue
            survivor_set = set(survivor_idx)
            nested_parent = _find_nested_table_pairs(
                [b if i in survivor_set else None for i, b in enumerate(cand_bboxes)])

        built: dict[int, tuple[Block, list[list[tuple | None]]]] = {}
        for i in survivor_idx:
            result = _build_pymupdf_table(candidates[i], pg, page_h, idx)
            if result is not None:
                built[i] = result

        page_tables: list[Block] = []
        for i in survivor_idx:
            if i not in built:
                continue
            if i in nested_parent and nested_parent[i] in built:
                continue   # 부모 쪽에서 nested_tables로 흡수(아래) — 최상위로는 안 냄
            page_tables.append(built[i][0])
        children_by_parent: dict[int, list[int]] = {}
        for child_i, parent_i in nested_parent.items():
            if child_i in built and parent_i in built:
                children_by_parent.setdefault(parent_i, []).append(child_i)
        for parent_i, child_is in children_by_parent.items():
            parent_block, parent_rows = built[parent_i]
            for child_i in child_is:
                child_block, _ = built[child_i]
                if not _attach_nested_table(parent_block, parent_rows, page_h, child_block):
                    page_tables.append(child_block)   # 자리 못 찾음 — 안전 폴백(평면 표 유지)

        if not page_tables:
            continue
        # 아래 OCR 줄 소비에는 넓은 표까지 전부 쓰고(그래야 그 영역 줄이 flat 문단에
        # 안 남는다), 최종 출력에서만 중복 표를 뺀다 — "소비는 하되 블록으로는 안 남김"
        out.extend(_drop_redundant_broad_tables(page_tables))

        lines = ocr_lines_by_page.get(idx)
        if not lines:
            continue
        consumed: set[int] = set()
        # 새로 만든 표뿐 아니라 **이미 있던 표(existing)**와 겹치는 줄도 소비 처리해야
        # 한다(§4-0⑭) — 아래 재구성은 가공 전 ocr_lines_by_page 로 다시 계산하므로,
        # 안 그러면 `_apply_docling` 이 이미 지운 줄까지 되살려 문단에 도로 넣는다.
        for tbbox in [tb.bbox for tb in page_tables] + existing:
            for i, ln in enumerate(lines):
                if i in consumed or not ln.get("bbox"):
                    continue
                if _bbox_center_in(ln["bbox"], tbbox):
                    consumed.add(i)
        if consumed:
            consumed_by_page[idx] = consumed
    doc.close()

    for page, idxs in consumed_by_page.items():
        lines = ocr_lines_by_page.get(page) or []
        remaining = [ln for i, ln in enumerate(lines)
                    if i not in idxs and (ln.get("text") or "").strip()]
        new_text = merge_wrapped_lines(relocate_stray_labels(remaining)) or None
        for b in blocks:
            if b.type == PARAGRAPH and b.page == page and b.origin == ORIGIN_OCR:
                b.text = new_text
    # §4-0⑱: 위 재구성은 ORIGIN_OCR 문단만 대상이라, ORIGIN_TEXT 문단은 표와 같은 내용을
    # 담고도 그대로 남아 중복이 됐다. 이쪽은 줄 좌표가 없어 텍스트로만 비교하는데,
    # **줄 전체가 정확히 일치할 때만** 지운다 — 문단은 산문이라 부분 치환은 문장을
    # 훼손할 위험이 크고(§4-0⑬-6), 노리는 중복은 "셀 값이 통째로 한 줄"인 형태다.
    new_tables_by_page: dict[int, list[Block]] = {}
    for tb in out:
        new_tables_by_page.setdefault(tb.page, []).append(tb)
    for b in blocks:
        if b.type != PARAGRAPH or b.origin != ORIGIN_TEXT or not b.text:
            continue
        tables = new_tables_by_page.get(b.page)
        if not tables:
            continue
        # pdf-inspector 평문에는 표 내용이 줄단위로 중복되어 남는다.
        # 먼저 ``Communicati\non``같은 단어를 PDF 좌표로 복원해야
        # 아래 cell_values의 ``Communication``과 같아져 중복 제거도 동작한다.
        b.text = _repair_wrapped_text(b.text, wrap_pairs_by_page.get(b.page, []))
        cell_values = {" ".join(f.split())
                       for t in tables if t.table for f in _table_line_fragments(t)}
        kept = [ln for ln in b.text.split("\n") if " ".join(ln.split()) not in cell_values]
        b.text = "\n".join(kept).strip() or None

    blocks[:] = [b for b in blocks
                if not (b.type == PARAGRAPH and b.page in consumed_by_page
                        and b.origin == ORIGIN_OCR and not b.text)
                and not (b.type == PARAGRAPH and b.origin == ORIGIN_TEXT and not b.text)
                # 교체하기로 한 페이지의 bbox 없는 표만 제거 — bbox 있는(Docling 등으로
                # 확정된) 표는 같은 페이지라도 그대로 둔다(§4-0⑮⑰).
                and not (b.type == TABLE and b.page in overridden_pages and not b.bbox)]
    return out


# ---------------------------------------------------------------------------
# 워터마크
# ---------------------------------------------------------------------------
def _detect_watermarks(page_texts: list[str]) -> list[dict]:
    """§2-3 "본문 병합형 워터마크" 휴리스틱: 페이지 전체 텍스트에서 줄 단위로 뽑아,
    (a) 워터마크 키워드 사전에 걸리거나 (b) 전체 페이지의 절반 이상에서 반복되는 짧은
    줄(2~40자)을 후보로 낸다. parse_pdf() 가 각 페이지 원문(page_texts)을 다 모은 뒤
    마지막에 한 번 호출 — 확신 없으면 삭제하지 않고 meta.watermark_candidates 로만 표시."""
    n = len(page_texts)
    line_pages: dict[str, set[int]] = {}
    for i, txt in enumerate(page_texts):
        for raw in (txt or "").splitlines():
            s = raw.strip().lower().lstrip("# ").strip()
            if 2 <= len(s) <= 40:
                line_pages.setdefault(s, set()).add(i)
    # 버그 수정(2026-07-28): max(1, ...) 이면 n=2(2페이지 문서)일 때 half=1이 되어,
    # 딱 1페이지에만 등장한 줄도 "반복(repeated)"으로 오탐됐다(01/07/09번에서 실측 재현 —
    # 07번은 진짜 워터마크 외에 페이지 제목까지 워터마크 후보로 잘못 끼어듦).
    # "반복"은 최소 2개 페이지에 나와야 한다는 의미이므로 하한을 2로 올린다.
    half = max(2, (n + 1) // 2)
    cands = []
    for s, pages in line_pages.items():
        reasons = []
        if any(kw in s for kw in WATERMARK_KEYWORDS):
            reasons.append("keyword")
        if n >= 2 and len(pages) >= half:
            reasons.append("repeated")
        if reasons:
            cands.append({"text": s, "reasons": reasons, "pages": sorted(pages)})
    cands.sort(key=lambda c: "keyword" not in c["reasons"])
    return cands


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def parse_pdf(path: str | Path, password: str = "") -> DocumentModel:
    """doc_parser.parse_document() 가 .pdf 확장자에 대해 위임하는 최종 구현.

    복호화 평문 사본이 디스크에 남지 않도록 임시 디렉터리를 이 함수가 소유하고, 실제
    처리는 _parse_pdf_in() 에 위임한다. 중간에 어떤 경로로 반환/예외가 나도 finally 로
    정리된다(보호 문서의 권한 해제본이 out/ 아래 무기한 쌓이던 동작을 대체).
    """
    tmpdir = tempfile.mkdtemp(prefix="doc_parser_")
    try:
        return _parse_pdf_in(path, password, tmpdir)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _parse_pdf_in(path: str | Path, password: str, tmpdir: str) -> DocumentModel:
    """parse_pdf() 본체 — 이 파일 상단 docstring의 [A]~[E] 단계를 순서대로 실행하는
    오케스트레이터:
    [A] _normalize() 로 복호화 → [B] pdf-inspector 로 분류/추출(페이지별로 텍스트/OCR
    분기) → [C] DOCLING_HOOK 있으면 _apply_docling() 으로 표/그림 보강 →
    [E] DocumentModel 로 묶어서 반환.
    """
    path = str(path)
    name = Path(path).name
    clean_path, meta, warnings = _normalize(path, password, tmpdir)   # [A] 복호화 prestep
    if clean_path is None:
        return DocumentModel(name, meta, [], warnings)   # user-password 미인증 → 여기서 중단

    try:
        c = pi.classify_pdf(clean_path)            # [B] 페이지별 text/scanned/mixed 분류
        md = pi.extract_pages_markdown(clean_path)  # [B] 텍스트 페이지 마크다운 직접 추출
    except Exception as e:  # noqa
        warnings.append(f"pdf-inspector 오류: {e}")
        meta["pages"] = 0
        return DocumentModel(name, meta, [], warnings)

    meta.update({"pages": len(md.pages), "pdf_type": str(c.pdf_type),
                 "confidence": round(float(c.confidence), 3),
                 "is_complex": bool(md.is_complex),
                 "text_engine": TEXT_ENGINE})
    # pdf-inspector 의 인덱싱 혼용 quirk(§3-0-6): pages_needing_ocr 는 1-indexed 로 온다.
    # 이후 전부 0-indexed 로 통일해서 쓴다(이 변환을 빠뜨려서 실제 버그가 났던 이력 있음).
    ocr_pages = {p - 1 for p in list(md.pages_needing_ocr)}     # 1→0 idx

    blocks: list[Block] = []
    page_texts: list[str] = []
    scanned_pages: list[int] = []
    md_failed_pages: list[int] = []   # 스캔이 아니라 마크다운 추출만 실패한 페이지
    ocr_lines_by_page: dict[int, list[dict]] = {}   # _apply_docling 이 표 채우기/중복제거에 사용

    # needs_ocr 페이지가 진짜 스캔인지 "마크다운 추출만 실패한 텍스트 페이지"인지 가를
    # 기준선(_md_extract_failed 참조) — 마크다운이 정상적으로 나온 순수 텍스트 페이지들의
    # 원문 글자 수 중앙값. needs_ocr 페이지가 하나도 없으면 계산 자체를 건너뛴다(대부분의 문서).
    baseline: float | None = None
    if any(bool(pg.needs_ocr) or (pg.page in ocr_pages) for pg in md.pages):
        ok = [_text_volume(clean_path, pg.page) for pg in md.pages
              if (pg.markdown or "").strip()
              and not (bool(pg.needs_ocr) or (pg.page in ocr_pages))]
        baseline = statistics.median(ok) if ok else None

    # 스캔 페이지 OCR 병렬 선실행(이식 2026-08-06) — 라우팅 루프와 같은 판정
    # (needs_ocr && not md_failed)을 미리 계산해 진짜 스캔 페이지만 병렬 OCR 한다.
    # _md_extract_failed 를 페이지당 한 번 더 부르는 비용은 OCR(페이지당 수십 초)에
    # 비하면 무시 가능. # ponytail: 판정 로직 중복 — 루프 구조를 흔들지 않는 대가.
    _ocr_pre: dict[int, list | Exception] = {}
    if OCR_HOOK is not None:
        _scan_idxs = []
        for pg in md.pages:
            _needs = bool(pg.needs_ocr) or (pg.page in ocr_pages)
            if _needs and not _md_extract_failed(
                    _text_volume(clean_path, pg.page), baseline):
                _scan_idxs.append(pg.page)
        if len(_scan_idxs) > 1:
            _ocr_pre = _run_ocr_parallel(
                _scan_idxs,
                lambda i: OCR_HOOK(_render_page_png(clean_path, i), i) or [])

    # 페이지별 라우팅 루프 — [B] 단계의 핵심. 각 페이지를 스캔/텍스트 경로 중 하나로 분기한다.
    for pg in md.pages:
        idx = pg.page  # pdf-inspector: pg.page 는 0-indexed
        needs_ocr = bool(pg.needs_ocr) or (idx in ocr_pages)

        # pdf-inspector 가 needs_ocr 을 붙였어도 원문 텍스트가 멀쩡히 뽑히면 스캔이 아니라
        # 그 라이브러리의 마크다운 추출 실패다(실측 근거는 _md_extract_failed docstring).
        # 이 페이지는 OCR 대신 PyMuPDF 텍스트로 처리한다 — 전역 TEXT_ENGINE 은 안 건드린다.
        md_failed = needs_ocr and _md_extract_failed(_text_volume(clean_path, idx), baseline)
        if md_failed:
            needs_ocr = False
            md_failed_pages.append(idx)
            warnings.append(
                f"p{idx}: pdf-inspector 마크다운 추출 실패"
                f"(needs_ocr 사유={pg.ocr_reason or '없음'})이지만 원문 텍스트는 정상 추출됨"
                " — 스캔이 아니라 추출 실패로 보고 OCR 대신 PyMuPDF 텍스트 사용")

        if needs_ocr:
            scanned_pages.append(idx)
            # §4-0 이슈⑥: needs_ocr 페이지라도 원본에 정상 디코딩된 텍스트 조각이 섞여 있으면
            # 그건 OCR로 다시 읽지 않고 그대로 쓴다(신뢰 가능한 원문 우선, OCR은 나머지만 채움).
            reliable_lines = _reliable_text_items(clean_path, idx)
            # 스캔 경로 → PaddleOCR (register_ocr() 로 등록된 훅,
            # 보통 ocr_paddle.make_ocr_lines_hook())
            if OCR_HOOK is not None:
                try:
                    _got = _ocr_pre.get(idx)
                    if isinstance(_got, Exception):
                        raise _got            # 기존 except 경로가 페이지 warning 처리
                    raw_lines = (_got if _got is not None
                                 else OCR_HOOK(_render_page_png(clean_path, idx), idx) or [])
                    page_h = _page_height_pt(clean_path, idx)
                    ocr_lines = [{"bbox": (_px_bbox_to_pdf_pt(ln["bbox"], _OCR_DPI, page_h)
                                       if ln.get("bbox") else None),
                             "text": ln.get("text", "")} for ln in raw_lines]
                    # 신뢰 가능한 원문 조각과 겹치는 OCR 줄은 버린다(중복·재오인식 방지) —
                    # 겹치지 않는 줄(주로 배경 스캔 이미지 영역)만 원문과 합쳐 채택.
                    ocr_only = [ln for ln in ocr_lines if ln["text"].strip()
                               and not any(_bbox_overlaps(ln["bbox"], rb["bbox"])
                                           for rb in reliable_lines)]
                    with_bbox = [ln for ln in (reliable_lines + ocr_only) if ln.get("bbox")]
                    no_bbox = [ln for ln in ocr_only if not ln.get("bbox")]
                    lines = reading_order(with_bbox) + no_bbox
                    ocr_lines_by_page[idx] = lines
                    text = merge_wrapped_lines(relocate_stray_labels(lines))
                    if text.strip():
                        blocks.append(Block(PARAGRAPH, idx, text=text.strip(), origin=ORIGIN_OCR))
                    page_texts.append(text)
                except Exception as e:  # noqa
                    warnings.append(f"p{idx}: OCR 훅 오류 → {e}")
                    reliable_text = merge_wrapped_lines(relocate_stray_labels(reliable_lines))
                    if reliable_text.strip():
                        blocks.append(Block(PARAGRAPH, idx, text=reliable_text, origin=ORIGIN_TEXT))
                    page_texts.append(reliable_text)
            else:
                warnings.append(
                    f"p{idx}: OCR 필요({pg.ocr_reason or 'scanned'}) — PaddleOCR 훅 미설정")
                reliable_text = merge_wrapped_lines(relocate_stray_labels(reliable_lines))
                if reliable_text.strip():
                    blocks.append(Block(PARAGRAPH, idx, text=reliable_text, origin=ORIGIN_TEXT))
                page_texts.append(reliable_text)
            continue

        # 텍스트 경로 — 텍스트 엔진 폴백 게이트 결과(TEXT_ENGINE)에 따라 추출기만
        # 바뀌고 라우팅 구조는 동일
        if TEXT_ENGINE == "pymupdf" or md_failed:
            txt = _pymupdf_page_text(clean_path, idx)
            pblocks = [Block(PARAGRAPH, idx, text=txt, origin=ORIGIN_TEXT)] if txt else []
            # 표는 pdf-inspector 마크다운에서 유지
            pblocks += [b for b in _markdown_to_blocks(pg.markdown or "", idx) if b.type == TABLE]
        else:
            pblocks = _markdown_to_blocks(pg.markdown or "", idx)
        blocks.extend(pblocks)
        page_texts.append(pg.markdown or "")

    # 격자 레이아웃이 찢어놓은 절 제목 복구(§4-0 이슈㉒) — Docling 보강 전에,
    # 마크다운에서 온 블록 그대로일 때 신호를 본다.
    blocks = _rescue_split_headings(blocks)

    # [C] Docling 보강 (표 구조/그림) — register_docling() 으로 등록된 훅(보통
    # docling_adapter.make_docling_hook())이 있으면 문서 전체를 다시 한 번 Docling 으로
    # 변환해 표 구조·그림을 덮어씌운다. 없으면 마크다운 표를 "구조 미확정"으로만 남긴다.
    if DOCLING_HOOK is not None:
        try:
            rotated = _rotated_pages(clean_path)   # §4-0 이슈① — 이 페이지들은 Docling 표 무시
            blocks = _apply_docling(blocks, DOCLING_HOOK(clean_path), warnings, ocr_lines_by_page,
                                    rotated, clean_path)
        except Exception as e:  # noqa
            warnings.append(f"Docling 훅 오류: {e}")
    elif any(b.type == TABLE for b in blocks):
        # 마크다운 표는 이미 detected_only=True 로 나온다(_markdown_to_blocks.flush_table) —
        # 여기서는 왜 구조가 미확정인지만 알린다.
        warnings.append("표 구조(무선/병합/중첩)·그림 복원은 Docling 훅 필요(미설정)")

    # §4-0 이슈⑯: pdf-inspector 마크다운 문단이 다단 레이아웃을 열 구분 없이 뒤섞어
    # 낸 경우, 실측으로 확인 가능한 열 경계가 있는 페이지에 한해 PyMuPDF words로 재구성
    try:
        _fix_multicolumn_paragraphs(clean_path, blocks, scanned_pages)
    except Exception as e:  # noqa
        warnings.append(f"다단 레이아웃 재구성 오류: {e}")

    # 표가 없는 "영역"만 PyMuPDF find_tables() 로 보충(§4-0 이슈⑩, ⑭에서 페이지 단위 →
    # 표 bbox 단위로 정밀화)
    try:
        blocks.extend(_pymupdf_gap_tables(clean_path, blocks, ocr_lines_by_page))
    except Exception as e:  # noqa
        warnings.append(f"PyMuPDF find_tables() 오류: {e}")

    # [E] 공통 문서 모델로 최종 정규화 — 워터마크는 다 모인 page_texts 로 한 번에 판정
    meta["watermark_candidates"] = _detect_watermarks(page_texts)
    meta["scanned_pages"] = scanned_pages
    meta["md_extract_failed_pages"] = md_failed_pages
    meta["docling_used"] = DOCLING_HOOK is not None

    # 페이지 순서로 최종 정렬(§4-0 이슈⑫) — [B] 단계는 페이지 순서로 blocks 를 쌓지만,
    # [C] Docling 보강과 PyMuPDF gap-tables(§4-0 이슈⑩)는 새 블록을 자기 처리 순서대로
    # 리스트 "끝"에 그냥 추가하기만 해서, 실제로는 "어느 파이프라인 단계가 만들었는지"
    # 순서가 되어 있었다(페이지 순서 아님) — 평소엔 각 페이지의 원본 블록이 앞쪽에 남아
    # 있어 눈에 덜 띄었는데, 이슈⑪에서 한 페이지의 원본 문단이 표에 완전히 흡수돼 통째로
    # 사라지는 경우가 생기면서 그 페이지의 남은 내용이 리스트 끝으로 쏠려 순서가 크게
    # 어긋나는 게 실측으로 드러남(사용자 보고). `sorted()`는 안정 정렬이라 같은 페이지
    # 안에서는 기존 상대 순서를 그대로 유지한다.
    blocks = sorted(blocks, key=lambda b: b.page)
    return DocumentModel(name, meta, blocks, warnings)
