"""업로드한 문서에 맞는 체크리스트를 화면이 짚어주는지 지키는 회귀 테스트.

프론트엔드는 빌드도 JS 테스트 러너도 없는 바닐라 SPA라 소스 수준에서 막는다.

막으려는 사고: **잘못된 체크리스트의 실패는 에러가 아니라 조용한 0건이다.**
패턴이 안 맞으면 요건 ID를 한 개도 못 찾고 화면에는 "지적 없음"이 뜬다 —
검토를 통과한 것처럼 보인다. 실측으로 두 번 재현했다.

  · SKN56 문서 + SHN34 체크리스트(FR-GC_01) -> ID 0개
  · SHN34 문서 + SKN56 체크리스트(FR1-0305) -> ID 0개

같은 실에서 온 문서인데도 ID 체계가 다르기 때문이다. 어떤 기본값도 옳을 수
없으므로, 안전장치는 기본값이 아니라 **문서를 재보는 쪽**에 둔다.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
APP_JS = (_ROOT / "web" / "app.js").read_text(encoding="utf-8")
VIEWS_JS = (_ROOT / "web" / "views.js").read_text(encoding="utf-8")
SERVER_PY = (_ROOT / "src" / "app" / "server.py").read_text(encoding="utf-8")


def test_server_exposes_the_detect_endpoint() -> None:
    assert '"/api/detect"' in SERVER_PY


def test_app_measures_the_document_after_it_is_picked() -> None:
    """고르기 전에 재야 한다. 검토를 돌린 뒤에 알려주면 이미 늦었다."""
    assert "api/detect" in APP_JS, "업로드한 문서를 재지 않는다"


def test_app_keeps_the_detection_result_in_state() -> None:
    assert "state.detect" in APP_JS


def test_detection_does_not_override_an_explicit_choice() -> None:
    """검토자가 직접 고른 기준을 도구가 말없이 갈아치우면 안 된다.
    자동 선택은 아무것도 안 골랐을 때만이다."""
    assert "state.checklistPicked" in APP_JS


def test_screen_warns_when_the_picked_checklist_matches_nothing() -> None:
    """이 경고가 없으면 '0건'이 통과로 읽힌다 — 막으려던 바로 그 사고다."""
    assert "detectWarn" in VIEWS_JS


def test_screen_shows_how_many_ids_were_found() -> None:
    """개수를 보여줘야 검토자가 기준이 맞는지 스스로 판단할 수 있다."""
    assert "detectCount" in VIEWS_JS


def test_server_reports_whether_the_checklist_has_a_pattern() -> None:
    assert '"has_pattern"' in SERVER_PY


def test_no_warning_for_checklists_without_an_id_pattern() -> None:
    """단일문서용 체크리스트(rvvr-standard 등)는 요건 ID 를 보지 않는다.

    매칭 0개를 결함처럼 경고하면 정상 사용에서 붉은 띠가 떠 배너 자체가
    무시된다 — 경고를 무시하게 만드는 경고는 없느니만 못하다.
    """
    assert "has_pattern" in VIEWS_JS, "화면이 id_pattern 유무를 보지 않는다"


def test_automatic_criteria_is_named_apart_from_the_manual_checklist() -> None:
    """엔진 기준과 사람이 채우는 체크리스트가 한 화면에 있다. 둘 다 '체크리스트'라
    부르면 검토자가 무엇을 고르는지 모른다 — 실제로 사용자가 헷갈렸다.
    엔진 쪽은 '자동 검토 기준'으로 부른다."""
    assert "자동 검토 기준" in VIEWS_JS
    assert "적용할 체크리스트" not in VIEWS_JS   # 옛 이름이 남아 있으면 안 된다
