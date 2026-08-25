"""그림 해석 — `[그림 N]` 자리표시를 비전 모델 설명으로 채운다.

실서버 없이 도는 테스트다. 가짜 VLM 으로 배선(자리표시 치환 · 실패 처리 · 미검토
보고)을 검증한다. 실서버 확인은 src/modules/llm_client/tests/test_live_server.py.
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass

import pytest

from app.images import describe_images
from modules.doc_parser import RawDoc
from modules.llm_client import Response


@dataclass
class _FakeVLM:
    """호출된 프롬프트를 기록하고 정해진 답을 준다."""
    text: str = "네트워크 구성도. CDMS Server-P 와 IPS 가 연결된다."
    error: str | None = None
    calls: int = 0

    def chat(self, messages, **opts):
        self.calls += 1
        return Response(text=self.text, error=self.error)

    def complete(self, prompt, **opts):
        raise AssertionError("그림은 chat() 으로 보내야 한다(이미지 파트 때문)")


@pytest.fixture
def doc(tmp_path):
    """그림 두 장이 든 docx 하나와 그것을 가리키는 RawDoc."""
    p = tmp_path / "d.docx"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("word/media/image1.png", b"\x89PNG one")
        z.writestr("word/media/image2.png", b"\x89PNG two")
    return RawDoc(
        source_path=str(p),
        text="본문\n[그림 1: 사진]\n중간\n[그림 2]\n끝",
        meta={"format": "docx", "images": [
            {"no": 1, "name": "그림 1", "alt": "사진", "part": "word/media/image1.png"},
            {"no": 2, "name": "그림 2", "alt": "", "part": "word/media/image2.png"},
        ]})


def test_fills_both_placeholder_shapes(doc):
    """대체텍스트가 붙은 것(`[그림 1: 사진]`)과 번호만 있는 것 둘 다 채운다."""
    out = describe_images(doc, _FakeVLM())

    assert "[그림 1: 네트워크 구성도. CDMS Server-P 와 IPS 가 연결된다.]" in out.text
    assert "[그림 2: 네트워크 구성도. CDMS Server-P 와 IPS 가 연결된다.]" in out.text
    assert "[그림 1: 사진]" not in out.text      # 옛 대체텍스트는 남지 않는다
    assert out.meta["images_read"] == 2


def test_keeps_the_rest_of_the_body(doc):
    out = describe_images(doc, _FakeVLM())

    assert out.text.splitlines()[0] == "본문"
    assert "중간" in out.text
    assert out.text.splitlines()[-1] == "끝"


def test_no_vlm_leaves_text_untouched(doc):
    """주소가 없으면 아무것도 하지 않고, 읽지 않았다는 사실을 남긴다."""
    out = describe_images(doc, None)

    assert out.text == doc.text
    assert out.meta["images_read"] == 0


def test_server_error_leaves_placeholder_and_records_why(doc):
    """실패한 그림의 자리표시는 그대로 둔다 — 없는 설명을 지어내지 않는다."""
    out = describe_images(doc, _FakeVLM(text="", error="HTTP 500"))

    assert "[그림 1: 사진]" in out.text          # 원래 모습 그대로
    assert out.meta["images_read"] == 0
    assert all(im["error"] == "HTTP 500" for im in out.meta["images"])


def test_missing_image_part_does_not_kill_the_review(doc):
    """ZIP 에 없는 경로여도 예외로 올리지 않는다. 그림 하나가 검토 전체를 죽이면 안 된다."""
    doc.meta["images"][0]["part"] = "word/media/없는파일.png"

    out = describe_images(doc, _FakeVLM())

    assert out.meta["images_read"] == 1        # 두 번째는 읽혔다
    assert out.meta["images"][0]["error"]
    assert "[그림 1: 사진]" in out.text


def test_no_images_skips_the_model_entirely(tmp_path):
    """그림이 없으면 부르지 않는다 — 쓸데없이 2~3초를 쓰지 않는다."""
    raw = RawDoc(source_path=str(tmp_path / "x.docx"), text="본문",
                 meta={"format": "docx", "images": []})
    vlm = _FakeVLM()

    out = describe_images(raw, vlm)

    assert vlm.calls == 0
    assert out is raw


def test_long_description_is_capped(doc):
    """설명이 길면 본문이 그림 설명으로 뒤덮인다. 실측 응답은 1~3문장이었다."""
    out = describe_images(doc, _FakeVLM(text="가" * 2000))

    for line in out.text.splitlines():
        if line.startswith("[그림"):
            assert len(line) < 700


# ── 동시 호출 ────────────────────────────────────────────────────────────────
# 그림 한 장에 1.8~3.4초라 여러 장이면 준비 단계가 수십 초 걸린다. ocr 은 qwen 과
# 다른 엔드포인트·다른 GPU 라 동시에 보내도 문서 검사와 경합하지 않는다.
# 실측(IS24-GDL, 그림 6장 + 청크 33개): 순차 93.3초 → 동시 8 18.7초.

def test_descriptions_stay_matched_to_their_own_image(doc):
    """순서가 흔들리면 그림 2의 설명이 그림 1 자리에 들어간다."""
    class _PerImage:
        """어느 그림인지 바이트로 알아보고 그에 맞는 설명을 준다."""
        def chat(self, messages, **opts):
            uri = messages[0]["content"][1]["image_url"]["url"]
            import base64
            data = base64.b64decode(uri.split(",", 1)[1])
            return Response(text="첫째 그림" if b"one" in data else "둘째 그림")

    for _ in range(5):
        out = describe_images(doc, _PerImage(), concurrency=4)

        assert "[그림 1: 첫째 그림]" in out.text
        assert "[그림 2: 둘째 그림]" in out.text
        assert out.meta["images"][0]["description"] == "첫째 그림"
        assert out.meta["images"][1]["description"] == "둘째 그림"


def test_calls_run_concurrently(doc):
    import threading
    import time

    class _Slow:
        def __init__(self):
            self.peak = 0
            self._live = 0
            self._lock = threading.Lock()

        def chat(self, messages, **opts):
            with self._lock:
                self._live += 1
                self.peak = max(self.peak, self._live)
            try:
                time.sleep(0.05)
                return Response(text="설명")
            finally:
                with self._lock:
                    self._live -= 1

    vlm = _Slow()
    describe_images(doc, vlm, concurrency=2)

    assert vlm.peak == 2, f"동시에 안 돌았다: {vlm.peak}"


def test_default_is_sequential(doc):
    """concurrency 를 안 주면 옛 동작 그대로다."""
    import threading

    class _Watch:
        def __init__(self):
            self.peak = 0
            self._live = 0
            self._lock = threading.Lock()

        def chat(self, messages, **opts):
            with self._lock:
                self._live += 1
                self.peak = max(self.peak, self._live)
            try:
                return Response(text="설명")
            finally:
                with self._lock:
                    self._live -= 1

    vlm = _Watch()
    describe_images(doc, vlm)

    assert vlm.peak == 1
