"""실제 LLM 서버 연동 확인. 주소가 없으면 스스로 skip 한다.

    LLM_QWEN_URL=http://<서버>:9001/v1 \\
    LLM_OCR_URL=http://<서버>:9002/v1 \\
        pytest src/modules/llm_client -v

서버 쪽 smoke 검사가 통과해도 이쪽 설정이 틀리면 조용한 0건이 된다. 그 사이를
메우는 테스트다 — 모델 별칭(qwen·ocr)이 맞는지, 두 엔드포인트가 각자 응답하는지.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import pytest

from modules.llm_client import build_llm, build_vlm

QWEN_URL = os.environ.get("LLM_QWEN_URL", "").strip()
OCR_URL = os.environ.get("LLM_OCR_URL", "").strip()


@dataclass
class _Cfg:
    llm_provider: str = "local"
    llm_model: str = "qwen"
    llm_base_url: str = ""
    llm_timeout: float = 60.0
    llm_api_key: str = ""
    llm_thinking: bool = False
    llm_max_tokens: int = 64
    vlm_base_url: str = ""
    vlm_model: str = "ocr"


@pytest.mark.skipif(not QWEN_URL, reason="LLM_QWEN_URL 없음 (문서 검사용 서버 미설정)")
def test_qwen_endpoint_answers():
    llm = build_llm(_Cfg(llm_base_url=QWEN_URL,
                         llm_api_key=os.environ.get("LLM_API_KEY", "")))

    resp = llm.complete("한 단어로만 답하라. 대한민국의 수도는?")

    assert resp.error is None, f"서버 호출 실패: {resp.error}"
    assert resp.text.strip(), "빈 응답 — 별칭(--served-model-name)이 'qwen' 인지 확인"
    assert "서울" in resp.text


def _blue_png(w: int = 64, h: int = 64) -> bytes:
    """**순수 파랑** 한 장. 파일을 딸리지 않으려고 손으로 짠다.

    두 번 넘어졌다.
    1) 1x1 이나 잘라낸 base64 → 서버가 "broken data stream when reading image
       file"(HTTP 500)로 거절한다.
    2) 그라데이션(R 0→255, B 200) → 모델이 "보라"라고 답했다. 틀린 답이 아니라
       그림이 실제로 보라빛이었다. 색을 물어 확인하려면 색이 하나여야 한다.
    """
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)      # 8bit RGB
    rows = b"".join(b"\x00" + bytes([0, 0, 255]) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


@pytest.mark.skipif(not OCR_URL, reason="LLM_OCR_URL 없음 (그림 해석용 서버 미설정)")
def test_ocr_endpoint_reads_an_image():
    """이미지를 실제로 보고 답하는지 본다 — 파란 그림을 주고 색을 묻는다.

    "응답이 왔다"만 보면 이미지를 무시하고 아무 말이나 해도 통과한다. 내용을 물어야
    비전 탑까지 도달했는지 알 수 있다.
    """
    import base64

    data_uri = "data:image/png;base64," + base64.b64encode(_blue_png()).decode()
    vlm = build_vlm(_Cfg(vlm_base_url=OCR_URL,
                         llm_api_key=os.environ.get("LLM_API_KEY", "")))
    assert vlm is not None

    resp = vlm.chat([{"role": "user", "content": [
        {"type": "text", "text": "이 이미지의 주된 색을 한 단어로만 답하라."},
        {"type": "image_url", "image_url": {"url": data_uri}},
    ]}])

    assert resp.error is None, f"서버 호출 실패: {resp.error}"
    assert resp.text.strip(), "빈 응답 — 별칭이 'ocr' 인지, 비전 모델인지 확인"
    assert any(w in resp.text for w in ("파랑", "파란", "blue", "Blue")), \
        f"이미지를 못 본 것 같다: {resp.text[:80]!r}"


@pytest.mark.skipif(not (QWEN_URL and OCR_URL), reason="두 주소가 모두 필요")
def test_two_endpoints_are_not_the_same_server():
    """주소를 하나로 합쳐 두면 한쪽을 옮길 때 다른 쪽이 조용히 끊긴다."""
    assert QWEN_URL != OCR_URL
