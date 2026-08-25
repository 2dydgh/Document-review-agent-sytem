"""PaddleOCR 어댑터 — pdf_backend.OCR_HOOK 에 연결할 한국어 OCR.

pdf_backend.OCR_HOOK 시그니처: (img_bytes: bytes, page_index: int) -> list[dict]
    [{"bbox": [x0,y0,x1,y1] 픽셀좌표 | None, "text": str}, ...] (읽기순서 정렬됨)

bbox 를 같이 주는 이유: Docling 표 구조(스캔 페이지에서도 자체 셀 인식을 어느 정도
해내는 것으로 실측 확인됨)와 겹치는 줄을 pdf_backend._apply_docling() 이 골라내
표 셀 채우기/중복 제거에 쓴다.

연산 디바이스는 config.ocr_device()(= 환경변수 DOC_PARSER_DEVICE)에서 받아온다 —
이 모듈은 CPU/GPU 를 스스로 정하지 않는다.

PaddleOCR 3.x 는 API 가 여러 번 바뀌어(`ocr.ocr` vs `ocr.predict`, 반환 구조),
방어적으로 여러 형태를 처리한다. 실제 버전에 맞춰 test_api() 로 확인 가능.

사용(패키지를 어떤 이름으로 두든 동작하도록 패키지 기준 경로로 표기):
    from doc_parser import router
    from doc_parser.ocr_paddle import make_ocr_lines_hook
    router.register_ocr(make_ocr_lines_hook(lang="korean"))

merge_wrapped_lines() 는 OCR_HOOK 이 돌려준 줄 목록을 문단 텍스트로 합칠 때 pdf_backend.py
및 docx/hwp/hwpx/hwpml_backend.py 가 공통으로 쓰는 유틸(§4-0 이슈⑦) — 줄바꿈이 문서 폭
때문인지 진짜 문단 구분인지 bbox 로 판정한다.
"""
from __future__ import annotations

import io
import os
import re
from collections.abc import Callable

# paddlepaddle 3.x 의 PIR+oneDNN 실행기에서 발생하는
# NotImplementedError(ConvertPirAttribute2RuntimeAttribute ... onednn_instruction.cc)
# 회피용 플래그 — paddle import 전에 설정해야 한다.
os.environ.setdefault("FLAGS_use_mkldnn", "0")
os.environ.setdefault("FLAGS_enable_pir_in_executor", "0")
os.environ.setdefault("FLAGS_enable_pir_api", "0")

import numpy as np

from .config import ocr_device

_ENGINE = None
_LANG = "korean"


def _get_engine(lang: str):
    """PaddleOCR 엔진 인스턴스를 지연 생성 후 모듈 전역에 캐시(같은 언어면 재사용).
    파일 상단의 FLAGS_use_mkldnn 등 환경변수가 여기서 처음 import 되는 paddle 에 적용된다."""
    global _ENGINE, _LANG
    if _ENGINE is not None and _LANG == lang:
        return _ENGINE
    from paddleocr import PaddleOCR
    # 디바이스는 배포 설정에서 받아온다(DOC_PARSER_DEVICE). auto 면 키 자체를 넘기지 않아
    # PaddleOCR 의 자동 감지를 그대로 쓴다 — 여기서 CPU/GPU 를 판단하지 않는다.
    device = ocr_device()
    dev = {} if device is None else {"device": device}
    # 3.x 는 use_angle_cls 대신 use_textline_orientation. enable_mkldnn=False 로
    # oneDNN 실행기 우회. 파라미터 미지원 버전 대비 단계적 fallback.
    for kwargs in (
        dict(lang=lang, use_textline_orientation=True, enable_mkldnn=False, **dev),
        dict(lang=lang, use_textline_orientation=True, **dev),
        dict(lang=lang, use_angle_cls=True, **dev),
        dict(lang=lang, **dev),
    ):
        try:
            eng = PaddleOCR(**kwargs)
            break
        except TypeError:
            continue
    else:
        raise RuntimeError("PaddleOCR 초기화 실패(지원 파라미터 없음)")
    _ENGINE, _LANG = eng, lang
    return eng


