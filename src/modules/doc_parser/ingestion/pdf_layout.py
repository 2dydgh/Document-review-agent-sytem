"""쪽을 세로 밴드로 쪼갠다.

표와 본문이 한 쪽에 섞여 있고 둘은 처리 방법이 다르다 — 표는 행 단위로,
본문은 좌표 군집으로. 먼저 세로로 갈라 두고 top 순으로 이어붙이면 원래 읽기
순서가 그대로 남는다.

좌표만 다루는 순수 함수다. pdfplumber 없이 테스트된다.
"""
from __future__ import annotations

# 이보다 얇은 조각은 밴드로 치지 않는다. 크롭해도 빈 문자열만 나오고
# 표 경계의 반올림 오차로 생기는 실틈이 대부분이다.
MIN_BAND_HEIGHT = 1.0


def split_bands(page_height: float, table_spans: list[tuple[float, float]], *,
                page_top: float = 0.0,
                min_height: float = MIN_BAND_HEIGHT) -> list[dict]:
    """표 y범위 목록으로 쪽을 밴드로 나눈다.

    table_spans 는 (top, bottom) 목록이고 순서가 뒤섞여 있어도 된다 —
    여기서 top 순으로 세운다. 결과의 ``index`` 는 **원래 목록에서의 위치**라,
    호출자가 그 표의 데이터를 다시 찾을 수 있다.
    """
    ordered = sorted(enumerate(table_spans), key=lambda pair: pair[1][0])

    bands: list[dict] = []
    cursor = page_top
    for index, (top, bottom) in ordered:
        if top - cursor >= min_height:
            bands.append({"kind": "text", "top": cursor, "bottom": top, "index": None})
        bands.append({"kind": "table", "top": top, "bottom": bottom, "index": index})
        cursor = max(cursor, bottom)
    if page_height - cursor >= min_height:
        bands.append({"kind": "text", "top": cursor, "bottom": page_height, "index": None})
    return bands
