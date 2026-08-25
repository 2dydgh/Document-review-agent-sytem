"""이미지 OCR 예약·병렬 실행.

원격 VL OCR 한 번이 5초쯤 걸린다. 이미지마다 차례로 기다리면 그 시간이 그대로
쌓인다 — 실측(AI시험인증1팀 산출물 폴더): 문서 14건에 이미지 24개, OCR 대기만 약
2분. 폴더 검토는 LLM 을 한 번도 안 부르는데 몇 분씩 걸리던 원인이 이것이었다.
"""
from __future__ import annotations

import threading
import time

from modules.doc_parser import ocr_batch
from modules.doc_parser.model import FIGURE, ORIGIN_OCR, ORIGIN_TEXT, Block


def _figure() -> Block:
    return Block(FIGURE, 0, text=None, origin=ORIGIN_TEXT, needs_semantic=True)


def _hook(lines):
    def hook(image_bytes: bytes, idx: int) -> list[dict]:
        return lines
    return hook


def test_예약한_블록에_인식_결과를_채운다():
    ocr_batch.begin()
    block = _figure()
    warnings: list[str] = []

    ocr_batch.schedule(block, b"img", warnings)
    ocr_batch.run(_hook([{"bbox": None, "text": "읽은 글자"}]))

    assert block.text == "읽은 글자"
    assert block.origin == ORIGIN_OCR
    assert warnings == []


def test_여러_이미지를_병렬로_돌린다():
    """순차면 합이 그대로 걸린다 — 이 테스트가 지키는 것은 '동시에 돈다'는 사실이다."""
    ocr_batch.begin()
    blocks = [_figure() for _ in range(4)]
    seen: list[str] = []

    def slow(image_bytes: bytes, idx: int) -> list[dict]:
        seen.append(threading.current_thread().name)
        time.sleep(0.25)
        return [{"bbox": None, "text": "x"}]

    for i, block in enumerate(blocks):
        ocr_batch.schedule(block, b"img", [])

    started = time.perf_counter()
    ocr_batch.run(slow)
    elapsed = time.perf_counter() - started

    assert all(b.text == "x" for b in blocks)
    assert len(set(seen)) > 1, "한 스레드에서 차례로 돌았다"
    assert elapsed < 0.9, f"순차(1.0초)에 가깝다: {elapsed:.2f}초"


def test_한_이미지가_실패해도_나머지는_채운다():
    """실패를 조용히 넘기지 않는다 — 그 이미지의 warnings 에 남기고 나머지는 살린다."""
    ocr_batch.begin()
    bad, good = _figure(), _figure()
    bad_warnings: list[str] = []

    def hook(image_bytes: bytes, idx: int) -> list[dict]:
        if image_bytes == b"bad":
            raise RuntimeError("연결 끊김")
        return [{"bbox": None, "text": "살아남음"}]

    ocr_batch.schedule(bad, b"bad", bad_warnings)
    ocr_batch.schedule(good, b"good", [])
    ocr_batch.run(hook)

    assert bad.text is None and bad.origin == ORIGIN_TEXT
    assert good.text == "살아남음"
    # 자리도 사유도 검토자가 읽을 수 있어야 한다 — 이 경고는 검토 결과 화면에
    # INFO·미검토 지적으로 그대로 뜬다.
    assert any("쪽 그림" in w and "연결 끊김" in w for w in bad_warnings), bad_warnings
    assert any("검토하지 않았습니다" in w for w in bad_warnings), bad_warnings


def test_훅이_없으면_예약을_버린다():
    """OCR 훅이 안 걸린 배포에서는 예약이 쌓이기만 하면 안 된다."""
    ocr_batch.begin()
    block = _figure()
    ocr_batch.schedule(block, b"img", [])

    ocr_batch.run(None)

    assert block.text is None
    ocr_batch.run(_hook([{"bbox": None, "text": "뒤늦게"}]))
    assert block.text is None, "버린 예약이 다음 실행에 되살아났다"


def test_begin_이_앞선_파싱의_예약을_비운다():
    """파싱이 중간에 터지면 예약이 남는다 — 다음 문서로 새면 남의 그림이 붙는다."""
    ocr_batch.begin()
    stale = _figure()
    ocr_batch.schedule(stale, b"img", [])

    ocr_batch.begin()          # 다음 문서 파싱 시작
    fresh = _figure()
    ocr_batch.schedule(fresh, b"img", [])
    ocr_batch.run(_hook([{"bbox": None, "text": "이번 문서"}]))

    assert fresh.text == "이번 문서"
    assert stale.text is None


