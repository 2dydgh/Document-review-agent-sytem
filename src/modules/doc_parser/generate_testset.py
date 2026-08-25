"""형식·양식·분량·내용이 다양한 더미 PDF 테스트셋 생성기.

실제 대외비 데이터는 절대 쓰지 않고, 무의미한 더미/예시 텍스트만 사용한다.
설치된 오프라인 라이브러리(PyMuPDF, matplotlib)만 사용한다.

생성물:
    testset/*.pdf          다양한 특성의 더미 PDF
    testset/manifest.json  각 PDF의 정답(ground-truth) 특성

사용:
    python -m pdf_poc.generate_testset
"""
from __future__ import annotations

import io
import json
from dataclasses import asdict, dataclass, field
from typing import Any

import fitz  # PyMuPDF

from .config import MANIFEST, TESTSET_DIR, ensure_dirs, korean_font

FONT = korean_font()
FONT_NAME = "kr"  # insert_textbox 내부 폰트명 (fontfile 과 함께 사용)

A4 = fitz.paper_rect("a4")  # 595 x 842 pt
MARGIN = 50

# 더미 본문 (의미 없는 예시 텍스트, 한글+영문 혼합)
LOREM_KR = (
    "본 문서는 파서 개발용 더미 예시입니다. 실제 의뢰기관 정보나 대외비 내용은 "
    "포함하지 않으며, 형식·양식·분량이 서로 다른 PDF를 파서가 공통적으로 잘 "
    "처리하는지 검증하기 위한 목적으로만 사용됩니다. 문단은 여러 줄에 걸쳐 이어지고, "
    "숫자 1234 와 기호 §, ※, ①②③ 등이 섞여 있을 수 있습니다. "
    "This paragraph mixes Korean and English to exercise font handling and reading order. "
)


# ----------------------------------------------------------------------------
# 정답(manifest) 스키마
# ----------------------------------------------------------------------------
@dataclass
class Truth:
    filename: str
    title: str
    pages: int
    text: bool = True
    table: bool = False
    nested_table: bool = False
    multicolumn: bool = False
    rotated: bool = False
    watermark: bool = False
    watermark_text: str = ""
    scanned_pages: list[int] = field(default_factory=list)  # 이미지-only 페이지 인덱스
    formula: bool = False
    code: bool = False
    diagram: bool = False
    permission_restricted: bool = False
    owner_pw: str = ""
    user_pw: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["scanned"] = len(self.scanned_pages) > 0
        return d


# ----------------------------------------------------------------------------
# 저수준 그리기 헬퍼
# ----------------------------------------------------------------------------
def _textbox(page, rect, text, size=11, mono=False, color=(0, 0, 0), align=0):
    """텍스트 상자 삽입. mono=True 면 Courier(코드용)."""
    if mono:
        page.insert_textbox(rect, text, fontname="cour", fontsize=size,
                            color=color, align=align)
    else:
        page.insert_textbox(rect, text, fontname=FONT_NAME, fontfile=FONT,
                            fontsize=size, color=color, align=align)


def _title(page, text, y=MARGIN):
    rect = fitz.Rect(MARGIN, y, A4.width - MARGIN, y + 30)
    _textbox(page, rect, text, size=16)
    return y + 36


def _draw_table(page, x0, y0, col_widths, row_h, rows, size=9, nested_at=None):
    """단순 격자 표를 벡터 선 + 텍스트로 그린다.

    rows: list[list[str]]  (첫 행을 헤더처럼 취급)
    nested_at: (r, c) 지정 시 그 셀 안에 2x2 중첩표를 그린다.
    반환: 표 하단 y 좌표
    """
    shape = page.new_shape()
    n_rows = len(rows)
    # 바깥/셀 테두리
    y = y0
    for r in range(n_rows):
        x = x0
        for c, w in enumerate(col_widths):
            cell = fitz.Rect(x, y, x + w, y + row_h)
            shape.draw_rect(cell)
            x += w
        y += row_h
    shape.finish(width=0.8, color=(0.1, 0.1, 0.1))
    shape.commit()

    # 셀 텍스트
    y = y0
    for r in range(n_rows):
        x = x0
        for c, w in enumerate(col_widths):
            if nested_at is not None and (r, c) == nested_at:
                # 중첩표: 셀 내부에 작은 2x2 격자
                _draw_table(page, x + 3, y + 3,
                            [(w - 8) / 2, (w - 8) / 2], (row_h - 8) / 2,
                            [["a", "b"], ["c", "d"]], size=6)
            else:
                cell = fitz.Rect(x + 3, y + 2, x + w - 3, y + row_h - 2)
                _textbox(page, cell, str(rows[r][c]), size=size)
            x += w
        y += row_h
    return y