def _bytes_to_ndarray(img_bytes: bytes) -> np.ndarray:
    """pdf_backend._render_page_png() 가 만든 PNG bytes를
    PaddleOCR 입력 형식(RGB ndarray)으로 변환."""
    from PIL import Image
    img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    return np.array(img)


def suppress_watermark(img: np.ndarray, darkness: int = 140,
                       color_tolerance: int = 30) -> np.ndarray:
    """스캔 페이지의 워터마크/도장을 지워 OCR 정확도 저하를 막는다.

    판정을 문자열이 아니라 **색 성질**로 해서 특정 워터마크 문구에 묶이지 않게 한다:
      - 무채색(R≈G≈B)이 아니면 지운다(빨간 도장·남색 로고바 등 — 채도 있는 색으로
        본문을 쓰는 한국어 공식 문서는 매우 드물다)
      - 무채색이어도 darkness 보다 밝으면(연함) 배경 워터마크로 보고 지운다
      - 무채색 + 어두움을 둘 다 만족해야 "진짜 잉크"로 남긴다
    이 판정이 일반적으로 통하는 근거는, 워터마크·도장을 본문과 시각적으로 구분되게
    만드는 것(옅게 하거나 다른 색을 쓰는 것) 자체가 워터마크의 정의에 가깝기 때문이다.

    지운 픽셀은 흰색으로 대체 — 이진화에 가까운 효과라 워터마크 없는 문서에도 해가
    되지 않는 표준적인 OCR 전처리다. 기본값은 실측 분포에서 여유를 두고 잡은 값이다."""
    img = img.astype(np.int16)
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    spread = np.maximum(np.maximum(r, g), b) - np.minimum(np.minimum(r, g), b)
    is_grayish = spread <= color_tolerance
    is_dark = np.minimum(np.minimum(r, g), b) <= darkness
    keep = is_grayish & is_dark
    out = np.full_like(img, 255)
    out[keep] = img[keep]
    return out.astype(np.uint8)


def _extract_lines(result) -> list[tuple[list[float] | None, str, float]]:
    """다양한 PaddleOCR 반환 구조(3.x predict()의 dict 형태 / 2.x ocr()의 중첩 list 형태)에서
    공통으로 (bbox=[x0,y0,x1,y1] 픽셀좌표, 텍스트, 신뢰도점수 0~1) 목록을 뽑아낸다.
    bbox 는 Docling 표 bbox(PDF pt)와 겹침을 비교하기 위해 pdf_backend 가 좌표 변환에 쓰고,
    score 는 ocr_lines() 가 저신뢰 노이즈(빈 서명란 오인식 등, §4-0 이슈⑧)를 거를 때 쓴다."""
    out: list[tuple[list[float] | None, str, float]] = []

    def _bbox_of(box) -> list[float] | None:
        try:
            xs = [pt[0] for pt in box]
            ys = [pt[1] for pt in box]
            return [float(min(xs)), float(min(ys)), float(max(xs)), float(max(ys))]
        except Exception:
            return None

    # --- 3.x predict(): list[dict] with 'rec_texts'/'rec_scores'/'dt_polys'
    if isinstance(result, list) and result and isinstance(result[0], dict):
        for page in result:
            texts = page.get("rec_texts") or page.get("rec_text") or []
            polys = page.get("dt_polys") or page.get("boxes") or []
            scores = page.get("rec_scores") or []
            for i, t in enumerate(texts):
                bbox = _bbox_of(polys[i]) if i < len(polys) else None
                score = float(scores[i]) if i < len(scores) else 1.0
                out.append((bbox, str(t), score))
        return out

    # --- 2.x ocr(): list[ list[ [box, (text, score)] ] ]
    if isinstance(result, list):
        for page in result:
            if not page:
                continue
            for line in page:
                try:
                    box, (text, score) = line[0], line[1]
                    out.append((_bbox_of(box), str(text), float(score)))
                except Exception:
                    # line 이 [box, text] 이거나 dict 인 경우(신뢰도 정보 없음)
                    if isinstance(line, (list, tuple)) and len(line) >= 2:
                        out.append((None, str(line[1]), 1.0))
        return out
    return out