# ── 반복 붕괴한 OCR 결과는 버린다 ────────────────────────────────────────────
# 실측(시험의뢰서 44KB 로고): 모델이 `SURESOFT` 를 9,216자까지 뱉으며 93초를 썼고,
# 그 글자가 `[그림 N: ...]` 로 검토 본문에 그대로 실렸다. 속도는 훅의
# frequency_penalty 가 잡고(93초→1.9초), 본문 오염은 여기서 막는다.


def test_같은_말만_되풀이한_결과는_버린다():
    ocr_batch.begin()
    block = _figure()
    warnings: list[str] = []
    ocr_batch.schedule(block, b"logo", warnings)

    ocr_batch.run(_hook([{"bbox": None, "text": "SURESOFT"} for _ in range(20)]))

    assert block.text is None, "되풀이한 글자가 본문에 실렸다"
    assert any("되풀이" in w and "쪽 그림" in w for w in warnings), warnings
    # 내부 id(docx rId·hwpx item id)는 검토자가 어느 그림인지 알 길이 없는 글자다.
    # 이 경고는 검토 결과 화면에 INFO·미검토 지적으로 그대로 뜬다.
    assert not any("rId" in w for w in warnings), warnings
    # 결론이 맨 앞이다 — "그래서 이 그림은 안 봤다"가 문장 끝에 있으면 안 읽힌다.
    assert warnings[0].startswith("1쪽 그림"), warnings[0]
    # "N번째 그림"은 안 쓴다 — 셀 수 있는 것은 OCR 예약에 성공한 그림뿐이라,
    # 앞에서 한 장이라도 건너뛰면 뒤 번호가 통째로 밀린다(ocr_batch.figure_label).
    assert "번째" not in warnings[0], warnings[0]
    # 되풀이된 낱말을 경고에 싣는다 — 자리만으로는 무슨 그림인지 알 수 없다.
    # "SURESOFT" 가 보이면 로고라는 게 그 자리에서 읽힌다.
    assert any("SURESOFT" in w for w in warnings), warnings


def test_깨진_변형_말고_제일_흔한_낱말을_싣는다():
    """반복 붕괴가 나면 낱말이 조금씩 어긋난 채 찍힌다.

    실측: 로고가 `SURESOFT` 하나인데 경고에는 `SURESOFT · URESOFTWARESOLUTIONS.COM`
    이 실렸다 — 둘째는 앞 글자 S 가 떨어진 같은 말의 깨진 변형이다. 그것이 대표로
    올라오면 검토자는 문서에 없는 글자를 찾게 되고, "같은 말"이라 해놓고 둘을
    나열하는 모순도 생긴다.
    """
    ocr_batch.begin()
    block = _figure()
    warnings: list[str] = []
    ocr_batch.schedule(block, b"logo", warnings)

    ocr_batch.run(_hook([{"bbox": None, "text": "SURESOFT"} for _ in range(18)]
                        + [{"bbox": None, "text": "URESOFTWARESOLUTIONS.COM"}]))

    assert block.text is None
    assert any("SURESOFT" in w for w in warnings), warnings
    assert not any("URESOFTWARESOLUTIONS.COM" in w for w in warnings), warnings
    # 낱말은 하나만 — 여럿을 이어 붙이면 "같은 말"이라는 문장과 어긋난다.
    assert not any(" · " in w for w in warnings), warnings


def test_한_줄에_되풀이해도_잡는다():
    ocr_batch.begin()
    block = _figure()
    ocr_batch.schedule(block, b"logo", [])

    ocr_batch.run(_hook([{"bbox": None, "text": "SURESOFT " * 30}]))

    assert block.text is None


def test_내용이_있는_그림은_그대로_남긴다():
    """실측(시험 설계서 77KB 구성도)에서 실제로 읽어 온 문장."""
    ocr_batch.begin()
    block = _figure()
    real = ("범례 무선: - - - - 유선: __________ 내부망 구성 가상 환경 구성 "
            "가상 환경 시험 PC WIFI 공유기 Internet 서버 PC 1")
    ocr_batch.schedule(block, b"figure", [])

    ocr_batch.run(_hook([{"bbox": None, "text": real}]))

    assert block.text == real


def test_짧은_결과는_버리지_않는다():
    """로고에서 낱말 서넛을 정직하게 읽은 것까지 버리면 안 된다."""
    ocr_batch.begin()
    block = _figure()
    ocr_batch.schedule(block, b"logo", [])

    ocr_batch.run(_hook([{"bbox": None, "text": "SURESOFT"}]))

    assert block.text == "SURESOFT"
