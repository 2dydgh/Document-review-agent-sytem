"""지적을 PDF 지면에 직접 그린다 — 요약 페이지와 근거 번호.

형광펜에 매단 주석(/Contents)은 **뷰어가 그린다.** 크롬 기본 뷰어(pdfium)는
그 팝업의 한글을 못 찍어서 구두점만 남는다. 인쇄하면 아예 사라진다. 즉 팝업에
지적 내용을 맡기는 설계는 크롬으로 여는 사람에게는 작동하지 않는다.

그래서 우리가 직접 그린다. 지면에 그린 글자는 어느 뷰어에서 열든, 인쇄를 하든
똑같이 보인다. 대신 한글 폰트를 PDF에 심어야 한다 — PDF 기본 폰트(Helvetica 등)
에는 한글이 없다.

폰트는 시스템에서 찾는다. 저장소에 넣지 않는다(수 MB짜리 바이너리다). 없으면
요약을 조용히 빼지 않고, 무엇이 없어서 못 넣었는지 화면에 말한다.
"""
from __future__ import annotations

import io
from pathlib import Path

# 흔한 한글 폰트 자리. 사내 서버는 보통 fonts-nanum을 깐다.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJKkr-Regular.otf",
    "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
)

_SEV_LABEL = {"major": "주의", "minor": "경미", "info": "정보"}
_SEV_RGB = {
    "major": (194, 65, 12),
    "minor": (161, 98, 4),
    "info": (29, 78, 216),
}


class FontMissing(Exception):
    """한글 폰트를 못 찾았다. 요약 없이 형광펜만 나간다."""


def find_font() -> Path:
    for c in _FONT_CANDIDATES:
        p = Path(c)
        if p.is_file():
            return p
    raise FontMissing(
        "한글 폰트를 찾지 못해 요약 페이지를 넣지 못했습니다. "
        "설치: sudo apt install fonts-nanum")


def _fpdf(size: tuple[float, float], font: Path):
    from fpdf import FPDF  # noqa: PLC0415 — web extra

    pdf = FPDF(unit="pt", format=(size[0], size[1]))
    pdf.set_auto_page_break(auto=True, margin=48)
    # fpdf2가 쓰는 글자만 골라 심는다(서브셋). 나눔고딕 전체는 4MB지만
    # 실제로 들어가는 건 수십 KB다.
    pdf.add_font("kr", "", str(font))
    return pdf