def _y0(item: tuple[list[float] | None, str, float]) -> float:
    bbox = item[0]
    return bbox[1] if bbox else 0.0


# 실측(2026-08-04, "99. 일반성적서 예시.pdf" 빈 서명란 영역)으로 잡은 잠정 임계값 —
# 이 문서에서 진짜 텍스트(뭉개진 것 포함)는 전부 score>=0.753("=0스프트테크(" 같은
# 오인식도 포함)였고, 빈 서명란을 오인식한 노이즈("읽" 0.272, "(k)" 0.552,
# "T장 /클이" 0.295 등)는 전부 score<=0.660 이었다 — 둘 사이 0.66~0.753 구간이 비어
# 있어 0.7 을 경계로 잡음. 검증 문서 1건 기준이라 다른 문서/폰트에서 재조정 필요할 수 있음.
_MIN_SCORE = 0.7


def ocr_lines(img: np.ndarray, lang: str = _LANG) -> list[dict]:
    """이미지 1장을 OCR해 줄 단위 (bbox, text) 목록을 읽기순서(위→아래)로 정렬해 반환.
    make_ocr_lines_hook() 이 만드는 훅의 실제 처리부. bbox 가 없는 줄은 [] 로 표시(정렬용
    y=0 취급, pdf_backend 쪽에서 위치 매칭 없이 일반 텍스트로만 사용).

    신뢰도(score) < _MIN_SCORE 인 줄은 버린다(§4-0 이슈⑧) — 빈 서명란·얼룩·도장 자국처럼
    실제 텍스트가 없는 영역을 PaddleOCR이 억지로 글자로 읽어내는 노이즈 대응. 진짜 텍스트는
    인식이 다소 뭉개져도(오탈자) 이 임계값보다는 확연히 높은 점수가 나오는 것으로 실측
    확인됨(위 _MIN_SCORE 주석 참조) — 즉 "오인식"과 "노이즈"는 다른 문제이고, 이건 노이즈만
    거른다(오탈자 자체는 §4-0 이슈⑥/OCR 엔진 정확도의 별개 영역)."""
    eng = _get_engine(lang)
    # 3.x: predict / 2.x: ocr
    if hasattr(eng, "predict"):
        try:
            result = eng.predict(img)
        except Exception:
            result = eng.ocr(img)
    else:
        result = eng.ocr(img)
    items = _extract_lines(result)
    items.sort(key=_y0)  # 위→아래 읽기 순서
    return [{"bbox": bbox, "text": t} for bbox, t, score in items
           if t.strip() and score >= _MIN_SCORE]


def flip_bbox_y(lines: list[dict]) -> list[dict]:
    """PaddleOCR 원시 bbox(픽셀, top-left 원점: `bbox[1]`=위쪽 모서리가 `bbox[3]`=아래쪽
    모서리보다 작음, y 아래로 증가)를 `cluster_rows`/`reading_order`/`merge_wrapped_lines`
    /`relocate_stray_labels`가 기대하는 BOTTOMLEFT 방향 정렬 규약(`bbox[1]`이 커야 "위")
    으로 바꾼다. 절대 좌표는 의미 없어지고(페이지 높이를 모르므로 진짜 BOTTOMLEFT 좌표는
    아님) 오직 **상대적 위→아래 순서**만 맞추면 되는 이 4개 유틸 안에서만 쓸 것 —
    페이지 전체 좌표계와 맞춰야 하는 pdf_backend.py는 `_px_bbox_to_pdf_pt()`를 대신 쓴다.
    bbox 가 없는 항목(`None`)은 그대로 둔다."""
    out = []
    for ln in lines:
        bbox = ln.get("bbox")
        if bbox:
            x0, y0, x1, y1 = bbox
            ln = {**ln, "bbox": [x0, -y0, x1, -y1]}
        out.append(ln)
    return out


