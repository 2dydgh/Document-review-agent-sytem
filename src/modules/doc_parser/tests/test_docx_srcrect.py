"""워드의 **자르기**(`<a:srcRect>`)를 OCR 에 반영한다.

워드에서 그림을 자르면 원본은 파일에 그대로 남고 `srcRect` 가 "이만큼은 안 보인다"
고만 적는다. 그걸 안 보면 **인쇄해도 안 나오는 글자**를 읽어 문서 내용으로 싣는다.

실측(SST-K-TP-7-04-01 제출물 확인증): 머릿말 레터헤드가 원본 1190×224 인데 문서는
`b="77151"` 로 위 51px(파란 띠)만 쓴다. 잘린 아래쪽에 대표·등록번호·전화·주소가
있고, OCR 이 그것을 읽어 머릿말 내용으로 실었다 — 검토자가 문서를 아무리 봐도
없는 문장이 지적의 근거로 떴다.

이 파일은 그 경계를 고정한다. 자르기 없는 그림은 그대로 다 읽어야 하고,
자른 그림은 보이는 부분만 읽어야 한다.
"""
from __future__ import annotations

from io import BytesIO

import pytest

from modules.doc_parser.docx_backend import _apply_crop

PIL = pytest.importorskip("PIL")
from PIL import Image  # noqa: E402


def _png(w: int, h: int) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (w, h), (10, 30, 80)).save(buf, format="PNG")
    return buf.getvalue()


def _size(data: bytes) -> tuple[int, int]:
    return Image.open(BytesIO(data)).size


def test_아래쪽을_자르면_위만_남는다() -> None:
    """실측값 그대로 — 1190×224 를 b=77.151% 로 자르면 1190×51 이다."""
    warn: list[str] = []
    got = _apply_crop(_png(1190, 224), (0.0, 0.0, 0.0, 0.77151), warn)
    assert _size(got) == (1190, 51)
    assert not warn


@pytest.mark.parametrize(("box", "want"), [
    ((0.0, 0.0, 0.0, 0.5), (100, 50)),     # 아래 절반
    ((0.0, 0.5, 0.0, 0.0), (100, 50)),     # 위 절반
    ((0.25, 0.0, 0.25, 0.0), (50, 100)),   # 좌우 4분의 1씩
    ((0.1, 0.1, 0.1, 0.1), (80, 80)),      # 사방
])
def test_네_방향을_다_반영한다(box, want) -> None:
    assert _size(_apply_crop(_png(100, 100), box, [])) == want


def test_보이는_것이_없으면_OCR_을_걸지_않는다() -> None:
    """전부 잘린 그림은 읽을 것이 없다. 빈 바이트를 돌려주면 호출부가 예약을 건너뛴다."""
    assert _apply_crop(_png(100, 100), (0.0, 0.0, 0.0, 1.0), []) == b""


def test_못_자르면_원본을_쓰되_사실을_남긴다() -> None:
    """자르기 실패로 그림을 통째로 버리지 않는다. 다만 조용히 넘기지도 않는다 —
    안 보이는 글자가 섞일 수 있다는 것을 검토자가 알아야 한다."""
    warn: list[str] = []
    got = _apply_crop(b"not an image", (0.0, 0.0, 0.0, 0.5), warn)
    assert got == b"not an image"
    assert warn and "보이지 않는 글자가 섞일 수 있습니다" in warn[0]
