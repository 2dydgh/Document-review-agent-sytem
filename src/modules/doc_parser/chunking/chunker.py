"""Document를 검토 단위 Chunk로 분할."""
from __future__ import annotations

from modules.shared import Chunk, Document


def chunk(doc: Document, max_chars: int = 4000) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in doc.iter_sections():
        text = (section.text or "").strip()
        if not text:
            continue
        pieces = [text[i:i + max_chars] for i in range(0, len(text), max_chars)]
        for n, piece in enumerate(pieces):
            chunks.append(Chunk(
                id=f"{section.id}#{n}",
                text=piece,
                anchor=section.anchor,
                section_id=section.id,
            ))
    return chunks
