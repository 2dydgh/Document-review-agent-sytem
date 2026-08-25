"""문서 안 이미지 OCR 을 모아 한 번에 병렬로 돌린다.

원격 VL OCR 한 번이 5초쯤 걸린다. 이미지마다 차례로 기다리면 그 시간이 그대로
쌓인다 — 실측(AI시험인증1팀 산출물 폴더): 문서 14건에 이미지 24개, **OCR 대기만
약 2분.** 폴더 검토는 LLM 을 한 번도 안 부르는데도 몇 분씩 걸리던 원인이 이것이다.
호출은 서로 독립이라 병렬이 곧 처리량이고, `pdf_backend` 가 스캔 페이지 OCR 에
이미 같은 방식을 쓴다(`_run_ocr_parallel`).

순회 코드를 갈아엎지 않으려고 **예약 → 나중에 채움**으로 만들었다. 순회 중에는
빈 FIGURE 블록만 만들어 두고 바이트를 예약했다가, 파싱이 끝난 뒤 한 번에 돌려
블록의 `text` 를 채운다(`Block` 은 가변 dataclass 다).

예약은 **스레드마다 따로** 모은다 — 문서 둘을 동시에 파싱해도 서로의 예약을
건드리지 않는다. `begin()` 이 시작을 알리고 `run()` 이 비우므로, 파싱이 중간에
터져도 다음 파싱에 남은 예약이 새지 않는다.
"""
from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from .model import ORIGIN_OCR, Block
from .ocr_paddle import flip_bbox_y, merge_wrapped_lines, reading_order, relocate_stray_labels

# pdf_backend._OCR_WORKERS 와 같은 값. 원격 VL(vLLM)은 배치 처리라 병렬이 곧 처리량이다.
# 로컬 PaddleOCR 훅으로 바꾸면 엔진이 스레드 안전하지 않을 수 있다 — 그때는 1 로 내린다.
_WORKERS = 4

_local = threading.local()

# 반복 붕괴 판정 문턱. 낱말이 이만큼 이상인데 서로 다른 낱말이 이 비율 이하면
# 읽은 것이 아니라 되풀이한 것으로 본다.
_DEGEN_MIN_WORDS = 12
_DEGEN_DISTINCT_RATIO = 0.15


def _looks_degenerate(lines: list[dict]) -> bool:
    """모델이 같은 말을 되풀이하다 끝난 결과인가.

    실측(시험의뢰서 44KB 로고): `SURESOFT` 만 9,216자. 이 글자는 그림 블록을 거쳐
    `[그림 N: ...]` 로 **검토 본문에 그대로 실린다** — 표현 점검 LLM 이 그 쓰레기를
    읽는다. frequency_penalty 로 길이는 잡았지만(93초→1.9초) 짧아진 결과도 여전히
    되풀이라, 본문에 넣기 전에 여기서 버린다.

    낱말 기준으로 본다 — 한 줄에 `A A A ...` 로 오든 여러 줄에 `A\\nA\\nA` 로 오든
    같은 실패다. 문턱을 낮게(12낱말) 두지 않는 이유: 로고에서 낱말 서넛을 정직하게
    읽은 짧은 결과까지 버리게 된다.
    """
    words = " ".join((ln.get("text") or "") for ln in lines).split()
    if len(words) < _DEGEN_MIN_WORDS:
        return False
    return len(set(words)) <= max(2, int(len(words) * _DEGEN_DISTINCT_RATIO))


def _repeated_word(lines: list[dict]) -> str:
    """가장 많이 나온 낱말 하나. 경고에 실어 **어느 그림인지 사람이 알아보게** 한다.

    되풀이된 낱말이 `SURESOFT` 하나면 로고라는 게 그 자리에서 보인다.

    **하나만 싣는다.** 예전에는 처음 나온 차례로 서로 다른 낱말 셋까지 이어
    붙였는데, 반복 붕괴가 나면 낱말이 조금씩 어긋난 채 찍힌다 — 실측에서
    `SURESOFT · URESOFTWARESOLUTIONS.COM` 이 나왔다(둘째는 앞 글자 S 가 떨어진
    같은 말의 깨진 변형이다). 그 변형이 대표로 올라오면 검토자는 문서에 없는
    글자를 찾게 되고, "같은 말"이라 해놓고 둘을 나열하는 모순도 생긴다.
    가장 흔한 것 하나면 그림을 알아보는 데 충분하다.
    """
    words = " ".join((ln.get("text") or "") for ln in lines).split()
    return Counter(words).most_common(1)[0][0] if words else ""


