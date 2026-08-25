"""web/DESIGN.md 의 자가 점검을 실제로 돌린다.

문서에 grep 명령으로만 적혀 있어서 아무도 안 돌렸고, 그 사이 소수점이 20 → 24 로
조용히 늘었다(2026-08-05 확인). 문서가 "늘면 안 되는 값"이라고 말해도 세는 사람이
없으면 안 지켜진다.

**여기서 잡는 것은 "0이어야 하는 것"과 "상한"이다.** 색·모서리는 아직 규칙과 멀어서
상한으로만 막는다 — 한 번에 접을 수 없는 종류다(치환이 아니라 매번 판단이 필요하다).
줄이면 이 숫자도 같이 내린다.
"""
from __future__ import annotations

import re
from pathlib import Path

_WEB = Path(__file__).resolve().parents[1] / "web"
_JS = sorted(_WEB.glob("*.js"))
_SOURCES = _JS + [_WEB / "index.html"]


def _joined(paths) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in paths)


def test_글자_크기_단계_밖의_소수점이_없다() -> None:
    """`13.5px` 같은 값은 글자 크기 단계(11·12·13·15·18·22·28·40)를 무너뜨린다.

    "왜 이 값인가"에 답이 없는 값이라, 한 번 생기면 옆 자리가 그걸 베낀다.

    공백 변형(`font-size: 13.5px`)도 잡는다. 예전 정규식은 콜론 뒤 공백을 안
    받아서, 정작 위반 두 곳(.sel-opt 13.5px · .sel-sm .sel-opt 12.5px)이 **전부**
    빠져나갔다 — 검사는 초록인데 지키려던 값은 깨져 있었다. 바로 옆
    test_font_weight_800_은_큰_숫자_전용이다 가 같은 함정을 겪고 이미 `\\s*` 로
    고쳐 놨던 것을, 이 검사만 안 물려받고 있었다.
    """
    hits = re.findall(r"font-size:\s*\d+\.\d+px", _joined(_SOURCES))
    assert hits == [], f"크기 단계 밖 소수점: {sorted(set(hits))}"


def test_font_weight_800_은_큰_숫자_전용이다() -> None:
    """800(ExtraBold)은 22px 이상 큰 통계 숫자에만 쓴다.

    Wanted Sans 에는 800 이 실제로 있다(400~950 축). 그래서 전면 금지가 아니라
    자리를 못박는다 — 큰 숫자가 제목(700)과 다른 목소리를 내는 것이 목적이라,
    작은 글씨나 제목에 800 이 번지면 위계가 도로 뭉개진다. 영문 브랜드 워드마크는
    글자가 작아도 로고로 인식되게 하는 유일한 예외다. Gmarket Sans 자리
    (.headline)에는 800 이 없어 700 으로 스냅되므로 여전히 금지다.
    공백 변형(font-weight: 800)도 같이 잡는다 — 예전 정규식은 공백을 놓쳐
    .rail-label 의 800 이 몇 달을 숨어 지냈다.
    """
    bad = []
    for p in _SOURCES:
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not re.search(r"font-weight:\s*800", line):
                continue
            if re.search(r"font-weight:\s*(100 900|400 950)", line):
                continue  # @font-face 가변 축 선언
            # 삼항으로 크기·굵기를 함께 고르는 자리(caseStat)는 "24px;font-weight:800"
            # 처럼 크기가 굵기 바로 앞에 붙는다 — 그 꼴도 큰 숫자로 인정한다.
            ok = "brand-wordmark" in line or (re.search(r"font-size:\s*(2[2-8]|40)px", line)
                  or re.search(r"(2[2-8]|40)px;font-weight:\s*800", line)) \
                 and "headline" not in line
            if not ok:
                bad.append(f"{p.name}:{i}")
    assert bad == [], f"큰 숫자 밖에서 800 을 쓴다: {bad}"


def test_로컬_서체는_Wanted와_Gmarket_두_가족뿐이다() -> None:
    """두 가족만 두고 Gmarket은 홈의 짧은 대표 제목에만 제한한다.

    범위 라벨·설명·문서 정보와 실제 작업 화면 제목은 계속 Wanted Sans다.
    """
    font_dir = _WEB / "public" / "fonts"
    assert {p.name for p in font_dir.iterdir() if p.is_file()} == {
        "WantedSansVariable.woff2", "GmarketSansMedium.woff", "GmarketSansBold.woff",
    }
    css = (_WEB / "index.html").read_text(encoding="utf-8")
    assert "Gong Gothic" not in css
    assert "--font-display: 'Gmarket Sans'" in css
    assert ".tile-h { font-family: var(--font-body)" in css
    assert ".home-layout .tile-h { font-family: var(--font-display); font-weight: 700" in css
    assert ".home-layout .flow-title { font-family: var(--font-display); font-size: 15px" in css
    assert "color: var(--home-title)" in css
    assert ".tile-sub { font-size: 12px" in css
    assert ".history-doc-title { font-size: 14px" in css
    assert ".setup-section-title { margin: 0; font-family: var(--font-body)" in css


