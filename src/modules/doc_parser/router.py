"""doc_parser.router — PDF·Word·HWP를 공통 문서 모델(장절·표·그림·위치)로 변환.

이 파일은 원래 doc_parser 패키지의 `__init__.py` 였다. 같은 모듈 안에 성격이 다른
파이프라인(`load_document`→`normalize`→`chunk`)이 이미 자리잡고 있고 그쪽 소비자가
`src/app`·`tests` 에 20곳 넘게 있어, 패키지 `__init__` 을 건드리지 않고 여기로 내렸다.
따라서 이 계열을 쓰는 쪽은 `from modules.doc_parser.router import parse_document` 처럼
서브모듈 경로로 가져온다.

**공개 인터페이스** (외부에서 사용하는 것은 여기서 export 하는 것만):
    parse_document(path, password="", ocr=True, docling=True) -> DocumentModel
    DocumentModel, Block, TableData        (공통 문서 모델)
    블록 타입 상수: HEADING, PARAGRAPH, TABLE, FIGURE, FORMULA, CODE
    register_ocr / register_docling        (엔진 훅 연결)
    set_text_engine(name)                  (텍스트 엔진 폴백 게이트 결과 반영)
    check_cid_quality(paths)               (텍스트 엔진 폴백 게이트 검사)

하류(下流) 소비자는 DocumentModel.blocks 를 Block.type 으로만 처리한다.
어느 경로(pdf-inspector/PaddleOCR/Docling/Qwen3-VL)로 왔는지는 알 필요가 없다.

의존성(이 모듈만 떼어갈 때): **쓰는 포맷의 것만 설치하면 된다.** 백엔드와 게이트는
    실제로 호출될 때 import 되므로, 예를 들어 HWPML 만 다루면 표준 라이브러리만으로 동작한다.
      PDF   → pdf-inspector, PyMuPDF     DOCX → python-docx
      HWPX  → python-hwpx                HWP5 → olefile          HWPML → (없음)
    선택: PaddleOCR(스캔/이미지 OCR), docling(표·구조), (Qwen3-VL 은 외부 연결).
"""
from __future__ import annotations

import importlib
import sys
from collections.abc import Callable
from pathlib import Path

from .model import (
    CODE,
    FIGURE,
    FOOTNOTE,
    FORMULA,
    HEADING,
    PARAGRAPH,
    SECTION_BODY,
    SECTION_FOOTER,
    SECTION_FOOTER_EVEN,
    SECTION_FOOTER_FIRST,
    SECTION_HEADER,
    SECTION_HEADER_EVEN,
    SECTION_HEADER_FIRST,
    TABLE,
    Block,
    DocumentModel,
    TableData,
)

__all__ = [
    "parse_document", "DocumentModel", "Block", "TableData",
    "HEADING", "PARAGRAPH", "TABLE", "FIGURE", "FORMULA", "CODE", "FOOTNOTE",
    "SECTION_BODY", "SECTION_HEADER", "SECTION_FOOTER",
    "SECTION_HEADER_FIRST", "SECTION_FOOTER_FIRST",
    "SECTION_HEADER_EVEN", "SECTION_FOOTER_EVEN",
    "register_ocr", "register_docling", "set_text_engine",
    # 아래 둘은 모듈 하단 __getattr__(PEP 562)이 지연 로드한다 — 정적으로는 안 보인다.
    # __init__.py 였을 때는 ruff 가 재export 로 봐주고 넘어갔지만 일반 모듈에서는 F822 다.
    "check_cid_quality", "GateResult",  # noqa: F822
]

_PDF_EXT = {".pdf"}
_DOCX_EXT = {".docx"}
_HWPX_EXT = {".hwpx"}
_HWP_EXT = {".hwp"}