def figure_label(page: int | None) -> str:
    """경고에 쓸 그림의 자리. 검토자가 문서에서 찾아갈 수 있는 말이어야 한다.

    docx 의 `rId1` 같은 포맷 내부 식별자는 쓰지 않는다 — 검토자에게는 어느
    그림인지 알 길이 없는 글자다. 이 경고들은 검토 결과 화면에 INFO·미검토
    지적으로 그대로 뜬다(app/orchestrator._parser_warning_findings).

    **"N번째 그림"도 안 쓴다.** 한때 썼는데, 셀 수 있는 것은 OCR 예약에 성공한
    그림뿐이라 앞에서 한 장이라도 건너뛰면 뒤 번호가 통째로 밀렸다 — 조용히
    어긋나는 번호는 없는 번호보다 나쁘다.

    쪽은 docx·hwpx 에서 개바꿈 신호로 **근사**한 값이다(각 backend 의 페이지
    근사 주석). 화면의 다른 지적도 같은 값으로 쪽을 말하므로 여기서만 다른
    잣대를 쓰지 않는다. 그마저 없으면 쪽을 지어내지 않고 "그림"이라고만 한다.
    """
    return f"{page + 1}쪽 그림" if isinstance(page, int) else "그림"


def _jobs() -> list[tuple[Block, bytes, list[str]]]:
    got = getattr(_local, "jobs", None)
    if got is None:
        got = _local.jobs = []
    return got


def begin() -> None:
    """이 스레드의 예약을 비운다. 각 백엔드의 parse_* 시작에서 부른다."""
    _jobs().clear()


def schedule(block: Block, image_bytes: bytes, warnings: list[str]) -> None:
    """이 블록의 OCR 을 예약한다. `run()` 이 돌 때 채워진다.

    예전에는 호출자가 그림의 내부 id(docx 의 `rId1`, hwpx 의 item id)를 함께
    넘겼고 경고 문장이 그것을 그대로 적었다. 그 경고는 **검토 결과 화면에**
    INFO·미검토 지적으로 뜨는데(app/orchestrator._parser_warning_findings),
    검토자에게 `rId1` 은 어느 그림인지 알 길이 없는 글자였다. 자리는 예약된
    차례(문서 안 몇 번째 그림인가)와 블록의 쪽으로 말한다.
    """
    _jobs().append((block, image_bytes, warnings))


def run(hook: Callable[[bytes, int], list[dict]] | None) -> None:
    """예약된 OCR 을 병렬로 돌려 블록에 채운다. 각 백엔드의 parse_* 끝에서 부른다.

    실패는 조용히 넘기지 않고 그 이미지의 warnings 에 남긴다(text 는 None 으로 둔다) —
    기존 순차 구현과 같은 관례다.
    """
    jobs = _jobs()
    if not jobs:
        return
    pending, jobs[:] = list(jobs), []
    if hook is None:
        return
    with ThreadPoolExecutor(max_workers=min(_WORKERS, len(pending))) as pool:
        futures = [(block, warnings, pool.submit(hook, image_bytes, 0))
                   for block, image_bytes, warnings in pending]
        for block, warnings, future in futures:
            where = figure_label(getattr(block, "page", None))
            try:
                raw = future.result() or []
            except Exception as e:  # noqa: BLE001 — 한 이미지 실패가 문서를 죽이지 않는다
                warnings.append(
                    f"{where}을 읽다가 오류가 났습니다 → {e}. "
                    f"이 그림 안의 글자는 검토하지 않았습니다.")
                continue
            if _looks_degenerate(raw):
                # 조용히 버리지 않는다 — 이 그림은 읽히지 않은 것이고, 그 사실이
                # 남아야 "이상 없음"으로 오해되지 않는다(CLAUDE.md).
                # 문장은 **결론부터** 쓴다. 예전에는 "글자 읽기가 …만 되풀이해
                # 버렸습니다"로 시작해서, 정작 검토자가 알아야 할 "그래서 이
                # 그림은 안 봤다"가 맨 끝에 있었다.
                warnings.append(
                    f"{where}의 글자를 읽지 못했습니다 — 같은 말"
                    f"(\"{_repeated_word(raw)}\")만 되풀이해 나왔습니다. "
                    f"로고·도장처럼 글자가 거의 없는 그림이면 정상입니다. "
                    f"이 그림 안의 글자는 검토하지 않았습니다.")
                continue
            flipped = flip_bbox_y([ln for ln in raw if ln.get("bbox")])
            lines = reading_order(flipped) + [ln for ln in raw if not ln.get("bbox")]
            block.text = merge_wrapped_lines(relocate_stray_labels(lines)) or None
            block.origin = ORIGIN_OCR
