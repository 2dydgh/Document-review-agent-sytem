"""입력 어댑터 기반: RawDoc, Loader 프로토콜, 확장자 레지스트리."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass
class RawDoc:
    source_path: str
    text: str
    meta: dict = field(default_factory=dict)


class UnsupportedFormatError(Exception):
    pass


@runtime_checkable
class Loader(Protocol):
    extensions: tuple[str, ...]

    def load(self, path: Path) -> RawDoc: ...


# 조립 계층이 외부 파서(Loader 구현체)를 앞순위로 꽂는 자리 — 확장자가 겹치면
# 여기 것이 기본 로더보다 먼저 매칭된다. 모듈은 조립처를 모른 채 유지(CLAUDE.md).
EXTRA_LOADERS: list[Loader] = []


def _registry() -> list[Loader]:
    # 지연 임포트로 순환참조 방지
    from .docx import DocxLoader
    from .hwp import HwpLoader
    from .hwpx import HwpxLoader
    from .pdf_digital import PdfDigitalLoader
    from .pdf_ocr import PdfOcrLoader
    from .text import TextLoader

    return [*EXTRA_LOADERS, TextLoader(), PdfDigitalLoader(), PdfOcrLoader(),
            HwpxLoader(), HwpLoader(), DocxLoader()]


def load_document(path: Path) -> RawDoc:
    path = Path(path)
    ext = path.suffix.lower()
    for loader in _registry():
        if ext in loader.extensions:
            return loader.load(path)
    raise UnsupportedFormatError(f"지원하지 않는 확장자: {ext}")