def test_var_뒤에_hex_알파를_붙이지_않는다() -> None:
    """`var(--accent)20` 은 무효 문법이다 — 색이 통째로 안 먹는다."""
    bad = []
    for p in _SOURCES:
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith("//"):
                continue
            if re.search(r"var\(--[a-z0-9-]*\)[0-9A-Fa-f]", line):
                bad.append(f"{p.name}:{i}")
    assert bad == [], f"var() 뒤 hex 알파: {bad}"


# ── 아직 규칙과 먼 것 — 상한으로만 막는다 ──────────────────────────────
# 줄이는 것이 목표다. 줄었으면 이 숫자도 같이 내린다(안 내리면 다시 늘 자리가 생긴다).

def test_하드코딩_hex_가_늘지_않는다() -> None:
    """색은 토큰만 쓴다. index.html 은 토큰을 **정의**하는 곳이라 여기서 뺀다."""
    # 78 → 67: 색을 역할 셋으로 정리하며(index.html 팔레트 주석) 하드코딩을
    # 토큰으로 바꿨다 — 홈 "지적 없음" 칩의 #10B981/#10B98122 는 --band-good-*,
    # 로그아웃의 #EF4444 는 --sev-crit-* 이 이미 들고 있던 값이었다. hex 는
    # 다크에서 안 뒤집힌다는 게 핵심이다. 줄었으면 상한도 같이 내린다.
    hits = re.findall(r"#[0-9A-Fa-f]{6}", _joined(_JS))
    assert len(hits) <= 67, f"하드코딩 hex 가 {len(hits)}회로 늘었다 (상한 67)"


def test_모서리_반지름이_늘지_않는다() -> None:
    """px 모서리는 사다리 토큰(--r-sm/md/lg/xl)으로 접었다 — 남는 px 는
    사다리 밖의 것들뿐이다: 알약(999px)과 4px 이하 미세 요소(진행바·mark).
    (내보내기 HTML(EXPORT_CSS)은 토큰이 없어 px 로 남는다 — 거기만 예외.)"""
    hits = re.findall(r"border-radius:(\d+)px", _joined(_JS))
    assert len(set(hits)) <= 6, f"모서리가 {len(set(hits))}종으로 늘었다 (상한 6)"
    # 166 → 171: 프로필 설정 화면이 들어오며 5회 늘었다. 쓴 값은 전부 기존
    # 값(6·8·10·12·16px)이라 **종류는 안 늘었다** — 늘려도 되는 종류의 증가다.
    # 171 → 173: 반영 확인이 "기계가 본 것"(그대로 있음·안 보임)을 뱃지로 함께
    # 보여주며 1회, 재검토 카드의 `신규` 뱃지로 1회. 둘 다 기존 값(6px)이다.
    # 173 → 174: 반영 확인 패널이 "이 화면을 어떻게 봐야 하는가"를 스스로 설명하는
    # 뜻풀이 상자를 얻으며 1회(8px). 같은 변경에서 판정 드롭다운이 네이티브
    # <select>(7px 인라인)에서 앱 셀렉트(.sel-sm, CSS)로 옮겨가 1회 줄었고,
    # "지난 판정" 뱃지가 1회 늘었다(6px). 새로 쓴 값은 없다.
    # 174 → 175: 반영 확인에서 `해당없음` 으로 정리한 지적임을 이번 검토 카드가
    # 말하는 뱃지로 1회(6px). 카드를 지우지 않는 대신 다는 표시다. 새 값은 없다.
    # 175 → 177: 뷰어 도구줄의 형광펜 켜기·끄기 단추로 1회, 검토 기록 전체 삭제
    # 단추로 1회. 둘 다 기존 값(8px)이라 **종류는 안 늘었다**.
    # 177 → 154: 모서리 단계(--r-sm/md/lg/xl)가 생기면서 카드·패널·드롭다운의
    # px 지정이 토큰으로 옮겨갔다. 종류도 16 → 15 로 줄었다.
    # 154 → 20: 단계에 걸치는 px(6~28)를 전부 토큰으로 접었다(2026-08-11).
    # 남는 것은 알약(999px)·4px 이하 미세 요소·EXPORT_CSS(토큰이 없는 내보내기
    # HTML) 뿐이다.
    assert len(hits) <= 20, f"모서리 지정이 {len(hits)}회로 늘었다 (상한 20)"


# ── 대비 ─────────────────────────────────────────────────────────────────
# 색은 상한으로만 막고 있지만, **읽히느냐**는 상한으로 못 잰다. 실제로 두 번
# 놓쳤다: `규칙 · 자동` 뱃지 글자가 흰 바탕에서 1.14:1(사실상 안 보임),
# 다크 모드 `--text-3` 이 패널 위 3.53:1(소속 팀이 안 읽힘).


