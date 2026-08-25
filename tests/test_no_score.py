"""점수(100점 만점 단일 숫자)를 두지 않는다.

한 번 있었다가 뺐다. 되돌아오기 쉬운 종류의 결정이라 여기서 막는다 — 화면에
숫자 하나가 비어 보이면 누군가 "점수가 없네" 하고 다시 넣는다.

**뺀 이유** (실측 176건 · 지적 2,248건):

- 가중치(20/10/4/1)와 구간(80/55)에 실측 근거가 없었다. 이 저장소의 다른 상수와
  달리 근거 주석이 없는 유일한 값들이었다.
- `critical × 20` 은 **절대 발동하지 않는 항**이었다. 어떤 체커도 CRITICAL 을
  내지 않는다.
- `info × 1` 은 개념 오류였다. INFO 는 "못 봤다 · 걸러냈다"는 **검토 과정 보고**지
  문서의 결함이 아니다. 환각 필터가 잘 작동해 많이 걸러낼수록 점수가 깎였다.
- 감점의 92% 가 `consistency` minor 하나였다 — 사실상 `점수 ≈ LLM 이 얼마나
  말이 많았나`.
- 길이 보정이 없어 분량이 곧 점수였다: 짧은 절반(평균 2,443자) 83.8점 vs
  긴 절반(평균 65,269자) **43.9점**.
- minor 25건이면 무조건 0점이라 나쁜 쪽 끝에서 변별력이 사라졌다(10% 가 바닥).

다시 넣으려면 **정답 문서 셋으로 눈금을 검증한 뒤**다 (CLAUDE.md "기능 방침").
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
WEB = _ROOT / "web"
VIEWS_JS = (WEB / "views.js").read_text(encoding="utf-8")
INDEX_HTML = (WEB / "index.html").read_text(encoding="utf-8")


def _code_lines(src: str) -> str:
    """주석을 걷어낸다 — 왜 뺐는지 설명하는 주석이 스스로 걸리면 안 된다."""
    return "\n".join(l for l in src.split("\n") if not l.lstrip().startswith("//"))


def test_점수_공식이_없다() -> None:
    code = _code_lines(VIEWS_JS)
    # 가중 감점 공식의 지문. 하나라도 살아 있으면 되돌아온 것이다.
    assert not re.search(r"critical\s*\*\s*20", code), "점수 공식이 되살아났다"
    assert not re.search(r"100\s*-\s*\(", code), "100점 만점 감점식이 있다"
    assert "scoreLabel" not in code, "판정 라벨(양호/개선 필요/위험)이 되살아났다"


def test_판정_어휘를_쓰지_않는다() -> None:
    """"위험"은 검사 결과로 말할 근거가 없다. "지적 없음"만 말할 수 있다."""
    code = _code_lines(VIEWS_JS)
    for word in ("개선 필요", "양호"):
        assert word not in code, f"근거 없는 판정 어휘 '{word}' 가 화면에 있다"


def test_죽은_밴드_토큰이_없다() -> None:
    """점수를 뺐으므로 warn/bad 밴드는 쓸 곳이 없다. good 은 '이상 없음' 이 쓴다."""
    for dead in ("--band-warn-fg", "--band-bad-fg"):
        assert dead not in INDEX_HTML, f"{dead} 가 정의만 남아 있다"
    assert "--band-good-fg" in INDEX_HTML, "'이상 없음' 칩 색이 사라졌다"
    assert "var(--band-good-fg)" in VIEWS_JS, "'이상 없음' 칩이 그 색을 안 쓴다"


def test_큰_자리에는_실제로_센_것이_온다() -> None:
    """점수를 빼고 남은 40px 자리에는 지적 건수가 온다 — 비워두지 않는다."""
    # 패널 껍데기는 issuesShell 이 그린다 — 단일 검토와 폴더 검토가 같이 쓴다.
    panel = VIEWS_JS[VIEWS_JS.index("function issuesShell("):]
    panel = panel[:panel.index("function sevChipsOf(")]
    assert "font-size:40px" in panel, "요약 블록의 큰 숫자 자리가 비었다"
    big = panel[panel.index("font-size:40px"):]
    assert "total" in big[:400], "큰 자리에 지적 건수가 아닌 것이 왔다"


def test_방침이_규칙서에_적혀_있다() -> None:
    """코드에서만 지우면 다음 사람이 이유를 모른 채 되돌린다."""
    claude = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "점수" in claude and "넣지 않는다" in claude, \
        "CLAUDE.md 에 점수를 두지 않는다는 방침이 없다"
    assert "정답 문서 셋" in claude, "다시 넣을 조건이 안 적혀 있다"
