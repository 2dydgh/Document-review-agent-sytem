"""Claude LLM 어댑터 (스텁 — 백엔드/키 확정 후 구현)."""
from __future__ import annotations

from .base import Response


class ClaudeClient:
    def __init__(self, model: str = "claude-opus-4-8") -> None:
        self.model = model

    def complete(self, prompt: str, **opts) -> Response:
        raise NotImplementedError("Claude 클라이언트 미구현 — LLM 백엔드 확정 후 구현")