def summary_pdf(doc_name: str, items: list[dict], size: tuple[float, float],
                font: Path, unmarked: list[dict], brand: str = "문서 검토") -> bytes:
    """지적 요약 페이지. items는 [{no, sev, page, section, message, quote, suggestion}].

    no가 None인 지적은 본문에 번호를 못 붙인 것이다(근거가 없거나 못 찾았다).
    목록에는 그대로 싣는다 — 요약에서 빠지면 "없는 지적"이 된다.
    """
    pdf = _fpdf(size, font)
    pdf.add_page()
    w = size[0] - 96  # 좌우 여백 48pt

    pdf.set_font("kr", size=18)
    pdf.set_text_color(20, 20, 26)
    pdf.set_xy(48, 48)
    pdf.multi_cell(w, 24, f"검토 결과 — {doc_name}", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("kr", size=9)
    pdf.set_text_color(116, 118, 135)
    pdf.multi_cell(
        w, 14,
        f"{brand} — 본문의 형광펜 번호와 아래 번호가 짝입니다. "
        "LLM이 낸 지적에는 원문 근거가 함께 실려 있습니다.",
        new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    if unmarked:
        pdf.set_font("kr", size=9)
        pdf.set_text_color(185, 28, 28)
        pdf.multi_cell(
            w, 14,
            f"※ {len(unmarked)}건은 본문에서 위치를 찾지 못해 형광펜을 칠하지 못했습니다. "
            "형광펜이 없다고 해서 지적이 없는 것이 아닙니다 — 아래 목록에 번호 없이 실려 있습니다.",
            new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    for it in items:
        pdf.set_font("kr", size=10)
        r, g, b = _SEV_RGB.get(it["sev"], (100, 100, 100))
        pdf.set_text_color(r, g, b)
        no = f"[{it['no']}] " if it.get("no") else "[-] "
        where = f"{it['page']}쪽" if it.get("page") else (
            f"§{it['section']}" if it.get("section") else "문서 전체")
        head = f"{no}{_SEV_LABEL.get(it['sev'], it['sev'])} · {where}"
        pdf.multi_cell(w, 14, head, new_x="LMARGIN", new_y="NEXT")

        pdf.set_font("kr", size=10)
        pdf.set_text_color(25, 27, 36)
        pdf.multi_cell(w, 15, it["message"], new_x="LMARGIN", new_y="NEXT")

        for q in it.get("quotes") or []:
            pdf.set_font("kr", size=9)
            pdf.set_text_color(67, 70, 85)
            pdf.multi_cell(w - 12, 13, f"  “{q}”", new_x="LMARGIN", new_y="NEXT")

        if it.get("suggestion"):
            pdf.set_font("kr", size=9)
            pdf.set_text_color(116, 118, 135)
            pdf.multi_cell(w, 13, f"  제안: {it['suggestion']}",
                           new_x="LMARGIN", new_y="NEXT")
        pdf.ln(7)

    return bytes(pdf.output())


def number_overlay(size: tuple[float, float],
                   labels: list[tuple[int, float, float, str]]) -> bytes:
    """형광펜 옆에 번호를 그리는 한 장짜리 투명 오버레이.

    labels: [(번호, x, y_top, sev)] — y_top은 페이지 위에서부터의 거리(pt).

    번호는 숫자라 한글 폰트가 필요 없다(PDF 기본 폰트로 찍는다). 그래서 폰트가
    없는 서버에서도 번호는 붙는다 — 요약 페이지만 빠진다.
    """
    from fpdf import FPDF  # noqa: PLC0415 — web extra

    pdf = FPDF(unit="pt", format=(size[0], size[1]))
    pdf.set_auto_page_break(auto=False)
    pdf.add_page()

    # 번호표는 페이지 왼쪽 여백에 세운다.
    #
    # 예전에는 형광펜 시작점의 16pt 왼쪽(x - 16)에 놓았다. 형광펜이 줄 맨
    # 앞에서 시작할 때는 맞지만, 줄 중간에서 시작하면("제정일자: 2025.00.00."
    # 에서 날짜만 칠한 경우) 그 자리는 바로 앞 글자 위였다 — 번호표가 본문을
    # 덮어 글자가 깨져 보였다.
    #
    # 여백에 세우면 무엇을 가릴 일이 없고, 줄 단위로 훑기도 쉽다.
    W = 14.0
    H = 11.0
    MARGIN_X = 4.0

    # 같은 줄에 형광펜이 여럿이면 번호표도 여럿이다. 그대로 두면 여백의 같은
    # 자리에 겹쳐 찍히므로, 이미 쓴 높이면 오른쪽으로 한 칸씩 민다.
    used: list[tuple[float, float]] = []   # (y, 다음에 쓸 x)

    for no, _x, y_top, sev in labels:
        r, g, b = _SEV_RGB.get(sev, (100, 100, 100))
        pdf.set_fill_color(r, g, b)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("helvetica", size=7)

        by = min(max(2.0, y_top - 1), size[1] - H - 2.0)
        bx = MARGIN_X
        for i, (uy, ux) in enumerate(used):
            if abs(uy - by) < H:          # 사실상 같은 줄
                bx = ux
                used[i] = (uy, ux + W + 1.0)
                break
        else:
            used.append((by, MARGIN_X + W + 1.0))

        pdf.set_xy(bx, by)
        pdf.cell(W, H, str(no), border=0, align="C", fill=True)
    return bytes(pdf.output())
