"""글자를 좌표로 묶어 줄로 되돌린다.

PDF 도면은 작은 텍스트 상자 수십 개가 좌표에 흩어져 있다. 줄 단위로 읽으면
가로로 나란한 라벨들이 한 줄에 섞인다 — 실측(SHN34 SRS 본문 17쪽):

    A D M c i t a v u n e a u r t s i a o e l n I M nv in e i n m t u

원래는 Diverse, Actuation, Minimum Inventory, ITP 같은 개별 라벨이다. 회전
텍스트도 이미지도 아니라(그 쪽 1,863자 전부 upright), 좌표로 묶어야만 살아난다.

**줄글에는 무손실이다.** 실측으로 확인했다 — 본문 10쪽(줄글) 글자 100% 보존에
순서 유사도 100%, 5쪽(괘선 없는 개정이력)도 100%/100%. 17쪽(도면)만 유사도
66.3%로 떨어지는데 그게 뒤섞인 순서를 바로잡은 것이다. 그래서 도면인지
판정하지 않고 늘 이걸 쓴다. 판별자는 두 번 시도했다 두 번 다 실패했다 —
다시 시도하지 말 것:

  · 한 글자 토큰 비율 — 개정이력 쪽(41.7%)이 도면 쪽(25.4%)보다 높다.
  · 쪽 단위 벡터 밀도 — 밴드가 아니라 쪽 전체에 걸려 줄글 문단까지 도면으로
    분류된다. 밴드 단위로 고치려면 문서마다 다른 기준선이 필요하고, 그걸
    구하는 사전 패스가 본 패스와 맞먹는 42초다.

자세한 근거는 docs/superpowers/specs/2026-07-28-pdf-parsing-accuracy-design.md.
"""
from __future__ import annotations

# 같은 줄에서 글자 사이가 이보다 벌어지면 다른 라벨로 본다.
X_GAP = 3.2
# top 차이가 이 이하면 같은 줄.
Y_GAP = 2.0
# 왼쪽 모서리가 이 안이면 같은 세로줄(한 상자의 다음 줄).
X_COL = 6.0
# 세로로 이 이내면 같은 상자의 다음 줄.
Y_STACK = 4.0
# 출력에서 같은 가로줄로 묶는 폭.
ROW_TOL = 8.0


def cluster_chars(chars: list[dict], *, x_gap: float = X_GAP, y_gap: float = Y_GAP,
                  x_col: float = X_COL, y_stack: float = Y_STACK) -> list[dict]:
    """글자 목록 → 라벨 상자 목록.

    chars 는 pdfplumber ``page.chars`` 모양의 dict 목록이다:
    ``{"text": str, "x0": float, "x1": float, "top": float, "bottom": float}``
    """
    runs: list[list[dict]] = []
    cur: list[dict] = []
    for c in sorted(chars, key=lambda c: (round(c["top"] / 3), c["x0"])):
        if cur:
            prev = cur[-1]
            same_line = abs(c["top"] - prev["top"]) <= y_gap
            adjacent = (c["x0"] - prev["x1"]) <= x_gap
            if not (same_line and adjacent):
                runs.append(cur)
                cur = []
        cur.append(c)
    if cur:
        runs.append(cur)

    boxes: list[dict] = []
    for run in runs:
        text = "".join(c["text"] for c in run).strip()
        if not text:
            continue
        boxes.append({"text": text,
                      "x0": min(c["x0"] for c in run),
                      "top": min(c["top"] for c in run),
                      "bottom": max(c["bottom"] for c in run)})

    # 한 상자 안에서 여러 줄로 쓰인 라벨을 세로로 잇는다("Diverse" 아래 "Actuation").
    merged: list[dict] = []
    for b in sorted(boxes, key=lambda b: (round(b["x0"] / x_col), b["top"])):
        if merged:
            m = merged[-1]
            if abs(b["x0"] - m["x0"]) < x_col and 0 <= b["top"] - m["bottom"] <= y_stack:
                # 하이픈으로 끝났으면 끊긴 낱말이다 — 공백 없이 붙인다.
                # "FR-" 아래 "MTP_02" 는 ID 하나다. 띄우면 추출이 실패하고
                # 하위문서에 실재하는 요건이 '누락'으로 보고된다.
                m["text"] += ("" if m["text"].endswith("-") else " ") + b["text"]
                m["bottom"] = b["bottom"]
                continue
        merged.append(dict(b))
    return merged


def render_lines(boxes: list[dict], *, row_tol: float = ROW_TOL) -> list[str]:
    """라벨 상자 → 줄 목록. 세로 위치가 비슷한 상자를 한 줄로 모은다.

    짧다고 버리지 않는다. 한 글자 상자도 도면에서는 진짜 내용이다 — 본문
    17쪽에서 버려질 뻔한 것이 채널·슬롯 라벨 'G','2','C','1','3' 이었다.
    """
    rows: dict[int, list[dict]] = {}
    for b in sorted(boxes, key=lambda b: (b["top"], b["x0"])):
        rows.setdefault(round(b["top"] / row_tol), []).append(b)
    return ["   ".join(b["text"] for b in group) for _, group in sorted(rows.items())]