def _hex(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _lum(c) -> float:
    def ch(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * ch(c[0]) + 0.7152 * ch(c[1]) + 0.0722 * ch(c[2])


def _ratio(fg: str, bg: str) -> float:
    hi, lo = sorted((_lum(_hex(fg)), _lum(_hex(bg))), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _token(name: str, *, dark: bool, _depth: int = 0) -> str:
    """index.html 에서 토큰 값을 읽는다. dark 면 두 번째(오버라이드) 선언.

    토큰이 다른 토큰을 가리키면(`--accent-surface: var(--accent)`) 따라간다.
    가리키기는 **일부러 쓰는 수법**이다 — 새 색을 만드는 대신 이미 있는 색을
    역할 이름으로 부르면, 팔레트에 값이 안 늘고 "왜 이 색인가"가 이름에 남는다.
    값만 읽으면 그 자리에서 대비 검사가 통째로 빠져나간다.
    """
    assert _depth < 4, f"{name} 토큰이 자기 자신을 가리킨다"
    css = (_WEB / "index.html").read_text(encoding="utf-8")
    found = re.findall(rf"{re.escape(name)}:\s*(#[0-9A-Fa-f]{{6}}|var\(--[a-z0-9-]+\))", css)
    assert found, f"{name} 토큰이 없다"
    if dark:
        assert len(found) > 1, f"{name} 에 다크 오버라이드가 없다"
        val = found[1]
    else:
        val = found[0]
    if val.startswith("var("):
        return _token(val[4:-1], dark=dark, _depth=_depth + 1)
    return val


def test_작은_글씨_토큰이_대비를_지킨다() -> None:
    """11~12px 글자라 AA 기준 4.5:1 을 넘겨야 한다."""
    cases = [
        ("--text-3", "--panel", False), ("--text-3", "--bg", False),
        ("--text-3", "--panel", True), ("--text-3", "--bg", True),
        ("--neutral-ink", "--panel", False), ("--neutral-ink", "--panel", True),
        ("--accent-ink", "--panel", False), ("--accent-ink", "--panel", True),
        # 심각도 뱃지 글자. 면이 반투명이라 패널에 얹힌 값으로 재야 맞지만,
        # 패널만으로 재도 더 빡빡한 쪽이라 이 문턱을 넘으면 실제로도 넘는다.
        ("--sev-maj-fg", "--panel", False), ("--sev-min-fg", "--panel", False),
        ("--sev-info-fg", "--panel", False),
    ]
    bad = []
    for fg, bg, dark in cases:
        got = _ratio(_token(fg, dark=dark), _token(bg, dark=dark))
        if got < 4.5:
            bad.append(f"{'다크' if dark else '라이트'} {fg} on {bg} = {got:.2f}:1")
    assert not bad, "대비 미달: " + " · ".join(bad)


def test_채운_면_위_흰_글자가_읽힌다() -> None:
    """`--accent-surface` 는 흰 글자를 얹으라고 있는 면이다(사이드바 선택 항목).

    마스코트의 딥 블루는 공식 Primary를 그대로 쓸 만큼 깊고, 두 테마 모두
    흰 글자 AA를 유지한다.
    """
    bad = []
    for dark in (False, True):
        got = _ratio(_token("--accent-surface", dark=dark), "#FFFFFF")
        if got < 4.5:
            bad.append(f"{'다크' if dark else '라이트'} = {got:.2f}:1")
    assert not bad, "채운 면 위 흰 글자 대비 미달: " + " · ".join(bad)


def test_공식_브랜드색과_액션면의_역할이_분명하다() -> None:
    """두 공식 색과 그래픽용 밝은 블루를 고정하고, 채운 면은 Primary로 쓴다."""
    assert _token("--brand-primary", dark=False).upper() == "#356998"
    assert _token("--brand-secondary", dark=False).upper() == "#F2E0D4"
    assert _token("--brand-highlight", dark=False).upper() == "#4C97D6"
    assert _token("--brand-accent", dark=False).upper() == "#FABE53"
    assert _token("--accent", dark=False) == _token("--brand-primary", dark=False)
    assert _token("--accent-surface", dark=False) == _token("--brand-primary", dark=False)
    assert _token("--accent-surface", dark=True) == _token("--brand-primary", dark=False)



def test_로그인_워드마크_포인트는_브랜드면에서_읽힌다() -> None:
    """40px bold `Suree`는 그라데이션 양 끝에서 큰 글자 대비 3:1을 넘긴다."""
    color = _token("--brand-accent", dark=False)
    for surface in ("--brand-primary", "--brand-deep"):
        got = _ratio(color, _token(surface, dark=False))
        assert got >= 3, f"워드마크가 {surface}에 묻힌다 ({got:.2f}:1)"


def test_라이트_앱_캔버스는_브랜드_크림이_아니다() -> None:
    """Secondary가 큰 캔버스를 덮으면 앱 전체가 베이지색 브랜드 면처럼 읽힌다."""
    assert _token("--bg", dark=False).upper() == "#F7F6F3"
    assert _token("--bg", dark=False) != _token("--brand-secondary", dark=False)


def test_라이트_경계선은_브랜드_크림에서_파생하지_않는다() -> None:
    """큰 면의 테두리는 기존 웜 그레이 단계로 두어 카드 외곽이 진해지지 않게 한다."""
    expected = {
        "--line": "#E2DED7",
        "--line-2": "#EAE6DF",
        "--line-dashed": "#C8C1B8",
        "--neutral-strong": "#E2DED7",
    }
    for name, color in expected.items():
        assert _token(name, dark=False).upper() == color


def test_라이트_공용_hover는_진한_크림이_아니다() -> None:
    """사이드바·프로필·최근 검토의 넓은 면은 옅은 웜 그레이 하나를 공유한다."""
    assert _token("--state-hover-neutral", dark=False).upper() == "#F3F0EB"
    assert _token("--state-hover-neutral", dark=False) != _token("--brand-secondary", dark=False)


def test_로그인_크림_글자가_브랜드면에서_읽힌다() -> None:
    """Secondary 크림은 Primary 위 작은 글자 기준까지 지킨다."""
    got = _ratio(_token("--brand-secondary", dark=False), _token("--brand-primary", dark=False))
    assert got >= 4.5, f"크림 글자가 Primary에 묻힌다 ({got:.2f}:1)"


def test_다크_표면은_한_웜차콜_계열이다() -> None:
    """다크 화면에 네이비·청회색 면이 섞여 조각나 보이지 않게 한다."""
    # 카드가 배경과 한 덩어리로 보인다는 지적(2026-08-14)에 캔버스와 패널을
    # 양쪽으로 벌렸다. 패널만 밝히면 파랑 기준 타일이 패널에 묻힌다
    # (아래 test_채운_면이_패널에_묻히지_않는다 의 2.5:1) — 그래서 캔버스가 내려갔다.
    expected = {
        "--bg": "#191715",
        "--panel": "#2B2825",
        "--state-hover-neutral": "#332F2B",
        "--line": "#413B36",
        "--text": "#F7F1EB",
        "--text-2": "#D8CEC5",
        "--text-3": "#AEA298",
    }
    for name, color in expected.items():
        assert _token(name, dark=True).upper() == color, f"{name}이 웜차콜 체계에서 벗어났다"


def test_채운_면이_패널에_묻히지_않는다() -> None:
    """다크에서 채운 면이 어두우면 "고른 항목"이 배경과 구별되지 않는다.

    라이트는 흰 패널 위라 어떤 채움도 눈에 띄지만, 다크는 패널 자체가 어두워서
    채운 면도 어두우면 그냥 안 보인다.
    """
    got = _ratio(_token("--accent-surface", dark=True), _token("--panel", dark=True))
    assert got >= 2.5, f"다크에서 선택 항목이 패널에 묻힌다 ({got:.2f}:1)"


def test_면_전용_색을_글자에_쓰지_않는다() -> None:
    """`--neutral-strong`(Slate 200)은 **면** 색이다.

    다크 오버라이드가 없어 두 테마에서 같은 연회색이고, 흰 바탕 글자로 쓰면
    1.14:1 — 사실상 안 보인다. 검토 기준 화면의 `규칙 · 자동` 뱃지가 그랬다.
    팔레트 주석도 쓰지 말라고 적어 두었는데 코드가 쓰고 있었다.

    SVG 삽화의 fill·stop-color 는 면이라 괜찮다 — 글자로 쓰는 것만 막는다.
    """
    js = _joined(_JS)
    assert "color:var(--neutral-strong)" not in js.replace(" ", ""), \
        "면 전용 색을 글자에 쓴다"
    # 뱃지 팔레트는 [배경, 글자, 테두리] 다. 두 번째가 글자색 — 예전엔 마지막
    # 칸을 집었는데, 테두리 칸이 붙으면서 엉뚱한 값을 검사하게 됐다.
    tone = js[js.index("var HOW_TONE"):]
    tone = tone[:tone.index("};")]
    for line in tone.splitlines():
        if "[" not in line or "]" not in line or line.strip().startswith("//"):
            continue
        inner = line[line.index("[") + 1:line.rindex("]")]   # 줄 끝 쉼표를 안 집게
        fg = inner.split(",")[1]
        assert "--neutral-strong" not in fg, f"뱃지 글자색이 면 색이다: {line.strip()}"


def test_움직임을_줄여달라는_설정을_지킨다() -> None:
    """무한 반복 애니메이션이 일곱 종류(blobFloat·dvpulse·floatOrb·shimmer·spin)
    돌고 있는데 `prefers-reduced-motion` 이 저장소 전체에 한 곳도 없었다.

    전정 장애가 있는 사람에게는 로그인 화면의 떠다니는 도형만으로도 어지럽다.
    접근성 기본은 생략하지 않는다(CLAUDE.md 개발 원칙).
    """
    css = (_WEB / "index.html").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in css, "움직임 줄이기 설정을 안 본다"

    block = css[css.index("@media (prefers-reduced-motion: reduce)"):]
    block = block[:block.index("\n    @keyframes")]
    assert "animation-duration" in block, "애니메이션을 안 줄인다"
    assert "animation-delay: 0ms" in block, "축소 화면도 진입 지연 동안 비어 있다"
    assert "transition-duration" in block, "전환을 안 줄인다"
    # 로딩 회전만 남긴다 — "아직 일하는 중"을 그 회전이 혼자 말한다(검토 최대 5분).
    # iteration-count 1 로 두면 한 바퀴 돌고 굳어서 아예 없는 것보다 나쁘다.
    assert "spin" in block, "로딩 회전까지 멈춰 멎은 화면과 구별되지 않는다"


def test_로그인_3d는_브랜드_접점에만_있고_포인터와_축소설정을_본다() -> None:
    """업무 화면이 아니라 로그인 히어로만 최대 2도 반응한다."""
    css = (_WEB / "index.html").read_text(encoding="utf-8")
    js = (_WEB / "app.js").read_text(encoding="utf-8")
    views = (_WEB / "views.js").read_text(encoding="utf-8")
    assert "data-hero-scene" in views and "hero-doc-left" in views and "hero-doc-right" in views
    assert "function wireHeroParallax" in js
    wire = js[js.index("function wireHeroParallax"):]
    wire = wire[:wire.index("\n  }") + 4]
    assert "reduceMotion()" in wire, "움직임 축소 설정에서도 포인터 원근이 돈다"
    assert "(hover: hover) and (pointer: fine)" in wire, "터치에서도 장식 원근을 건다"
    assert "* 4" in wire, "기울기 상한 2도 계약이 사라졌다"
    assert "heroDocIn" in css and "heroLensSweep" in css
    assert "infinite" not in css[css.index("@keyframes heroDocIn"):css.index("@keyframes heroMascotIn")], \
        "로그인 문서가 계속 움직인다"


def test_움직이는_hover_는_마우스에만_건다() -> None:
    """지적 카드는 hover 로 1px, 홈 액션 타일은 2px 떠오른다.

    손가락은 탭 한 번에 hover 를 흘리고 가므로, 터치에서는 카드가 떠오른 채로
    붙지 않도록 움직이는 hover를 포인터로 막는다.
    """
    css = (_WEB / "index.html").read_text(encoding="utf-8")

    def gated(selector: str) -> bool:
        """규칙이 (hover: hover) and (pointer: fine) 블록 **안**에 있는가.

        여는 미디어 쿼리와 선택자 사이에 그 블록을 닫는 줄이 없으면 안이다
        (이 파일은 최상위 규칙을 4칸 들여쓰므로 `\\n    }` 가 닫는 줄이다).
        """
        before = css[:css.index(selector)]
        opened = before.rfind("@media (hover: hover) and (pointer: fine)")
        return opened >= 0 and "\n    }" not in before[opened:]

    for sel in (".fcard:hover", ".fcard.on:hover", ".tile.act:hover"):
        assert sel in css, f"{sel} 규칙이 사라졌다"
        assert gated(sel), f"{sel} 가 포인터 게이트 밖에 있다"
    # 게이트만 있고 정작 움직임이 밖에 남으면 아무것도 못 막는다.
    assert "translateY(-1px)" in css and "translateY(-2px)" in css


def test_움직임을_줄여도_기준_층을_다_보여준다() -> None:
    """움직임 줄이기는 **덜 움직이는 것이지 덜 보는 것이 아니다.**

    한때 기준 타일은 층(공통·팀별)을 겹쳐 쌓고 6초마다 한 장씩 돌렸고, 회전을
    끄면서 `.crit-slide:not(:first-child) { display:none }` 으로 나머지를 지웠다
    — 움직임을 줄여 달라고 한 사람은 공통 층만 보고 **팀별 층이 있다는 사실조차**
    몰랐다. 그 뒤 회전만 끄고 세로로 펴는 방식으로 고쳤고, 지금은 아예 안 돈다
    (층을 늘 쌓아서 낸다). 회전이 없으니 이 블록에 기준 타일 예외가 있을 이유도
    없다 — 모두가 늘 같은 화면을 본다.

    규칙은 그대로다: 이 블록은 기준 타일의 무엇도 숨기지 않는다. 다시 도는 것을
    넣고 싶어지면 그때도 정보가 아니라 움직임만 줄여야 한다.
    """
    css = (_WEB / "index.html").read_text(encoding="utf-8")
    block = css[css.index("@media (prefers-reduced-motion: reduce)"):]
    block = block[:block.index("\n    @keyframes")]

    hidden = {
        line.strip().split("{")[0].strip()
        for line in block.splitlines()
        if "display: none" in line
    }
    assert not {h for h in hidden if "crit" in h}, f"기준 층을 숨긴다: {hidden}"
    # 애초에 돌지 않는다. 키프레임이 남아 있으면 이 블록이 다시 필요해진다.
    # (선언만 찾는다 — 무엇을 걷어냈는지 적어 둔 주석까지 걸리면 안 된다.)
    assert "@keyframes critRot" not in css and "@keyframes critDot" not in css, \
        "기준 타일 회전 키프레임이 남아 있다 — 걷어낸 줄 알았던 것이 돌고 있다"


def test_화면_진입_연출은_한_자리에서만_씌운다() -> None:
    """홈과 검토 진행 화면만 진입 연출이 있고 나머지 열두 화면은 툭 갈렸다.

    화면마다 따로 붙이면 반드시 갈린다 — 새 화면을 만든 사람이 그 한 줄을
    안 베끼면 그 화면만 연출이 없다. `body()` 가 `#main-scroll` 에 한 번
    씌우면 어느 화면이든 같은 방식으로 들어온다.
    """
    js = (_WEB / "views.js").read_text(encoding="utf-8")
    body = js[js.index("\n  function body(v) {"):]
    body = body[:body.index("\n  }")]
    assert "main-scroll" in body
    # 진입 연출은 body() 안에서만 붙는다. 화면 함수가 각자 붙이기 시작하면
    # 새 화면을 만든 사람이 그 한 줄을 안 베끼는 순간 그 화면만 연출이 없다.
    assert "animation:fadeIn" in body, "진입 연출이 body() 밖에 있다 — 화면마다 갈린다"
    others = js.replace(body, "")
    assert "data-scroll=\"main\"" not in others, "#main-scroll 을 다른 데서도 만든다"

    # 음수 지연이 있어야 진입 창(250ms) 안의 재렌더에서 되감기지 않는다.
    assert "animation-delay:-" in body, "재렌더마다 연출이 처음부터 다시 돈다"

    # 관용구는 이미 있는 것을 쓴다 — 화면 진입 전용 키프레임을 새로 만들면
    # 지속시간 사다리 밖의 값이 하나 더 늘고, 아무도 그걸 다시 안 맞춘다.
    css = (_WEB / "index.html").read_text(encoding="utf-8")
    assert "@keyframes fadeIn" in css and "@keyframes listIn" in css
    # 3D 회전은 안 쓴다. 타일 한 장이면 몰라도 화면 전체가 매번 꺾이면 과하다.
    assert "perspective(" not in css, "화면 진입이 3D 로 꺾인다 — 매번 보는 화면이다"


def test_스크롤_이동도_움직임_줄이기를_본다() -> None:
    """CSS 의 `scroll-behavior: auto !important` 는 JS 가 behavior 를 명시하면
    진다. scrollIntoView 에 "smooth" 를 박아두면 움직임을 줄여 달라고 한
    사람에게도 문서가 미끄러진다 — 그래서 JS 가 직접 물어봐야 한다.
    """
    js = (_WEB / "app.js").read_text(encoding="utf-8")
    assert "prefers-reduced-motion" in js, "JS 가 움직임 줄이기 설정을 안 본다"
    call = js[js.index("scrollIntoView("):]
    call = call[:call.index("});") + 3]      # reduceMotion() 의 괄호에 안 걸리게
    assert "smooth" in call, "지적을 골라도 문서가 순간이동한다"
    assert "reduceMotion()" in call, "smooth 를 무조건 건다 — 설정을 무시한다"


def test_한_레인이_끝나도_나머지_shimmer_를_안_끊는다() -> None:
    """레인 하나가 완료로 넘어갈 때 진행 화면 전체를 다시 그리면, 아직 도는
    다른 레인들의 shimmer 가 전부 처음으로 튀어 흰빛이 한꺼번에 번쩍인다.
    바뀐 레인의 알맹이만 갈아끼우고 겉 wrapper 는 살려둔다 — 노드가 살아
    있어야 opacity(.5→1) 전환도 실제로 돈다.
    """
    js = (_WEB / "app.js").read_text(encoding="utf-8")
    body = js[js.index("function updateLanesInPlace"):]
    body = body[:body.index("\n  }") + 4]
    assert "laneInner" in body, "상태가 바뀐 레인만 갈아끼우지 않는다"
    # 레인 개수가 달라졌을 때(구성 변경)만 통째로 폴백한다. 상태 전환은 아니다.
    assert body.count("return false") == 1, "상태 전환에서 여전히 통째로 다시 그린다"


def test_투명도를_줄여달라는_설정을_지킨다() -> None:
    """유리 면(--glass*)과 backdrop-filter 11군데가 이 설정을 안 보고 있었다.

    움직임 줄이기와 같은 판단의 나머지 절반이다. blur 는 views.js 가 인라인
    style 로 붙어서 클래스로는 못 집는다 — 속성 선택자여야 실제로 꺼진다.
    """
    css = (_WEB / "index.html").read_text(encoding="utf-8")
    assert "prefers-reduced-transparency" in css, "투명도 줄이기 설정을 안 본다"

    block = css[css.index("@media (prefers-reduced-transparency: reduce)"):]
    block = block[:block.index("\n    @keyframes")]
    assert "--panel-glass: var(--panel)" in block, "반투명 면을 불투명하게 안 바꾼다"
    assert '[style*="backdrop-filter"]' in block, "인라인 blur 를 못 끈다"
    # 진행바 sweep 은 재질이 아니라 "일하는 중" 신호다 — spin 을 남기는 것과 같다.
    assert "--shimmer" not in block, "진행바 반짝임까지 껐다"


def _pseudo_lines(pseudo: str) -> dict[str, list[int]]:
    """`.foo:hover` 처럼 **자기 자신**에 걸린 규칙의 줄 번호를 선택자별로 모은다.

    `.hrow:hover .arrow` 는 자식을 겨냥하므로 뺀다 — 같은 면의 상태가 아니다.
    """
    out: dict[str, list[int]] = {}
    for i, line in enumerate((_WEB / "index.html").read_text(encoding="utf-8").splitlines(), 1):
        head = line.split("{")[0]
        if pseudo not in head:
            continue
        for sel in head.split(","):
            sel = re.sub(r":not\([^)]*\)", "", sel).strip()
            if pseudo not in sel or " " in sel[sel.index(pseudo):]:
                continue
            out.setdefault(sel[:sel.index(pseudo)], []).append(i)
    return out


def test_누름_반응이_hover_에_가려지지_않는다() -> None:
    """`:hover` 와 `:active` 는 특정도가 같아서 **나중에 온 쪽이 이긴다.**

    마우스로 누르면 두 상태가 동시에 켜지므로, `:active` 가 자기 `:hover` 보다
    위에 있으면 누름 반응이 조용히 죽는다 — 규칙은 있는데 화면에선 안 보인다.
    실제로 `.backlink` · `.sel-opt` 가 이렇게 한 번 죽었다(2026-08-12).

    변형까지 본다: `.btn:active` 는 `.btn-primary:hover` 보다도 뒤여야 한다
    (같은 버튼에 둘 다 붙고 특정도도 같다). 이걸 안 봐서 주요 버튼의 누름
    반응이 마우스에서 한 번도 안 보였다 — 규칙은 두 벌이나 있었는데도.
    """
    hovers, actives = _pseudo_lines(":hover"), _pseudo_lines(":active")
    assert actives, "누름 반응이 하나도 없다"
    dead = {}
    for sel, lines in actives.items():
        # 같은 요소에 함께 걸릴 수 있는 hover: 자기 자신과 그 변형(.btn → .btn-primary).
        rival = [n for h, hl in hovers.items() if h == sel or h.startswith(sel + "-")
                 for n in hl]
        if rival and min(lines) < max(rival):
            dead[sel] = (max(rival), min(lines))
    assert not dead, f"hover 에 가려진 누름 반응(:active 줄 < :hover 줄): {dead}"


# ── 사다리 ────────────────────────────────────────────────────────────────
# 크기·행간·여백은 상한이 아니라 **집합**으로 막는다. 색·모서리와 달리 값마다
# 판단이 필요한 종류가 아니라, 사다리 안에서 고르기만 하면 되는 종류다.

# 48 은 로그인 브랜드 면의 워드마크 한 자리다(.login-brand .brand-wordmark).
# 40 이었을 때 280px 마스코트와 18px 슬로건 사이에서 묻혀 한 단 올렸다 —
# 40 바로 위 칸이라 사다리를 흔들지 않는다. **아이콘 예외로 넘기지 않는 이유**:
# 그 예외는 `1em` svg 를 감싼 요소의 font-size 자리이고, 이건 글자다. 글자를
# 아이콘 칸에 얹으면 그 예외가 무슨 뜻이었는지 흐려진다.
_SIZE_LADDER = {11, 12, 13, 14, 15, 18, 22, 28, 40, 48}


def test_글자_크기가_사다리_안에_있다() -> None:
    """한때 실제로 쓰이는 크기가 18종이었다(문서에 적힌 사다리는 8단인데).

    9 · 10 · 12.5 · 13.5 · 16 · 17 · 19 · 20 · 24 가 섞여 있었고, 그중 절반은
    한 번씩만 쓰인 값이라 "왜 이 값인가"에 답이 없었다. 14 는 38 회 쓰여 이미
    자리를 잡았으므로 없애지 않고 사다리에 들였다(index.html 서체 주석 참고).

    남는 예외는 **아이콘 크기**뿐이다. ICONS 의 svg 가 width:1em 이라 감싼
    요소의 font-size 가 곧 아이콘 크기가 된다 — 글자 사다리와 다른 체계라
    접지 않았고, 대신 늘지 않게 상한으로 막는다.
    """
    hits = [int(n) for n in re.findall(r"font-size:\s*(\d+)px", _joined(_SOURCES))]
    assert hits, "font-size 를 하나도 못 찾았다 — 검사가 무의미해졌다"
    off = sorted(n for n in hits if n not in _SIZE_LADDER)
    assert len(off) <= 6, f"사다리 밖 크기가 {len(off)}회로 늘었다 (아이콘 상한 6): {off}"


def test_행간이_네_단뿐이다() -> None:
    """예전엔 14종이었다 — 1.45 · 1.5 · 1.55 · 1.6 · 1.65 가 나란히 있었다.

    아무도 구별 못 하는 차이인데 값을 고르는 비용은 매번 냈다. 크기와 짝지어
    한 세트로 정한다: 1(큰 숫자) · 1.2(큰 제목) · 1.4(조밀한 UI) · 1.6(본문).
    """
    hits = re.findall(r"line-height:\s*([0-9.]+)", _joined(_SOURCES))
    assert hits, "line-height 를 하나도 못 찾았다 — 검사가 무의미해졌다"
    off = sorted({v for v in hits if v not in {"1", "1.2", "1.4", "1.6"}})
    assert not off, f"사다리 밖 행간: {off}"


def test_여백이_짝수px다() -> None:
    """홀수 여백에는 근거가 있을 수 없다 — 1px 옆 값과 구별되지 않는다.

    한때 padding 만 31 종이었고 1 · 3 · 5 · 7 · 9 · 11 · 13 · 15 · 35px 이
    섞여 있었다. 짝수는 사다리 자체가 아니라 **사다리를 만들 수 있는 바닥**이다
    (다음 단계는 4의 배수로 접는 것 — 그건 눈으로 보며 해야 한다).

    **음수 1px 만 예외다.** 그건 여백이 아니라 **선 맞춤**이다 — 1px 테두리 위에
    다른 테두리를 정확히 포개려면 그만큼 끌어당기는 수밖에 없고, "1px 옆 값과
    구별되지 않는다"는 이 규칙의 근거가 거기엔 안 걸린다(옆 값이 없다. 덮을
    선의 두께가 값을 정한다). 양수 1px 은 그대로 막는다 — 그건 여백이다.
    """
    prop = r"(?:padding|margin|gap|row-gap|column-gap)(?:-(?:top|right|bottom|left))?"
    odd = []
    for p in _SOURCES:
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if line.lstrip().startswith(("//", "*", "/*")):
                continue                      # 주석 속 치수 설명은 여백이 아니다
            for decl in re.findall(rf"\b{prop}\s*:\s*([^;\"'}}]*)", line):
                odd += [f"{p.name}:{i} {n}px" for n in re.findall(r"(-?\d+)px", decl)
                        if int(n) % 2 and int(n) != -1]
    assert not odd, f"홀수 여백: {odd[:12]}{' …' if len(odd) > 12 else ''}"


def test_브랜드_토큰이_죽은_채로_남지_않는다() -> None:
    """정의·문서화·대비검사까지 다 받아 놓고 **쓰는 곳이 0인** 토큰이 있었다.

    `--brand-secondary` 가 그랬다(2026-08-12 확인). 팔레트 주석은 "로고·로그인처럼
    의도적인 브랜드 장면에만 쓴다"고 말하고, 옆에는 그 색이 브랜드 면 위에서
    읽히는지 재는 검사까지 있었는데, 정작 화면 어디에도 안 나왔다 — 색을 바꿔도
    아무것도 안 변했다. 그런 토큰은 팔레트가 아니라 주석이다.

    대비 검사는 "읽히느냐"를 재지 "쓰이느냐"를 못 잰다. 그래서 이 검사가 있다.
    """
    # index.html 도 본다 — 사용처가 JS 인라인에서 CSS 클래스로 이사할 수 있다
    # (--brand-primary 가 실제로 그랬다). 정의 줄은 `var(` 형태가 아니라
    # 여기 걸리지 않으므로, CSS 를 포함해도 죽은 토큰은 여전히 잡힌다.
    src = _joined(_SOURCES)
    # --brand-secondary 는 **알면서 비워 둔 자리**다. 브랜드 3색 정립(2026-08-14)
    # 때 받침 면(크림·탠 아이콘 칩)으로 화면에 세워 봤는데 "화면은 주색
    # 톤온톤"으로 결론 나며 도로 나갔다 — 로그인 같은 브랜드 장면이 생기면
    # 그때 목록에 다시 넣는다. --brand-accent(부리 골드, 전 --brand-wordmark)는
    # 워드마크·캐릭터 전용으로 남는다.
    dead = [t for t in ("--brand-primary", "--brand-accent")
            if f"var({t})" not in src]
    assert not dead, f"브랜드 토큰이 화면에 안 쓰인다: {dead}"


def test_홈_기준_도식은_중간_폭에서도_사라지지_않는다() -> None:
    """도식만 숨기고 grid 첫 행을 남기면 기준 타일 가운데 큰 빈칸이 생긴다."""
    css = (_WEB / "index.html").read_text(encoding="utf-8")
    assert ".crit-figure { display: none" not in css, \
        "중간 화면에서 기준 관계는 사라지고 빈 행만 남는다"
    assert "grid-template-columns: minmax(96px, 1fr) 36px 80px" in css, \
        "숨기는 대신 도식을 조여 유지하는 반응형 규칙이 없다"
