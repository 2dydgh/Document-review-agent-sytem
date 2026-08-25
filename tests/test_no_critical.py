"""CRITICAL 등급을 두지 않는다.

**어느 체커도 내지 않았다.** 심각도를 지정하는 45곳 중 0곳, 실제 기록 200건에서
0건. 그런데 화면 범례에는 늘 "Critical 0" 이 떠서 *"심각한 문제를 찾아봤고 없었다"*
는 거짓말을 했다 — 이 저장소가 가장 경계하는 실패(지적 0건과 검사 안 함을 섞는 것)와
같은 종류다.

빼도 배치는 안 바뀐다. CRITICAL 은 비어 있었으므로 major·minor·info 는 그대로다.

최상위 등급이 정말 필요해지면 **그것을 내는 체커와 함께** 다시 넣는다. 등급만 먼저
정의해 두면 아무도 안 쓰는 자리가 또 생긴다 — 한 번 그랬다.
"""
from __future__ import annotations

import re
from pathlib import Path

from modules.shared import Severity

_ROOT = Path(__file__).resolve().parents[1]
WEB = _ROOT / "web"


def _js(name: str) -> str:
    return (WEB / name).read_text(encoding="utf-8")


def test_severity_는_중대성_3단이다() -> None:
    assert [s.value for s in Severity] == ["info", "minor", "major"]
    assert not hasattr(Severity, "CRITICAL"), "죽은 등급이 되살아났다"


def test_파이썬_배선에_안_남아_있다() -> None:
    """정렬·PDF 형광펜 색·PDF 라벨. 등급만 지우고 배선을 남기면 다음 사람이
    "색은 있는데 왜 안 나오지" 를 좇게 된다."""
    for rel in ("report/collector.py", "report/annotate_pdf.py", "report/pdf_summary.py"):
        src = (_ROOT / "src" / "modules" / rel).read_text(encoding="utf-8")
        body = "\n".join(l for l in src.split("\n") if not l.lstrip().startswith("#"))
        assert "critical" not in body.lower(), f"{rel} 에 critical 배선이 남아 있다"


def test_화면_배선에_안_남아_있다() -> None:
    for name in ("views.js", "app.js", "pdfview.js", "docreview-data.js"):
        body = "\n".join(l for l in _js(name).split("\n")
                         if not l.lstrip().startswith("//"))
        # --sev-crit-* 토큰은 등급이 아니라 '빨강 신호'로 계속 쓴다(비교 검토의
        # 누락 · 폴더 검토 에러 배너 · 필드 대조표의 다름). 그건 걸러낸다.
        body = body.replace("sev-crit-bg", "").replace("sev-crit-fg", "").replace("sev-crit-bd", "")
        assert "critical" not in body.lower(), f"{name} 에 critical 이 남아 있다"


def test_등급_목록을_한_곳에서_돌린다() -> None:
    """등급을 더하거나 빼도 한 곳만 고치면 되게. 예전엔 배열을 네 군데에 적어
    두고 counts.critical 을 직접 읽는 자리까지 있어서, 등급을 빼면 그 자리가
    undefined 로 NaN 이 됐다."""
    views = _js("views.js")
    assert 'var ORDER = ["major", "minor", "info"];' in views, "등급 목록이 없다"
    # 하드코딩된 등급 배열이 또 있으면 안 된다.
    dup = re.findall(r'\["major",\s*"minor",\s*"info"\]', views)
    assert len(dup) == 1, f"등급 배열이 {len(dup)}곳에 적혀 있다 — ORDER 를 쓸 것"
    assert "counts.major" not in views, "counts 를 등급별로 직접 읽는다 — ORDER 로 돌 것"


def test_사라진_등급이_문서에_남아_있지_않다() -> None:
    claude = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    assert "severity(major|minor|info)" in claude, \
        "CLAUDE.md 의 Finding 스키마가 실제 등급과 다르다"