def _watermark(page, text):
    """반복·대각선 워터마크(연한 회색). TextWriter 45° 시도 후 실패 시 수평 fallback."""
    try:
        font = fitz.Font(fontfile=FONT) if FONT else fitz.Font("helv")
        tw = fitz.TextWriter(page.rect, color=(0.85, 0.85, 0.85))
        pivot = fitz.Point(page.rect.width / 2, page.rect.height / 2)
        tw.append(fitz.Point(page.rect.width * 0.2, page.rect.height * 0.55),
                  text, font=font, fontsize=44)
        tw.write_text(page, morph=(pivot, fitz.Matrix(45)))
    except Exception:
        rect = fitz.Rect(MARGIN, page.rect.height / 2 - 30,
                        page.rect.width - MARGIN, page.rect.height / 2 + 30)
        _textbox(page, rect, text, size=40, color=(0.85, 0.85, 0.85), align=1)


def _formula_png() -> bytes:
    """matplotlib mathtext 로 수식 이미지를 PNG 바이트로 렌더."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(4.2, 0.9))
    fig.text(0.02, 0.35,
             r"$E=mc^2,\quad \int_0^{\infty} e^{-x^2}\,dx=\frac{\sqrt{\pi}}{2}$",
             fontsize=18)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _diagram_png() -> bytes:
    """간단한 흐름도(상자 3개 + 화살표) 이미지를 PNG 바이트로 렌더."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.patches as mpatches
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(4.5, 1.3))
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 3)
    ax.axis("off")
    boxes = [(0.5, "Input"), (4.0, "Parse"), (7.5, "Output")]
    for x, label in boxes:
        ax.add_patch(mpatches.FancyBboxPatch((x, 1), 2, 1,
                     boxstyle="round,pad=0.05", fc="#e8eef7", ec="#002878"))
        ax.text(x + 1, 1.5, label, ha="center", va="center", fontsize=11)
    for x in (2.6, 6.1):
        ax.annotate("", xy=(x + 0.8, 1.5), xytext=(x, 1.5),
                    arrowprops=dict(arrowstyle="->", color="#002878"))
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _paragraphs(page, y, n=3, size=11):
    """LOREM_KR 더미 문단을 n개 반복 삽입. 대부분의 build_* 빌더가 본문 채우기에 재사용."""
    for _ in range(n):
        rect = fitz.Rect(MARGIN, y, A4.width - MARGIN, y + 90)
        _textbox(page, rect, LOREM_KR, size=size)
        y += 96
    return y


# ----------------------------------------------------------------------------
# 개별 PDF 빌더 — 각 build_* 는 더미 PDF 1개를 저장하고, 그 파일의 정답(Truth)을
# 반환한다. main() 이 BUILDERS 순서대로 호출해 모아서 manifest.json 으로 직렬화한다.
# report.py 가 이 Truth 값과 실제 파싱 결과(DocumentModel)를 대조해 채점한다.
# ----------------------------------------------------------------------------
def build_simple_text() -> Truth:
    """01: 순수 텍스트 2페이지 — 표/스캔/특수요소 없는 baseline 케이스."""
    doc = fitz.open()
    p = doc.new_page(width=A4.width, height=A4.height)
    y = _title(p, "01. 단순 텍스트 문서 (한글+영문)")
    _paragraphs(p, y, n=5)
    p2 = doc.new_page(width=A4.width, height=A4.height)
    _paragraphs(p2, MARGIN, n=6)
    fn = "01_simple_text.pdf"
    doc.save(str(TESTSET_DIR / fn))
    doc.close()
    return Truth(fn, "단순 텍스트", pages=2, text=True, notes="기본 텍스트 추출 baseline")