def cluster_rows(items: list[dict]) -> list[list[dict]]:
    """조각을 같은 줄(비슷한 y)끼리 묶어 위→아래로 정렬한 행 목록을 반환(행 안은 왼→오).

    `reading_order`/`cluster_lines` 의 공통 기반 — pdf_backend(§4-0⑥)와
    docling_adapter(§4-0⑦)가 공유한다.
    같은 줄 판정 허용치는 조각 높이의 0.6배 — 절대 pt 가 아닌 상대값이라 글자 크기가
    달라도 일반화된다(§4-0③과 같은 원칙).

    **bbox 는 반드시 BOTTOMLEFT**(bbox[1]=top 이 bbox[3]=bottom 보다 큼)여야 한다 —
    "큰 y 가 위쪽"으로 가정해 정렬하므로, PaddleOCR 원시 픽셀 bbox(top-left 원점)를
    그대로 넣으면 읽기순서가 통째로 뒤집힌다. 원시 bbox 를 쓰는 호출부는 `flip_bbox_y()`
    로 먼저 변환할 것(pdf_backend 는 `_px_bbox_to_pdf_pt()` 로 이미 변환해 넘긴다)."""
    def top(it: dict) -> float: return it["bbox"][1]
    def left(it: dict) -> float: return it["bbox"][0]
    def height(it: dict) -> float: return it["bbox"][1] - it["bbox"][3]

    ordered = sorted(items, key=lambda it: (-top(it), left(it)))
    rows: list[list[dict]] = []
    for it in ordered:
        row = next((r for r in rows
                    if abs(top(it) - top(r[0])) <= max(height(r[0]), height(it)) * 0.6), None)
        if row is not None:
            row.append(it)
        else:
            rows.append([it])
    rows.sort(key=lambda r: -top(r[0]))
    for row in rows:
        row.sort(key=left)
    return rows


def reading_order(lines: list[dict]) -> list[dict]:
    """{"bbox":[l,t,r,b], "text":...} 조각을 같은 줄끼리 묶어 위→아래·왼→오른쪽 순서로
    "정렬만"(병합은 안 함) — 출처가 다른 조각(예: 신뢰 텍스트 줄 + OCR 전용 줄)을 합칠 때
    쓴다(§4-0 이슈⑥). bbox 없는 항목은 호출 쪽에서 걸러내고 넘길 것."""
    out: list[dict] = []
    for row in cluster_rows(lines):
        out.extend(row)
    return out


def cluster_lines(items: list[dict], split_gap_ratio: float | None = None) -> list[dict]:
    """단어 단위 조각을 같은 줄끼리 병합해 한 줄 텍스트로 만든다(§4-0⑥⑦).

    PyMuPDF·Docling 의 단어 단위 결과를 OCR 줄과 같은 granularity 로 맞추는 용도
    (공백으로 join, bbox 는 합집합).

    `split_gap_ratio`(§4-0⑲): 지정하면 한 행 안이라도 단어 사이 간격이 글자 높이의
    이 배수를 넘으면 별개 줄로 쪼갠다 — 다단에서 라벨열과 내용열이 한 줄로 붙는 걸 막는다.
    임계 2.0 의 근거(실측): 일반 단어 간격은 글자 높이의 0.38~0.40배에 몰려 있고 열
    사이 틈은 3.4배 이상이라, 그 사이 1.5~3.0배는 표본이 없는 빈 구간이다. 절대 pt 가
    아닌 상대값이라 글자 크기가 달라도 일반화된다.
    기본값 None(=안 쪼갬) — 필요한 호출부에서만 켠다. 표 셀 내부처럼 "이미 한 칸으로
    확정된 영역"에 적용하면 셀을 또 쪼개므로 일괄 적용하지 않는다."""
    out: list[dict] = []
    for row in cluster_rows(items):
        groups: list[list[dict]] = [[row[0]]] if row else []
        for prev, cur in zip(row, row[1:]):
            gap = cur["bbox"][0] - prev["bbox"][2]
            height = max(cur["bbox"][1] - cur["bbox"][3], prev["bbox"][1] - prev["bbox"][3], 1.0)
            if split_gap_ratio is not None and gap > height * split_gap_ratio:
                groups.append([cur])
            else:
                groups[-1].append(cur)
        for group in groups:
            left = min(it["bbox"][0] for it in group)
            t = max(it["bbox"][1] for it in group)
            r = max(it["bbox"][2] for it in group)
            b = min(it["bbox"][3] for it in group)
            out.append({"bbox": [left, t, r, b],
                        "text": " ".join(it["text"] for it in group)})
    return out


