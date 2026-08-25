"""텍스트/마크다운 로더 (실구현)."""
from __future__ import annotations

from pathlib import Path

from .base import RawDoc


class TextLoader:
    extensions = (".md", ".txt", ".markdown")

    def load(self, path: Path) -> RawDoc:
        text = Path(path).read_text(encoding="utf-8")
        return RawDoc(source_path=str(path), text=text, meta={"format": "text"})
