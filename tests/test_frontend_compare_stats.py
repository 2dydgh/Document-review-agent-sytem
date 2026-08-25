"""비교 결과 화면이 서버가 센 것을 빠짐없이 그리는지 지키는 회귀 테스트.

프론트엔드는 빌드도 JS 테스트 러너도 없는 바닐라 SPA라 소스 수준에서 막는다.

여기서 지키는 규칙은 하나다: **서버가 센 항목을 화면이 조용히 빼면 안 된다.**
`out_of_scope`(범위 밖)가 이미 같은 이유로 카드가 되어 있다 — "그렇다고 감추지도
않는다. 개수를 띄워 사용자가 범위를 확인하게 한다."

`rolled_up`(부모 수준 검증)은 더 위험하다. 커버리지 분모(requirements)에는
들어가는데 화면에 안 보이면, SHN34 실측 기준으로 누락 0·불일치 0·근거없음 0인데
커버리지만 63%로 떨어져 보인다 — 나머지 37%가 어디서 왔는지 화면만 봐서는
알 길이 없다.
"""
from __future__ import annotations

from pathlib import Path

VIEWS_JS = Path(__file__).resolve().parent.parent / "web" / "views.js"
UI_EXPORT = (Path(__file__).resolve().parent.parent / "src" / "modules"
             / "report" / "ui_export.py")


def test_rolled_up_is_counted_by_the_server() -> None:
    assert "rolled_up" in UI_EXPORT.read_text(encoding="utf-8")


def test_rolled_up_count_is_drawn_on_screen() -> None:
    """서버가 세는데 화면이 안 그리면 그 항목은 사용자에게 존재하지 않는 것이다."""
    views = VIEWS_JS.read_text(encoding="utf-8")
    assert "stats.rolled_up" in views, "화면이 부모 수준 검증 건수를 읽지 않는다"


def test_rolled_up_card_has_a_human_readable_label() -> None:
    """정규식이나 내부 상태명을 검토자에게 보여줄 수는 없다."""
    views = VIEWS_JS.read_text(encoding="utf-8")
    assert "부모 수준 검증" in views