# 실측 발견(2026-08-04, "99. 일반성적서 예시.pdf" p0 "11.비고" 재배치 실패로 확인): OCR은
# "11. 비고"(공백 있음)와 "11.비고"(공백 없음)를 뒤섞어 낸다 — 마커 뒤 공백을 필수로
# 요구하면 공백 없는 실제 마커를 놓친다. 그렇다고 공백 요구를 없애면 "37.5도씨" 같은
# 소수점 숫자를 마커로 오판하게 되므로, 숫자 마커(`\d+[.)]`)는 "바로 뒤에 또 숫자가
# 오면 안 됨"(전방탐색)으로 소수점과 구분한다 — 공백 유무와 무관하게 한글/영문/문장부호는
# 허용, 숫자만 배제(마커 뒤에 바로 숫자가 오는 실제 목록 항목은 못 봤음).
_LIST_MARKER_RE = re.compile(r"^(\d+[.)](?!\d)|[-•·▪]\s|[가-힣][.)]\s|[IVXivx]+[.)]\s)")


def _wrap_tolerances(rows: list[dict], right_ratio: float,
                     indent_ratio: float) -> tuple[float, float, float, float]:
    """`merge_wrapped_lines`/`relocate_stray_labels` 공통: (최대 오른쪽 끝, 최소 왼쪽 끝,
    오른쪽 허용오차, 왼쪽 들여쓰기 허용오차) — 전부 이 줄 묶음 안에서의 상대값."""
    with_bbox = [r for r in rows if r.get("bbox")]
    if not with_bbox:
        return 0.0, 0.0, 0.0, 0.0
    max_right = max(r["bbox"][2] for r in with_bbox)
    min_left = min(r["bbox"][0] for r in with_bbox)
    width = max(max_right - min_left, 1.0)
    return max_right, min_left, width * right_ratio, width * indent_ratio


def _is_wrap(prev: dict, cur: dict, max_right: float,
            right_tol: float, indent_tol: float) -> bool:
    """`prev` 다음의 `cur` 가 폭에 걸려 끊긴 줄바꿈(=이어붙일 것)인지 판정한다.
    `merge_wrapped_lines`/`relocate_stray_labels` 공통 핵심 판정.

    들여쓰기 비교 기준은 페이지 전체의 최소 왼쪽 끝이 아니라 **`prev` 자신의 왼쪽 끝**
    이다 — 2단 레이아웃에서 페이지 전체 기준을 쓰면 왼쪽 라벨열이 기준을 오염시켜,
    내용열 안에서 진짜로 이어지는 줄까지 "너무 들여써짐"으로 오판한다. prev 기준이면
    같은 열 안의 연속 여부만 보게 되고, 단일 컬럼에서는 어차피 결과가 같다."""
    prev_bbox, cur_bbox = prev.get("bbox"), cur.get("bbox")
    if not prev_bbox or not cur_bbox:
        return False
    if _LIST_MARKER_RE.match((cur.get("text") or "").strip()):
        return False
    return prev_bbox[2] >= max_right - right_tol and cur_bbox[0] <= prev_bbox[0] + indent_tol


