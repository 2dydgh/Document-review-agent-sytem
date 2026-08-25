"""폭 때문에 단어 한가운데서 끊긴 줄을 붙여 잇는다.

PDF 는 칸 폭이 모자라면 단어 **중간에서도** 줄을 끊는다. 그때 공백을 끼워 이으면
멀쩡한 단어가 갈라지고, 검토자에게는 문서 오탈자로 보인다 — 실제로 `Communication`
이 `Communicati on` 으로 갈려 있지도 않은 "용어 혼용"이 지적됐다(실측 SKN56 CDMS
RVVR 13건).

가르는 신호는 **줄 끝 공백**이다. PDF 글자 흐름에는 그게 남아 있다:

    'Monitoring \\n'    줄 끝 공백 있음 → 단어가 끝난 것    → 공백으로 이음
    'Communicati\\non'  줄 끝 공백 없음 → 단어 중간에서 끊김 → 붙여 이음

OCR 이 돌려준 줄에는 그 공백이 없으므로(엔진이 줄 단위로 인식해 붙여 준다) 이
규칙을 거기 쓰면 멀쩡한 단어들이 통째로 들러붙는다 — 그래서 기본값은 끔이다.
"""
from __future__ import annotations

from modules.doc_parser.ocr_paddle import merge_wrapped_lines


def _line(text: str, left: float, right: float, top: float) -> dict:
    return {"text": text, "bbox": [left, top, right, top - 10]}


# 두 줄 다 왼쪽 끝에서 시작하고 앞 줄이 오른쪽 끝까지 찬 상태 = 폭에 걸린 줄바꿈
_WRAPPED = [_line("IPS Communicati", 0, 100, 100),
            _line("on 자기진단정보", 0, 60, 88)]


def test_줄_끝_공백이_없으면_붙여_잇는다():
    got = merge_wrapped_lines(_WRAPPED, trailing_space_known=True)

    assert got == "IPS Communication 자기진단정보"


def test_줄_끝_공백이_있으면_공백으로_잇는다():
    lines = [_line("IPS Monitoring ", 0, 100, 100),
             _line("자기진단정보", 0, 60, 88)]

    got = merge_wrapped_lines(lines, trailing_space_known=True)

    assert got == "IPS Monitoring 자기진단정보"


def test_신호를_모르면_예전처럼_공백으로_잇는다():
    """OCR 줄에는 줄 끝 공백이 없다 — 거기서 붙여 이으면 단어가 들러붙는다."""
    got = merge_wrapped_lines(_WRAPPED)

    assert got == "IPS Communicati on 자기진단정보"


def test_줄바꿈이_아니면_신호와_무관하게_줄을_나눈다():
    """앞 줄이 오른쪽 끝에 한참 못 미치면 폭에 걸린 게 아니라 진짜 문단 구분이다."""
    lines = [_line("첫 문단", 0, 30, 100),
             _line("둘째 문단", 0, 100, 88)]

    got = merge_wrapped_lines(lines, trailing_space_known=True)

    assert got == "첫 문단\n둘째 문단"
