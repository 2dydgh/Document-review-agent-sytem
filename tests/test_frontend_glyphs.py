"""삽화형 문서·폴더 그림(업로드 드롭존 · 검토 기준 카드).

화면마다 따로 손으로 그린 SVG 라 계속 갈라졌다. 여기서 지키는 것은 둘.

1. **연한 채움에 윤곽선을 얹는다.** 채움(opacity .15)만 있으면 형태가 흐리다.
   한 화면에 윤곽선 있는 그림과 없는 그림이 같이 놓이면 없는 쪽만 덜 그려진
   것처럼 보인다 — 실제로 폴더 검토 그림에만 윤곽선이 있어서 그렇게 보였다.
2. **그라디언트 id 는 화면에서 유일하다.** 비교 검토는 드롭존을 A·B 두 번
   그린다. 고정 id 를 쓰면 같은 id 가 한 문서에 둘이 되고, 값이 갈리는 순간
   조용히 한쪽을 따라간다.
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
VIEWS_JS = (_ROOT / "web" / "views.js").read_text(encoding="utf-8")

# 삽화형 그림의 몸통. 문서(dropzone·검토 기준)와 폴더(폴더 검토)가 나눠 쓴다.
_DOC_SHAPES = (
    "M24 18 L57 18 L76 37 L76 78",  # 업로드 — 폴더와 면적을 맞춘 넓은 종이
    "M28 18 L56 18 L72 34 L72 78",  # 진행 스캔 — 기존 비율
)
_FOLDER_SHAPE = "M18 30 A4 4 0 0 1 22 26"


def _svg_blocks() -> list[str]:
    """viewBox="0 0 100 100" 짜리 삽화형 SVG 만 골라 온다."""
    return re.findall(r'<svg viewBox="0 0 100 100".*?</svg>', VIEWS_JS, re.DOTALL)


def test_문서_폴더_그림에_윤곽선이_있다() -> None:
    """**몸통 path** 만 본다.

    같은 svg 안의 화살표·더하기는 원래 stroke 로 그리므로, svg 통째로 "stroke 가
    있나"를 물으면 몸통이 채움뿐이어도 통과한다. 윤곽선 여부는 몸통에게 물어야 한다.

    윤곽선 색은 가리지 않는다 — 드롭존은 그라디언트로, 비교 검토 진행 화면의
    스캔 그림은 단색(--accent)으로 긋는다. 둘 다 형태가 또렷하면 목적을 채운다.
    """
    seen = 0
    for s in _svg_blocks():
        body = [p for p in re.findall(r"<path\b[^>]*>", s)
                if any(shape in p for shape in _DOC_SHAPES) or _FOLDER_SHAPE in p]
        if not body:
            continue
        seen += 1
        assert any('stroke="' in p for p in body), \
            "몸통에 윤곽선이 없다 — 채움만 있으면 형태가 흐리다"
    # 통짜 문자열로 적힌 것만 세어진다 — 드롭존 문서 · 폴더 검토 폴더 · 비교 검토
    # 진행 화면의 스캔 그림. 검토 기준의 둘은 docGlyph() 가 조립해서 만들므로
    # 여기 안 걸리고, 아래 test_검토_기준_그림은_한_함수에서_나온다 가 본다.
    assert seen >= 3, f"삽화형 문서·폴더 그림을 {seen}개만 찾았다 — 셀렉터가 낡았다"


def test_그림마다_그라디언트_id_가_다르다() -> None:
    """한 화면에 둘 이상 놓이므로 고정 id 를 쓰면 겹친다."""
    blocks = _svg_blocks()
    ids: list[str] = []
    for s in blocks:
        ids += re.findall(r'linearGradient id="([^"]*)"', s)
    # 비교 검토는 같은 함수를 A·B 두 번 부른다 — id 에 slot 을 붙여 가른다.
    assert any("' + opts.slot + '" in i for i in ids), \
        "드롭존 그라디언트 id 가 고정이다 — 비교 검토에서 A·B 가 겹친다"
    fixed = [i for i in ids if "+" not in i]
    assert len(fixed) == len(set(fixed)), f"고정 id 가 겹친다: {fixed}"


def test_점선_카드_hover_는_brand_state이다() -> None:
    """중립 목록 hover는 드롭 동작의 강조로 재사용하지 않는다.

    점선 드롭존은 브랜드 호버를 쓰고, 지속되는 선택 상태의 --accent-weak보다
    옅게 유지한다.
    """
    app_js = (_ROOT / "web" / "app.js").read_text(encoding="utf-8")
    # 점선 카드를 그리는 자리 = "2px dashed var(--line-dashed)" 를 가진 마크업.
    cards = [m for m in re.findall(r"'[^']*2px dashed var\(--line-dashed\)[^']*'[^;]*",
                                   VIEWS_JS)]
    assert cards, "점선 카드를 못 찾았다 — 셀렉터가 낡았다"
    for c in cards:
        assert "var(--state-hover-neutral)" not in c, \
            "점선 카드 hover 에 중립 목록 hover가 남아 있다"

    # onmouseover 로 중립 면을 칠하는 점선 카드가 없어야 한다(마크업 전체에서).
    for chunk in re.findall(r"onmouseover=[^+]*var\(--state-hover-neutral\)[^+]*", VIEWS_JS):
        assert "borderColor='var(--accent)'" not in chunk, \
            "점선 카드 hover 가 중립 목록 hover로 되돌아갔다"

    # 끌어다 놓는 중의 강조(폴더 검토)도 같은 브랜드 호버 값이어야 한다.
    drag = app_js[app_js.index("var z = caseZoneOf(e); if (z) { e.preventDefault();"):]
    drag = drag[:drag.index("\n")]
    assert "var(--state-hover-brand)" in drag, \
        "폴더 검토 드래그 강조가 브랜드 호버 토큰을 쓰지 않는다"


def test_검토_기준_그림은_한_함수에서_나온다() -> None:
    """파일 첨부·직접 작성이 같은 문서 모양을 쓴다. 따로 적어 두면 한쪽만 고쳐진다
    — 실제로 그래서 윤곽선이 두 곳 다 빠져 있었다."""
    assert "function docGlyph(" in VIEWS_JS, "두 그림을 함께 만드는 자리가 없다"
    fn = VIEWS_JS[VIEWS_JS.index("function docGlyph("):]
    fn = fn[:fn.index("\n    }") + 6]
    assert 'stroke="url(#' in fn, "공용 함수에 윤곽선이 없다"
    for name in ("attachIcon", "writeIcon"):
        assert f"var {name} = docGlyph(" in VIEWS_JS, f"{name} 이 공용 함수를 안 쓴다"


def test_업로드_그림의_크기와_농도가_한_단계다() -> None:
    """문서·체크리스트·폴더가 같은 52px 보조 삽화 세트로 읽혀야 한다."""
    assert VIEWS_JS.count('width:52px;height:52px') >= 3
    assert 'width:48px;height:48px;margin:0 auto 12px' not in VIEWS_JS
    # 일반 문서와 공용 체크리스트 함수 모두 같은 외곽 농도와 내부 선을 쓴다.
    assert VIEWS_JS.count('opacity="0.40"') >= 4
    assert VIEWS_JS.count('stroke-width="4"') >= 3
    # 첨부 전·후 폴더도 면을 진하게 바꾸지 않고 내부 기호로 상태를 구분한다.
    assert 'folder("0.15", "0.40")' in VIEWS_JS
    assert 'folder("0.25", "0.5")' not in VIEWS_JS


def test_큰_파일_폴더_아이콘은_업로드_그림처럼_윤곽이_있다() -> None:
    """40px 이상 콘텐츠 아이콘만 약 1px 윤곽을 쓰고 작은 배지는 단순하게 둔다."""
    start = VIEWS_JS.index("function docShapeIcon(")
    block = VIEWS_JS[start:VIEWS_JS.index("function iconTile(", start)]
    # 문서 몸통·접힌 면, 폴더 몸통·탭 네 곳이 같은 선과 농도를 쓴다.
    assert block.count('stroke-width="0.7"') == 4
    assert block.count('opacity="0.38"') == 4
    # 작은 아이콘 분기 뒤에만 윤곽 설명과 SVG가 온다.
    small_doc = block.index("if (size < 40)", block.index("var fSize"))
    outline = block.index('stroke-width="0.7"', small_doc)
    assert outline > block.index("var w =", small_doc)