def build_multicolumn() -> Truth:
    """02: 좌우 2단 컬럼 — pdf-inspector 의 다단 읽기순서 정렬 검증용."""
    doc = fitz.open()
    p = doc.new_page(width=A4.width, height=A4.height)
    y = _title(p, "02. 2단(멀티컬럼) 레이아웃")
    colw = (A4.width - 2 * MARGIN - 20) / 2
    left = fitz.Rect(MARGIN, y, MARGIN + colw, A4.height - MARGIN)
    right = fitz.Rect(MARGIN + colw + 20, y, A4.width - MARGIN, A4.height - MARGIN)
    _textbox(p, left, (LOREM_KR + "\n\n") * 3, size=10)
    _textbox(p, right, (LOREM_KR + "\n\n") * 3, size=10)
    fn = "02_multicolumn.pdf"
    doc.save(str(TESTSET_DIR / fn))
    doc.close()
    return Truth(fn, "멀티컬럼", pages=1, text=True, multicolumn=True,
                 notes="읽기 순서(컬럼) 처리 검증")


def build_table_simple() -> Truth:
    """03: 유선(테두리 있는) 단순 표 — 표 검출 baseline."""
    doc = fitz.open()
    p = doc.new_page(width=A4.width, height=A4.height)
    y = _title(p, "03. 단순 표 (테두리 있는 격자)")
    rows = [["항목", "2024", "2025", "증감"],
            ["매출", "100", "120", "+20"],
            ["비용", "70", "80", "+10"],
            ["이익", "30", "40", "+10"]]
    _draw_table(p, MARGIN, y + 10, [120, 90, 90, 90], 26, rows, size=10)
    fn = "03_table_simple.pdf"
    doc.save(str(TESTSET_DIR / fn))
    doc.close()
    return Truth(fn, "단순 표", pages=1, text=True, table=True,
                 notes="lattice 표 검출")


def build_table_nested() -> Truth:
    """04: 셀 안에 2x2 표가 들어간 중첩 표 — docling_adapter._has_nested_structure() 가
    검출해야 하는 케이스(row/col span 불규칙 그리드로 나타남)."""
    doc = fitz.open()
    p = doc.new_page(width=A4.width, height=A4.height)
    y = _title(p, "04. 중첩 표 (셀 안에 표)")
    rows = [["구분", "내용", "비고"],
            ["A", "표속의표", "x"],
            ["B", "일반셀", "y"]]
    # (1,1) 셀에 중첩표
    _draw_table(p, MARGIN, y + 10, [90, 180, 90], 60, rows, size=10,
                nested_at=(1, 1))
    fn = "04_table_nested.pdf"
    doc.save(str(TESTSET_DIR / fn))
    doc.close()
    return Truth(fn, "중첩 표", pages=1, text=True, table=True, nested_table=True,
                 notes="셀 내부 표 재귀 처리 검증")


def build_mixed_all() -> Truth:
    """05: 텍스트+표+수식(이미지)+코드+다이어그램(흐름도)을 한 문서에 종합 — 특수요소
    라우팅(FORMULA/CODE/FIGURE 타입 분기) 검증용. 3페이지로 구성."""
    doc = fitz.open()
    # p1: 텍스트 + 표
    p = doc.new_page(width=A4.width, height=A4.height)
    y = _title(p, "05. 복합 문서 (텍스트+표+수식+코드+다이어그램)")
    y = _paragraphs(p, y, n=2)
    rows = [["키", "값"], ["alpha", "1"], ["beta", "2"]]
    y = _draw_table(p, MARGIN, y, [120, 120], 24, rows, size=10)
    # p2: 수식 + 코드
    p2 = doc.new_page(width=A4.width, height=A4.height)
    yy = _title(p2, "5-1. 수식(이미지) 과 코드 블록")
    p2.insert_image(fitz.Rect(MARGIN, yy + 6, MARGIN + 320, yy + 80),
                    stream=_formula_png())
    code = ("def parse_pdf(path):\n"
            "    doc = open_pdf(path)\n"
            "    for page in doc:\n"
            "        yield classify(page)  # TextBased/Scanned\n")
    _textbox(p2, fitz.Rect(MARGIN, yy + 100, A4.width - MARGIN, yy + 200),
             code, size=10, mono=True)
    # p3: 다이어그램
    p3 = doc.new_page(width=A4.width, height=A4.height)
    yy = _title(p3, "5-2. 다이어그램(흐름도)")
    p3.insert_image(fitz.Rect(MARGIN, yy + 6, MARGIN + 360, yy + 120),
                    stream=_diagram_png())
    fn = "05_mixed_all.pdf"
    doc.save(str(TESTSET_DIR / fn))
    doc.close()
    return Truth(fn, "복합(텍스트+표+수식+코드+다이어그램)", pages=3, text=True,
                 table=True, formula=True, code=True, diagram=True,
                 notes="특수요소 라우팅 종합 검증")


