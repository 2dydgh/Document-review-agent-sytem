"""스캔 PDF(OCR) 로더 (스텁). 명시 선택용이라 자동 확장자 매칭 없음."""
from __future__ import annotations

from pathlib import Path

from .base import RawDoc


class PdfOcrLoader:
    extensions: tuple[str, ...] = ()

    def load(self, path: Path) -> RawDoc:
        raise NotImplementedError("스캔 PDF(OCR) 로더 미구현 — OCR 엔진 확정 후 구현")
