"""LLM 팩토리. LLM 호출 단일 창구 — provider 교체는 여기서.

창구는 둘이다. 문서 검사용 텍스트 모델(`build_llm`)과 그림·다이어그램 해석용
비전 모델(`build_vlm`)이다. 서버가 둘을 GPU 배치까지 달리해 따로 띄우므로
엔드포인트도 따로다 — 같은 주소로 합쳐 두면 한쪽을 옮길 때 다른 쪽이 끊긴다.
"""
from __future__ import annotations

from .base import EchoLLM, LLMClient, Response

__all__ = ["EchoLLM", "LLMClient", "Response", "build_llm", "build_vlm"]


def build_llm(config) -> LLMClient:
    provider = getattr(config, "llm_provider", "echo")
    if provider == "echo":
        return EchoLLM()
    if provider == "local":
        from .local import LocalClient
        return LocalClient(
            model=getattr(config, "llm_model", ""),
            base_url=getattr(config, "llm_base_url", "http://127.0.0.1:11434/v1"),
            timeout=getattr(config, "llm_timeout", 120.0),
            api_key=getattr(config, "llm_api_key", ""),
            thinking=getattr(config, "llm_thinking", False),
            max_tokens=getattr(config, "llm_max_tokens", 1024),
        )
    if provider == "claude":
        from .claude import ClaudeClient
        model = getattr(config, "llm_model", "")
        return ClaudeClient(model=model) if model else ClaudeClient()
    raise ValueError(f"알 수 없는 LLM provider: {provider}")


def build_vlm(config) -> LLMClient | None:
    """그림 해석용 비전 모델 창구. 주소가 없으면 **None** 이다.

    None 은 "그림 해석을 할 수 없다"는 뜻이고, 부르는 쪽은 그 사실을 결과에
    남겨야 한다 — 조용히 건너뛰면 그림 안의 내용을 검토한 것처럼 보인다.
    EchoLLM 을 대신 주지 않는 이유가 이것이다. 빈 응답은 "붙었는데 답이 없다"와
    구분되지 않는다.

    모델명은 서버가 --served-model-name 으로 고정한 별칭(기본 "ocr")이다.
    """
    base_url = getattr(config, "vlm_base_url", "")
    if not base_url:
        return None

    from .local import LocalClient
    return LocalClient(
        model=getattr(config, "vlm_model", "ocr"),
        base_url=base_url,
        timeout=getattr(config, "llm_timeout", 120.0),
        api_key=getattr(config, "llm_api_key", ""),
        thinking=False,          # 그림 설명에 사고는 값어치 없이 느리다
        max_tokens=getattr(config, "llm_max_tokens", 1024),
    )