def relocate_stray_labels(lines: list[dict], right_ratio: float = 0.08,
                          indent_ratio: float = 0.05) -> list[dict]:
    """2단 레이아웃에서 문장 중간에 끼어든 라벨을 문단 머리로 옮긴다(§4-0⑧).

    왼쪽 라벨열의 라벨이 오른쪽 내용열 중간 줄과 우연히 같은 y 에 있으면, y 기준
    읽기순서(`reading_order`)가 라벨을 문장 한가운데에 끼워 넣는다("...용도 이외의
    사용 / 11.비고 / 을 금합니다.").

    판정: 글머리/번호 마커 줄(`_LIST_MARKER_RE`)이면서, 그 줄을 빼면 앞뒤 줄이
    이어붙여졌을 조각(`_is_wrap`)이면 문단 머리로 옮긴다. 애매하면 그대로 둔다 —
    잘못 옮기는 것보다 안 옮기는 게 안전.

    **마커 없는 라벨은 여기서 처리하지 않는다(§4-0⑲에서 시도 후 기각).** 기하 조건으로
    같이 옮겨보려 했으나 되돌아갈 지점을 신뢰성 있게 제한할 방법이 없었다(범위를 좁히면
    엉뚱한 데서 끊기고, 넓히면 페이지 최상단까지 끌려 올라감). 근본 해결은 애초에 라벨과
    내용이 한 줄로 병합되지 않게 막는 `cluster_lines(split_gap_ratio=...)` 쪽이고,
    분리해두면 라벨이 자기 줄로 남아 재배치 자체가 불필요해진다."""
    rows = [ln for ln in lines if (ln.get("text") or "").strip()]
    n = len(rows)
    if n < 3:
        return rows
    max_right, min_left, right_tol, indent_tol = _wrap_tolerances(rows, right_ratio, indent_ratio)

    def is_wrap(a: int, b: int) -> bool:
        return _is_wrap(rows[a], rows[b], max_right, right_tol, indent_tol)

    targets: dict[int, int] = {}   # 원래 인덱스 -> 옮길 목표 인덱스(그 앞에 삽입)
    for i in range(1, n - 1):
        if not _LIST_MARKER_RE.match((rows[i].get("text") or "").strip()):
            continue
        if not is_wrap(i - 1, i + 1):
            continue
        start = i - 1
        while start > 0 and is_wrap(start - 1, start):
            start -= 1
        targets[i] = start
    if not targets:
        return rows

    insert_before: dict[int, list[dict]] = {}
    for orig_i, target in targets.items():
        insert_before.setdefault(target, []).append(rows[orig_i])
    out: list[dict] = []
    for idx, row in enumerate(rows):
        out.extend(insert_before.get(idx, []))
        if idx not in targets:
            out.append(row)
    return out


def merge_wrapped_lines(lines: list[dict], right_ratio: float = 0.08,
                        indent_ratio: float = 0.05,
                        trailing_space_known: bool = False) -> str:
    """줄 목록을 하나의 문단 텍스트로 합친다(§4-0⑦).

    각 줄이 "폭에 걸려 끊긴 줄바꿈"인지 "진짜 문단·항목 구분"인지 bbox 로 판정해,
    전자는 공백으로 잇고 후자만 `\\n`으로 남긴다 — 시각적 줄을 그냥 `\\n`으로 이어붙이면
    한 문장이 폭 때문에 두 줄이 된 것까지 잘려 나온다. PDF 스캔 페이지와 나머지 백엔드의
    임베드 이미지 OCR 캡션까지 5곳이 이 함수를 공유한다.

    이어붙이는 조건(둘 다 만족해야 함. 절대 pt/px 가 아니라 이 줄 묶음 안에서의 상대
    비율이라 여백·폰트가 달라도 일반화된다, §4-0③과 같은 원칙):
      - 이전 줄의 오른쪽 끝이 묶음의 최대 오른쪽 끝(열 폭 한계)에 가까움(right_ratio 이내)
      - 다음 줄의 왼쪽 시작이 묶음의 최소 왼쪽 끝(문단 기준선)에 가까움(indent_ratio 이내)
    글머리기호·번호매김으로 시작하는 줄은 폭 판정과 무관하게 항상 새 항목으로 본다.

    bbox 좌표계는 무관하다(x 만 쓰고 y 는 안 건드림) — 호출 쪽이 읽기순서로 정렬해
    넘기기만 하면 된다. 2단 라벨 재배치는 `relocate_stray_labels()` 담당이라, 필요하면
    이 함수보다 먼저 적용할 것.

    `trailing_space_known`: **줄 텍스트가 원문 그대로(줄 끝 공백까지) 실려 왔는가.**
    켜면 이어붙일 때 공백을 넣을지를 그 줄 끝 공백으로 정한다 — PDF 는 폭이 모자라면
    단어 **한가운데서도** 줄을 끊는데, 그때 공백을 끼워 이으면 멀쩡한 단어가 갈라진다
    (실측 SKN56 CDMS RVVR: `Communication` → `Communicati on` 13건. 검토자에게는 문서
    오탈자로 보이지만 문서는 멀쩡하고 우리가 깨뜨린 것이다). PDF 글자 흐름에는 그
    구분이 남아 있다:

        'Monitoring \n'    줄 끝 공백 있음 → 단어가 끝난 것    → 공백으로 잇는다
        'Communicati\non'  줄 끝 공백 없음 → 단어 중간에서 끊김 → 붙여 잇는다

    기본값이 False 인 이유: OCR 이 돌려주는 줄에는 그 공백이 없다(엔진이 줄 단위로
    인식해 붙여 준다). 거기서 이 규칙을 쓰면 멀쩡한 단어들이 통째로 들러붙는다 —
    신호가 **실제로 있는** 호출부만 켠다."""
    rows = [ln for ln in lines if (ln.get("text") or "").strip()]
    if not rows:
        return ""
    if not any(r.get("bbox") for r in rows):
        return "\n".join(r["text"].strip() for r in rows)
    max_right, min_left, right_tol, indent_tol = _wrap_tolerances(rows, right_ratio, indent_ratio)

    out: list[str] = [rows[0]["text"].strip()]
    for prev, cur in zip(rows, rows[1:]):
        cur_text = cur["text"].strip()
        if _is_wrap(prev, cur, max_right, right_tol, indent_tol):
            glue = " "
            if trailing_space_known and not (prev.get("text") or "")[-1:].isspace():
                glue = ""       # 단어 한가운데서 끊긴 줄 — 붙여야 원래 단어가 된다
            out[-1] = out[-1] + glue + cur_text
        else:
            out.append(cur_text)
    return "\n".join(out)