# 백엔드별 필요 패키지 — import 실패 시 "무엇을 깔아야 하는지" 를 알려주는 데만 쓴다.
_BACKEND_REQUIRES = {
    "pdf_backend": ("PDF", "pdf-inspector, pymupdf"),
    "docx_backend": ("DOCX", "python-docx"),
    "hwpx_backend": ("HWPX", "python-hwpx"),
    "hwp_backend": ("HWP5", "olefile"),
    "hwpml_backend": ("HWPML", "표준 라이브러리만 — 이 오류는 모듈 파일 누락을 뜻한다"),
}

# register_* / set_text_engine 이 백엔드보다 먼저 호출될 수 있으므로 여기에 보관했다가
# 해당 백엔드가 처음 로드되는 시점에 반영한다.
_OCR_HOOK: Callable | None = None
_DOCLING_HOOK: Callable | None = None
_TEXT_ENGINE = "pdf-inspector"
_HOOKS_APPLIED: set[str] = set()


def _load_backend(name: str):
    """백엔드를 호출 시점에 import 한다.

    모듈을 폴더째 떼어갔을 때 **실제로 쓰는 포맷의 의존성만** 설치하면 되도록 하기 위함.
    예전처럼 이 파일 상단에서 5개를 전부 import 하면, HWPML(표준 라이브러리만 사용) 하나만
    쓰려 해도 python-docx·PyMuPDF·python-hwpx·olefile 이 전부 있어야 import 가 통과했다.
    """
    try:
        # __name__ 이 아니라 __package__ 다 — 이 파일이 패키지 __init__ 에서 서브모듈로
        # 내려오면서 __name__ 이 "...doc_parser.router" 가 됐고, 그걸 기준으로 하면
        # ".pdf_backend" 가 "...doc_parser.router.pdf_backend" 로 잘못 풀린다.
        backend = importlib.import_module(f".{name}", __package__)
    except ImportError as e:
        label, packages = _BACKEND_REQUIRES[name]
        raise ImportError(f"{label} 파싱에 필요한 의존성이 없습니다 ({packages}): {e}") from e
    if name not in _HOOKS_APPLIED:
        _HOOKS_APPLIED.add(name)
        _apply_pending_hooks(backend)
    return backend


def _apply_pending_hooks(backend) -> None:
    """register_* 로 미리 등록해둔 훅을 방금 처음 로드된 백엔드에 한 번만 반영한다.

    두 번 이상 덮어쓰지 않는 이유: 테스트가 백엔드 모듈의 OCR_HOOK 을 직접 monkeypatch 한 뒤
    parse_document() 를 부르는 패턴을 쓰는데, 매번 다시 꽂으면 그 스텁을 지워버린다.
    """
    if _OCR_HOOK is not None:
        backend.OCR_HOOK = _OCR_HOOK
    if _DOCLING_HOOK is not None and hasattr(backend, "DOCLING_HOOK"):
        backend.DOCLING_HOOK = _DOCLING_HOOK
    if hasattr(backend, "TEXT_ENGINE"):
        backend.TEXT_ENGINE = _TEXT_ENGINE


def _loaded_backend(name: str):
    """이미 로드된 백엔드만 돌려준다(없으면 None). 훅 등록이 import 를 유발하지 않게 하는 용도."""
    return sys.modules.get(f"{__package__}.{name}")