def build_rotated() -> Truth:
    """06: /Rotate 90 이 지정된 가로 페이지 + 표 — 회전 좌표 처리 검증용."""
    doc = fitz.open()
    # 가로(landscape) 페이지 + 90도 회전 지정
    p = doc.new_page(width=A4.height, height=A4.width)
    y = _title(p, "06. 회전/가로 페이지 + 표")
    rows = [["col1", "col2", "col3"], ["1", "2", "3"], ["4", "5", "6"]]
    _draw_table(p, MARGIN, y + 10, [120, 120, 120], 24, rows, size=10)
    p.set_rotation(90)
    fn = "06_rotated.pdf"
    doc.save(str(TESTSET_DIR / fn))
    doc.close()
    return Truth(fn, "회전 페이지", pages=1, text=True, table=True, rotated=True,
                 notes="/Rotate 처리 검증")


def build_watermark() -> Truth:
    """07: 2페이지 모두 동일 위치에 반복되는 대각선 워터마크 삽입 —
    pdf_backend._detect_watermarks() 의 "반복성" 휴리스틱 검증용."""
    doc = fitz.open()
    wm = "대외비 SAMPLE"
    for i in range(2):
        p = doc.new_page(width=A4.width, height=A4.height)
        y = _title(p, f"07. 워터마크 문서 (p{i+1})")
        _paragraphs(p, y, n=4)
        _watermark(p, wm)
    fn = "07_watermark.pdf"
    doc.save(str(TESTSET_DIR / fn))
    doc.close()
    return Truth(fn, "워터마크", pages=2, text=True, watermark=True,
                 watermark_text=wm, notes="반복 워터마크 후보 탐지")


def _render_scanned(src_page) -> fitz.Pixmap:
    """텍스트 페이지를 150dpi 이미지로 구워 "스캔본"을 흉내낸다.
    build_scanned/build_mixed_scan 이 공용으로 사용."""
    return src_page.get_pixmap(dpi=150)


def build_scanned() -> Truth:
    """08: 텍스트 레이어가 전혀 없는 스캔본(이미지만) — pdf-inspector 가 OCR 필요로
    올바르게 분류하는지, PaddleOCR 훅이 실제 인식하는지 검증용."""
    # 먼저 텍스트 페이지를 만들고 이미지로 변환 → 텍스트 레이어 없는 스캔형
    tmp = fitz.open()
    tp = tmp.new_page(width=A4.width, height=A4.height)
    y = _title(tp, "08. 스캔본 (텍스트 레이어 없음)")
    _paragraphs(tp, y, n=4)
    pix = _render_scanned(tp)
    tmp.close()

    doc = fitz.open()
    p = doc.new_page(width=A4.width, height=A4.height)
    p.insert_image(p.rect, pixmap=pix)
    fn = "08_scanned.pdf"
    doc.save(str(TESTSET_DIR / fn))
    doc.close()
    return Truth(fn, "스캔본", pages=1, text=False, scanned_pages=[0],
                 notes="OCR 필요 페이지 분류 검증 (텍스트 없음)")


def build_mixed_scan() -> Truth:
    """09: 1p 텍스트 + 2p 스캔(이미지) 혼합 문서 — 같은 문서 안에서 페이지별로
    텍스트/OCR 경로가 정확히 갈리는지(pdf_type="mixed") 검증용."""
    # p0 텍스트, p1 스캔(이미지) → Mixed 문서
    tmp = fitz.open()
    tp = tmp.new_page(width=A4.width, height=A4.height)
    y = _title(tp, "09-b. 스캔 페이지")
    _paragraphs(tp, y, n=4)
    pix = _render_scanned(tp)
    tmp.close()

    doc = fitz.open()
    p0 = doc.new_page(width=A4.width, height=A4.height)
    y = _title(p0, "09. 텍스트+스캔 혼합 문서 (p1 텍스트)")
    _paragraphs(p0, y, n=4)
    p1 = doc.new_page(width=A4.width, height=A4.height)
    p1.insert_image(p1.rect, pixmap=pix)
    fn = "09_mixed_scan.pdf"
    doc.save(str(TESTSET_DIR / fn))
    doc.close()
    return Truth(fn, "텍스트+스캔 혼합", pages=2, text=True, scanned_pages=[1],
                 notes="문서 내 페이지별 경로 분기 검증")