def ocr_ndarray(img: np.ndarray, lang: str = _LANG) -> str:
    """이미지 1장을 OCR해 읽기순서(위→아래)로 정렬한 텍스트로 합친다(줄바꿈으로 이어붙임,
    위치정보 없음). 개발용 확인 헬퍼(test_api)에서만 사용 — 실제 파이프라인은 ocr_lines() 사용."""
    return "\n".join(ln["text"] for ln in ocr_lines(img, lang=lang))


def make_ocr_lines_hook(lang: str = "korean", suppress_watermark_bg: bool = True
                        ) -> Callable[[bytes, int], list[dict]]:
    """doc_parser.register_ocr() 에 넘길 훅 팩토리(위치정보 포함 버전).
    호출 흐름: pdf_backend.parse_pdf() 가 스캔 페이지를 만나면 OCR_HOOK(png_bytes, page_idx)
    를 호출 → 여기서 만든 hook() → _bytes_to_ndarray() → (기본으로) suppress_watermark() →
    ocr_lines() → PaddleOCR 추론.
    반환값 [{"bbox":[x0,y0,x1,y1] 또는 None, "text":str}, ...] — pdf_backend 가 이 bbox 를
    Docling 표 bbox 와 대조해, 표 영역과 겹치는 줄은 표 셀 채우기/중복제거에 쓰고
    나머지만 일반 문단으로 남긴다.

    suppress_watermark_bg=True(기본값)면 OCR 직전에 suppress_watermark() 를 거쳐 옅은
    회색/채도 있는 워터마크·도장을 지운다 — 워터마크 없는 문서에도 해가 되지 않는
    표준적 이진화 계열 전처리라 기본으로 켜둔다. 비교·디버깅용으로 끌 수 있게 남겨둠."""
    def hook(img_bytes: bytes, page_index: int) -> list[dict]:  # noqa: ARG001
        img = _bytes_to_ndarray(img_bytes)
        if suppress_watermark_bg:
            img = suppress_watermark(img)
        return ocr_lines(img, lang=lang)
    return hook


def test_api(sample_png: str) -> None:
    """설치된 PaddleOCR 반환 구조를 눈으로 확인하는 헬퍼(개발용, 파이프라인에서는 미사용)."""
    from PIL import Image
    img = np.array(Image.open(sample_png).convert("RGB"))
    eng = _get_engine(_LANG)
    fn = "predict" if hasattr(eng, "predict") else "ocr"
    result = getattr(eng, fn)(img)
    print("call:", fn, "| top-type:", type(result).__name__)
    print(ocr_ndarray(img)[:300])
