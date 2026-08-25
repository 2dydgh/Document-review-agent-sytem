"""그림 해석용 비전 모델 창구.

문서 검사용(build_llm)과 **다른 엔드포인트**다. 서버가 텍스트 모델과 비전 모델을
GPU 배치까지 달리해 따로 띄우므로, 주소를 하나로 합쳐 두면 한쪽을 옮길 때 다른
쪽이 끊긴다.
"""
from __future__ import annotations

from dataclasses import dataclass

from modules.llm_client import build_llm, build_vlm


@dataclass
class _Cfg:
    llm_provider: str = "echo"
    llm_model: str = ""
    llm_base_url: str = "http://text:9001/v1"
    llm_timeout: float = 30.0
    llm_api_key: str = ""
    llm_thinking: bool = False
    llm_max_tokens: int = 512
    vlm_base_url: str = ""
    vlm_model: str = "ocr"


def test_no_vlm_url_gives_none():
    """주소가 없으면 None 이다 — EchoLLM 을 대신 주지 않는다.

    빈 응답을 주면 "붙었는데 답이 없다"와 "아예 못 붙는다"가 구분되지 않는다.
    부르는 쪽은 None 을 보고 "그림 해석 안 했다"를 결과에 남겨야 한다.
    """
    assert build_vlm(_Cfg()) is None


def test_vlm_url_gives_client_on_that_endpoint():
    vlm = build_vlm(_Cfg(vlm_base_url="http://vision:9002/v1"))

    assert vlm is not None
    assert vlm.base_url == "http://vision:9002/v1"
    assert vlm.model == "ocr"          # 서버가 별칭으로 고정한 이름


def test_vlm_endpoint_is_separate_from_text_endpoint():
    cfg = _Cfg(llm_provider="local", llm_model="qwen",
               llm_base_url="http://text:9001/v1",
               vlm_base_url="http://vision:9002/v1")

    assert build_llm(cfg).base_url == "http://text:9001/v1"
    assert build_vlm(cfg).base_url == "http://vision:9002/v1"


def test_vlm_does_not_use_thinking():
    """그림 설명에 사고(reasoning)는 값어치 없이 시간만 먹는다."""
    assert build_vlm(_Cfg(vlm_base_url="http://vision:9002/v1",
                          llm_thinking=True)).thinking is False