def __getattr__(name: str):
    """`check_cid_quality`/`GateResult` 지연 로드(PEP 562).

    gate.py 가 PyMuPDF·pdf-inspector 를 import 하므로, 8/1 게이트를 실제로 쓰지 않는
    소비자(예: HWPML 만 파싱)가 PDF 스택을 설치하지 않아도 되게 한다.
    """
    if name in ("check_cid_quality", "GateResult"):
        from . import gate
        return getattr(gate, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _default_ocr_hook():
    from .ocr_paddle import make_ocr_lines_hook
    return make_ocr_lines_hook(lang="korean")


def _ensure_ocr(backend) -> None:
    """이 백엔드에 OCR_HOOK 이 아직 없을 때만 기본 PaddleOCR 훅을 지연 등록한다.
    이미 register_ocr() 로 직접 등록했거나(커스텀 엔진 교체) 테스트가 스텁 훅을
    monkeypatch 해둔 경우는 덮어쓰지 않는다 — parse_document(ocr=True, 기본값) 가 호출."""
    if backend.OCR_HOOK is None:
        backend.OCR_HOOK = _default_ocr_hook()


def _default_docling_hook():
    from .docling_adapter import make_docling_hook
    return make_docling_hook()


def _ensure_docling(backend) -> None:
    """이 백엔드에 DOCLING_HOOK 이 아직 없을 때만 기본 Docling 훅을 지연 등록한다.
    OCR 과 같은 이유로 기본 켜짐(parse_document(docling=True, 기본값)) —

    docling 없이 돌린 결과를 실제 문서로 확인해보니(2026-08-04, "99. 일반성적서 예시.pdf")
    표 구조가 아예 안 잡히고 헤더/풋터가 본문에 섞여 나오는 등 품질 차이가 커서, 이걸
    매번 옵션으로 켜고 끄고 사용자가 판단하게 두는 건 "깜빡하고 안 켜서 나쁜 결과를
    받는" 실패를 만들기 쉽다고 판단 — OCR 처럼 기본 ON 으로 바꿔서 그 판단 자체를
    없앴다. 빠른 반복 개발 등으로 꼭 꺼야 하면 parse_document(docling=False) 로 명시."""
    if backend.DOCLING_HOOK is None:
        backend.DOCLING_HOOK = _default_docling_hook()


def parse_document(path: str | Path, password: str = "", ocr: bool = True,
                   docling: bool = True) -> DocumentModel:
    """확장자로 백엔드를 선택해 공통 문서 모델을 반환한다. 외부(run_poc.py 의 report.py)가
    호출하는 최상위 진입점.

    PDF 는 pdf_backend.parse_pdf() 로, DOCX 는 docx_backend.parse_docx() 로, HWPX 는
    hwpx_backend.parse_hwpx() 로 위임한다. `.hwp` 확장자는 실제로 두 가지 서로 다른 포맷이
    있어(실측으로 발견, 2026-08-03) 파일 앞부분을 먼저 봐서 판별한다 — OLE2 바이너리(HWP5)
    면 hwp_backend.parse_hwp(), 평문 XML(HWPML, 예: 국가법령정보센터가 배포하는 법률
    문서)이면 hwpml_backend.parse_hwpml() 로 위임. 표/병합/중첩표·문단 텍스트는 실제 샘플로
    검증됨(HWP5 3건·HWPML 1건), 각주/이미지/머리말꼬리말/수식/제목/다단은 백엔드별로
    구현·미검증 상태가 다르다 — 각 backend.py docstring 참조. password(암호화·배포용 문서
    복호화)는 HWP5 쪽만 탐지하고 실제 복호화는 아직 미구현.

    ocr=True(기본값)이면 이미지가 있는 문서를 만났을 때 PaddleOCR 이 자동으로 붙는다
    (register_ocr() 로 미리 커스텀 훅을 등록해뒀으면 그걸 그대로 쓰고 덮어쓰지 않음).
    회귀 테스트처럼 무거운 OCR 엔진 로딩을 원치 않으면 ocr=False 로 끈다.

    docling=True(기본값, PDF 전용)이면 Docling 이 자동으로 붙어 표 구조/헤더·풋터
    분리까지 된다 — 꺼두면 pdf-inspector 마크다운만으로 훨씬 거친 결과가 나온다
    (`_ensure_docling` docstring 참조). 회귀 테스트 등에서 무거운 모델 로딩을 피하려면
    docling=False.
    """
    ext = Path(path).suffix.lower()
    if ext in _PDF_EXT:
        backend = _load_backend("pdf_backend")
        if ocr:
            _ensure_ocr(backend)
        if docling:
            _ensure_docling(backend)
        return backend.parse_pdf(path, password)
    if ext in _DOCX_EXT:
        backend = _load_backend("docx_backend")
        if ocr:
            _ensure_ocr(backend)
        return backend.parse_docx(path)
    if ext in _HWPX_EXT:
        backend = _load_backend("hwpx_backend")
        if ocr:
            _ensure_ocr(backend)
        return backend.parse_hwpx(path)
    if ext in _HWP_EXT:
        # HWPML 판별이 먼저다 — 이쪽은 표준 라이브러리만 쓰므로 olefile 이 없어도 여기까지는 온다.
        hwpml = _load_backend("hwpml_backend")
        if hwpml.looks_like_hwpml(str(path)):
            if ocr:
                _ensure_ocr(hwpml)
            return hwpml.parse_hwpml(path, password)
        hwp5 = _load_backend("hwp_backend")
        if ocr:
            _ensure_ocr(hwp5)
        return hwp5.parse_hwp(path, password)
    raise NotImplementedError(f"아직 지원하지 않는 형식: {ext} (PDF/DOCX/HWPX/HWP 백엔드만 구현됨)")


# ---- 엔진 훅 등록 (공개) ----
# run_poc.py 가 --ocr/--docling 옵션에 따라 이 함수들로 실제 구현체(ocr_paddle.py,
# docling_adapter.py)를 pdf_backend 모듈의 전역 훅 변수에 꽂아 넣는다. 훅을 등록하지
# 않으면 pdf_backend.parse_pdf() 는 해당 단계를 건너뛰고 "미설정" 경고만 남긴다.
def register_ocr(hook: Callable[[bytes, int], str]) -> None:
    """OCR 훅 등록. hook(이미지 bytes, 0-idx 페이지번호/DOCX 는 미사용) -> 인식 텍스트.
    실사용: ocr_paddle.make_ocr_hook() 이 만든 PaddleOCR 래퍼를 여기에 연결.
    같은 훅을 pdf_backend(스캔 페이지)·docx_backend·hwpx_backend·hwp_backend·hwpml_backend
    (본문/표 셀 이미지)에 동시에 꽂는다 — 한 번만 등록하면 PDF/DOCX/HWPX/HWP/HWPML 전부
    이미지 OCR 이 켜진다.

    아직 로드되지 않은 백엔드는 여기서 import 하지 않고(설치 안 된 포맷 때문에 등록이
    실패하면 안 되므로) 보관만 해뒀다가 그 백엔드가 처음 쓰일 때 반영한다."""
    global _OCR_HOOK
    _OCR_HOOK = hook
    for name in _BACKEND_REQUIRES:
        backend = _loaded_backend(name)
        if backend is not None:
            backend.OCR_HOOK = hook


def register_docling(hook: Callable[[str], dict]) -> None:
    """표/그림 구조 복원 훅 등록. hook(복호화된 PDF 경로) -> {"tables":[...], "figures":[...]}.
    실사용: docling_adapter.make_docling_hook() 을 연결."""
    global _DOCLING_HOOK
    _DOCLING_HOOK = hook
    backend = _loaded_backend("pdf_backend")
    if backend is not None:
        backend.DOCLING_HOOK = hook


def set_text_engine(name: str) -> None:
    """"pdf-inspector"(기본) 또는 "pymupdf"(텍스트 엔진 폴백 게이트 실패 시).
    gate.check_cid_quality() 결과에 따라 run_poc.py 가 호출해 텍스트 추출 엔진만
    교체한다(라우팅 구조는 그대로 유지) — pdf_backend.parse_pdf 의 TEXT_ENGINE 분기 참조."""
    assert name in ("pdf-inspector", "pymupdf")
    global _TEXT_ENGINE
    _TEXT_ENGINE = name
    backend = _loaded_backend("pdf_backend")
    if backend is not None:
        backend.TEXT_ENGINE = name