def build_restricted() -> Truth:
    """10: owner 비밀번호로 암호화하되 user 비번은 없어 "비번 없이 열리지만 복사/편집
    권한은 꺼진" PDF — pdf_backend._normalize() 의 복호화 prestep 검증용
    (§2-1 권한 플래그 vs 진짜 암호화 구분의 실증 케이스)."""
    doc = fitz.open()
    p = doc.new_page(width=A4.width, height=A4.height)
    y = _title(p, "10. 복사/편집 제한(권한 플래그) 문서")
    y = _paragraphs(p, y, n=3)
    rows = [["권한", "허용?"], ["열람", "예"], ["복사", "아니오"], ["편집", "아니오"]]
    _draw_table(p, MARGIN, y, [140, 100], 24, rows, size=10)
    fn = "10_restricted.pdf"
    owner = "owner-secret"
    # user_pw 없음 → 비번 없이 열림. 복사/편집 권한만 제거 (① 권한 플래그 케이스)
    perm = int(fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_PRINT)
    doc.save(str(TESTSET_DIR / fn), encryption=fitz.PDF_ENCRYPT_AES_256,
             owner_pw=owner, user_pw="", permissions=perm)
    doc.close()
    return Truth(fn, "권한 제한", pages=1, text=True, table=True,
                 permission_restricted=True, owner_pw=owner,
                 notes="복사 금지여도 열려서 파싱되는지 검증(권한 플래그)")


def build_long() -> Truth:
    """11: 15페이지 장문 + 간헐적 표(5페이지마다) — 분량 스트레스 테스트용."""
    doc = fitz.open()
    n_pages = 15
    for i in range(n_pages):
        p = doc.new_page(width=A4.width, height=A4.height)
        y = _title(p, f"11. 장문 문서 — 제{i+1}장")
        y = _paragraphs(p, y, n=4)
        if i % 5 == 0:  # 간헐적 표
            rows = [["#", "설명"], [str(i), "표 " + str(i)], [str(i + 1), "행"]]
            _draw_table(p, MARGIN, y, [60, 200], 22, rows, size=9)
    fn = "11_long.pdf"
    doc.save(str(TESTSET_DIR / fn))
    doc.close()
    return Truth(fn, "장문(15p)", pages=n_pages, text=True, table=True,
                 notes="분량 스트레스 + 간헐 표")


BUILDERS = [
    build_simple_text, build_multicolumn, build_table_simple, build_table_nested,
    build_mixed_all, build_rotated, build_watermark, build_scanned,
    build_mixed_scan, build_restricted, build_long,
]  # main() 이 이 순서대로 실행 → 01~11 번 파일명과 순서가 대응


def main() -> None:
    """run_poc.py 가 --no-gen 옵션이 없을 때 호출하는 진입점.
    BUILDERS 를 순서대로 실행해 testset/*.pdf 를 만들고, 각 Truth 를 모아
    testset/manifest.json 으로 저장한다(report.py 가 채점 시 이 정답을 읽음)."""
    ensure_dirs()
    if FONT is None:
        print("[경고] 한글 폰트를 찾지 못했습니다. 한글이 깨질 수 있습니다.")
    truths: list[dict[str, Any]] = []
    for b in BUILDERS:
        t = b()
        truths.append(t.to_dict())
        print(f"  생성: {t.filename:24s} pages={t.pages}")
    manifest = {
        "note": "파서 개발용 더미 PDF 테스트셋 (실데이터 아님)",
        "count": len(truths),
        "files": truths,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"\n총 {len(truths)}개 PDF + manifest.json → {TESTSET_DIR}")


if __name__ == "__main__":
    main()
