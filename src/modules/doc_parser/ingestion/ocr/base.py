"""OCR 엔진 추상화 (스텁). 엔진 교체 가능하도록 인터페이스만 고정."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class OcrEngine(Protocol):
    def image_to_text(self, image_path: Path) -> str: ...
